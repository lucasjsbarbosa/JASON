"""Tests for jason.features.outliers."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from jason.config import get_settings
from jason.features.outliers import (
    _trimmed_median,
    compute_multiplier,
    compute_percentile,
    views_at_age,
)

CHANNEL_A = "UCoutA00000000000000000z"


def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db = tmp_path / "warehouse.duckdb"
    monkeypatch.setenv("DUCKDB_PATH", str(db))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    db.parent.mkdir(parents=True, exist_ok=True)
    schema_001 = Path("migrations/001_init.sql").read_text(encoding="utf-8")
    with duckdb.connect(str(db)) as con:
        con.execute(schema_001)
    return db


def _seed_video(
    con: duckdb.DuckDBPyConnection,
    video_id: str,
    *,
    channel_id: str = CHANNEL_A,
    published_at: str = "2026-01-01T00:00:00Z",
    is_short: bool = False,
) -> None:
    con.execute(
        "INSERT OR IGNORE INTO channels (id, title) VALUES (?, ?)", [channel_id, "C"]
    )
    con.execute(
        "INSERT INTO videos (id, channel_id, title, published_at, is_short) "
        "VALUES (?, ?, ?, ?, ?)",
        [video_id, channel_id, f"t-{video_id}", published_at, is_short],
    )


def _seed_snapshot(
    con: duckdb.DuckDBPyConnection,
    video_id: str,
    *,
    days_since_publish: int,
    views: int,
    captured_at: datetime | None = None,
) -> None:
    if captured_at is None:
        captured_at = datetime(2026, 4, 30, 0, 0, 0) + timedelta(seconds=days_since_publish)
    con.execute(
        """
        INSERT INTO video_stats_snapshots
            (video_id, captured_at, days_since_publish, views, likes, comments)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [video_id, captured_at, days_since_publish, views, 0, 0],
    )


# ---------------------------------------------------------------------------
# views_at_age
# ---------------------------------------------------------------------------


def test_views_at_age_no_snapshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _setup(monkeypatch, tmp_path)
    with duckdb.connect(str(db)) as con:
        _seed_video(con, "vid_empty01")
        assert views_at_age(con, "vid_empty01", target_days=28) is None


def test_views_at_age_only_younger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Video too young (all snapshots before target_days) → None."""
    db = _setup(monkeypatch, tmp_path)
    with duckdb.connect(str(db)) as con:
        _seed_video(con, "vid_young01")
        _seed_snapshot(con, "vid_young01", days_since_publish=5, views=100)
        _seed_snapshot(con, "vid_young01", days_since_publish=15, views=500)
        assert views_at_age(con, "vid_young01", target_days=28) is None


def test_views_at_age_only_older(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """All snapshots after target_days (we started tracking too late) → None."""
    db = _setup(monkeypatch, tmp_path)
    with duckdb.connect(str(db)) as con:
        _seed_video(con, "vid_late0001")
        _seed_snapshot(con, "vid_late0001", days_since_publish=100, views=10000)
        assert views_at_age(con, "vid_late0001", target_days=28) is None


def test_views_at_age_exact_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _setup(monkeypatch, tmp_path)
    with duckdb.connect(str(db)) as con:
        _seed_video(con, "vid_exact001")
        _seed_snapshot(con, "vid_exact001", days_since_publish=28, views=5000)
        assert views_at_age(con, "vid_exact001", target_days=28) == 5000


def test_views_at_age_interpolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Linear interpolation between snapshots at age 14 (1000 views) and age 35 (8000)."""
    db = _setup(monkeypatch, tmp_path)
    with duckdb.connect(str(db)) as con:
        _seed_video(con, "vid_interp01")
        _seed_snapshot(con, "vid_interp01", days_since_publish=14, views=1000)
        _seed_snapshot(con, "vid_interp01", days_since_publish=35, views=8000)
        # target=28 → frac = (28-14)/(35-14) = 14/21 ≈ 0.6667
        # views = 1000 + 0.6667 * 7000 = 1000 + 4667 = 5667
        result = views_at_age(con, "vid_interp01", target_days=28)
        assert result is not None
        assert 5660 <= result <= 5670


def test_views_at_age_picks_closest_bracket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With multiple snapshots on each side, we pick the closest pair to target."""
    db = _setup(monkeypatch, tmp_path)
    with duckdb.connect(str(db)) as con:
        _seed_video(con, "vid_brack001")
        _seed_snapshot(con, "vid_brack001", days_since_publish=5,  views=200)
        _seed_snapshot(con, "vid_brack001", days_since_publish=25, views=4000)   # closest before
        _seed_snapshot(con, "vid_brack001", days_since_publish=30, views=5000)   # closest after
        _seed_snapshot(con, "vid_brack001", days_since_publish=60, views=10000)
        # Should bracket between 25 and 30:
        #   frac = (28-25)/(30-25) = 3/5 = 0.6
        #   views = 4000 + 0.6 * 1000 = 4600
        assert views_at_age(con, "vid_brack001", target_days=28) == 4600


# ---------------------------------------------------------------------------
# compute_multiplier
# ---------------------------------------------------------------------------


def _seed_eligible(
    con: duckdb.DuckDBPyConnection, vid: str, published_at: str, views_at_28: int
) -> None:
    """Seed a video + bracketing snapshots so views_at_age(28) == views_at_28."""
    _seed_video(con, vid, published_at=published_at)
    # snapshot at day 28 exact = simplest
    _seed_snapshot(con, vid, days_since_publish=28, views=views_at_28)


def test_compute_multiplier_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """15 chronological videos, all eligible. The 16th should get
    multiplier = its views / median of the previous 15 (or up to baseline_n)."""
    db = _setup(monkeypatch, tmp_path)
    with duckdb.connect(str(db)) as con:
        # 15 baseline videos with views_at_28 = 100, 200, ..., 1500
        for i in range(1, 16):
            _seed_eligible(con, f"vid_base{i:03d}", f"2026-0{((i-1)//5)+1}-{((i-1)%5)+1:02d}T00:00:00Z", i * 100)
        # 16th video — should get a multiplier vs median of previous 15 (median = 800)
        _seed_eligible(con, "vid_target01", "2026-04-01T00:00:00Z", 4000)

    result = compute_multiplier(CHANNEL_A, db_path=db)
    assert result["total_videos"] == 16
    assert result["eligible"] == 16
    # First 10 get NULL (less than min_baseline=10 prior); 11..15 get multiplier; 16 too.
    # Actually first 10 have <10 prior → skipped_no_baseline = 10
    # 11..15: 5 videos with multipliers
    # 16: 1 video
    assert result["computed"] == 6
    assert result["skipped_no_baseline"] == 10

    with duckdb.connect(str(db)) as con:
        target_mult = con.execute(
            "SELECT multiplier FROM outliers WHERE video_id = ?", ["vid_target01"]
        ).fetchone()[0]
        # baseline = last 30 prior eligible = all 15 prior; median of [100..1500] = 800
        assert abs(target_mult - 4000 / 800) < 1e-6  # 5.0


def test_compute_multiplier_skips_shorts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _setup(monkeypatch, tmp_path)
    with duckdb.connect(str(db)) as con:
        for i in range(20):
            _seed_video(con, f"vid_long{i:03d}", published_at=f"2026-04-{i+1:02d}T00:00:00Z")
            _seed_snapshot(con, f"vid_long{i:03d}", days_since_publish=28, views=1000)
        # A short with HUGE views — should NOT be in eligible
        _seed_video(con, "vid_short001", is_short=True, published_at="2026-04-15T00:00:00Z")
        _seed_snapshot(con, "vid_short001", days_since_publish=28, views=999_999_999)

    result = compute_multiplier(CHANNEL_A, db_path=db)
    assert result["total_videos"] == 20  # short excluded from total query
    with duckdb.connect(str(db)) as con:
        # Make sure the short isn't in outliers
        n = con.execute(
            "SELECT COUNT(*) FROM outliers WHERE video_id = ?", ["vid_short001"]
        ).fetchone()[0]
    assert n == 0


def test_compute_multiplier_below_min_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A channel with only 5 eligible videos: nobody gets a multiplier (need 10 prior)."""
    db = _setup(monkeypatch, tmp_path)
    with duckdb.connect(str(db)) as con:
        for i in range(5):
            _seed_eligible(con, f"vid_thin{i:03d}", f"2026-04-{i+1:02d}T00:00:00Z", 1000)

    result = compute_multiplier(CHANNEL_A, db_path=db)
    assert result["computed"] == 0
    assert result["skipped_no_baseline"] == 5
    with duckdb.connect(str(db)) as con:
        n = con.execute("SELECT COUNT(*) FROM outliers").fetchone()[0]
    assert n == 0


def test_compute_multiplier_skips_no_age_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Videos without bracketing snapshots are dropped before the baseline check."""
    db = _setup(monkeypatch, tmp_path)
    with duckdb.connect(str(db)) as con:
        # 11 eligible
        for i in range(11):
            _seed_eligible(con, f"vid_ok{i:04d}", f"2026-04-{i+1:02d}T00:00:00Z", (i + 1) * 100)
        # 5 videos with only late snapshots (no early bracket)
        for i in range(5):
            _seed_video(con, f"vid_late{i:03d}", published_at=f"2026-04-{i+15:02d}T00:00:00Z")
            _seed_snapshot(con, f"vid_late{i:03d}", days_since_publish=100, views=99_999)

    result = compute_multiplier(CHANNEL_A, db_path=db)
    assert result["total_videos"] == 16
    assert result["eligible"] == 11
    assert result["skipped_no_age_data"] == 5


# ---------------------------------------------------------------------------
# compute_percentile
# ---------------------------------------------------------------------------


def test_compute_percentile_basic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """20 videos in the same window: of those, only the last 10 get multipliers
    (need 10 prior eligible). Use non-linear views so the resulting multipliers
    actually vary (linear views + linear baseline = constant multiplier coincidence)."""
    db = _setup(monkeypatch, tmp_path)
    # 10 baseline videos at flat 1000 views, then 10 "test" videos with
    # heterogeneous views — yields multipliers spread across low/mid/high.
    baseline_views = [1000] * 10
    test_views = [500, 800, 1000, 1200, 1500, 2000, 3000, 5000, 8000, 12000]

    with duckdb.connect(str(db)) as con:
        for i, v in enumerate(baseline_views + test_views):
            day = (i % 28) + 1
            _seed_eligible(
                con, f"vid_pct{i:03d}", f"2026-01-{day:02d}T00:00:00Z", v
            )

    compute_multiplier(CHANNEL_A, db_path=db)
    p = compute_percentile(CHANNEL_A, db_path=db, window_days=90)
    assert p["computed"] >= 5

    with duckdb.connect(str(db)) as con:
        rows = con.execute(
            "SELECT video_id, multiplier, percentile_in_channel FROM outliers "
            "ORDER BY multiplier"
        ).fetchall()

    # 10 multipliers, increasing (test_views is monotonic and baseline median is stable)
    assert len(rows) == 10
    multipliers = [r[1] for r in rows]
    assert multipliers == sorted(multipliers)
    # percentile is monotonic with multiplier within the same window
    percentiles = [r[2] for r in rows]
    assert percentiles[0] < percentiles[-1]
    # top multiplier should land at the top of the distribution
    assert percentiles[-1] >= 90.0
    # bottom multiplier should land near the bottom
    assert percentiles[0] <= 10.0


# ---------------------------------------------------------------------------
# trimmed median (rolling-baseline robustness)
# ---------------------------------------------------------------------------


def test_trimmed_median_resists_isolated_viral() -> None:
    """Single huge value far above the rest must not move the trimmed median."""
    baseline = [100] * 29 + [1_000_000]
    assert _trimmed_median(baseline, trim_frac=0.1) == 100


def test_trimmed_median_matches_plain_median_for_small_n() -> None:
    """With <10 values, k=int(n*0.1) collapses to 0 and trimmed == plain median."""
    arr = [1, 2, 3, 4, 5]
    assert _trimmed_median(arr, trim_frac=0.1) == 3


def test_trimmed_median_handles_low_outliers_too() -> None:
    """Bottom-tail outliers also dropped (a long-dead channel firing back up)."""
    baseline = [10] + [1000] * 28 + [9999]
    out = _trimmed_median(baseline, trim_frac=0.1)
    assert 900 <= out <= 1100  # core mass survives, tails dropped
