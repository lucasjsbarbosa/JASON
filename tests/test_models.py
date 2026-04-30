"""Tests for jason.models — buckets + features assembly.

Training/predict tests are skipped unless the `ml` deps are installed
(lightgbm/sklearn). Most of the logic that's NOT covered by the heavy ML
path is in the feature assembly, so we test that thoroughly.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from jason.config import get_settings
from jason.models.buckets import bucket_of

CHANNEL_A = "UCmodelA000000000000000z"


# ---------------------------------------------------------------------------
# bucket_of
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subs, expected",
    [
        (None, 0),
        (0, 0),
        (500, 0),
        (999, 0),
        (1_000, 1),
        (3_480, 1),    # @babygiulybaby
        (9_999, 1),
        (10_000, 2),
        (99_999, 2),
        (100_000, 3),
        (153_000, 3),  # @CineAntiqua
        (999_999, 3),
        (1_000_000, 4),
        (3_290_000, 4),  # @JuMCassini
    ],
)
def test_bucket_of(subs: int | None, expected: int) -> None:
    assert bucket_of(subs) == expected


# ---------------------------------------------------------------------------
# build_feature_matrix — guarded behind pandas import
# ---------------------------------------------------------------------------

pandas = pytest.importorskip("pandas", reason="pandas is in the optional ml group")


def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db = tmp_path / "warehouse.duckdb"
    monkeypatch.setenv("DUCKDB_PATH", str(db))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    db.parent.mkdir(parents=True, exist_ok=True)
    for sql_file in (
        "001_init.sql", "003_horror_releases.sql",
        "004_video_features.sql", "005_embeddings.sql", "006_topics.sql",
        "010_paper_backed_features.sql",
        "011_paper_backed_features_v2.sql",
    ):
        with duckdb.connect(str(db)) as con:
            con.execute(Path(f"migrations/{sql_file}").read_text(encoding="utf-8"))
    return db


def _seed(db: Path, *, video_id: str, channel_id: str, title: str, subs: int,
          published_at: str, multiplier: float | None = None,
          theme_id: int = -1, franchise_id: int = -1) -> None:
    with duckdb.connect(str(db)) as con:
        con.execute(
            "INSERT OR IGNORE INTO channels (id, title, subs) VALUES (?, ?, ?)",
            [channel_id, "C", subs],
        )
        con.execute(
            "INSERT INTO videos (id, channel_id, title, published_at, duration_s, is_short) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [video_id, channel_id, title, published_at, 600, False],
        )
        con.execute(
            "INSERT INTO video_features (video_id, char_len, word_count, caps_ratio, "
            "has_number, has_emoji, has_question_mark, has_caps_word, has_first_person, "
            "has_explained_keyword, has_ranking_keyword, has_curiosity_keyword, "
            "has_extreme_adjective, theme_id, franchise_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [video_id, len(title), len(title.split()), 0.0,
             False, False, False, False, False, False, False, False, False,
             theme_id, franchise_id],
        )
        if multiplier is not None:
            con.execute(
                "INSERT INTO outliers (video_id, multiplier) VALUES (?, ?)",
                [video_id, multiplier],
            )


def test_build_feature_matrix_basic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from jason.models.features import build_feature_matrix

    db = _setup(monkeypatch, tmp_path)
    _seed(db, video_id="vid_b001", channel_id=CHANNEL_A, title="Hereditário",
          subs=3480, published_at="2026-04-01T10:00:00Z", multiplier=2.5)
    _seed(db, video_id="vid_b002", channel_id=CHANNEL_A, title="Top 10",
          subs=3480, published_at="2026-04-15T18:00:00Z", multiplier=1.2)

    df = build_feature_matrix(db_path=db, only_with_multiplier=True)
    assert len(df) == 2
    assert "subs_bucket" in df.columns
    assert "published_hour" in df.columns
    assert "is_halloween_week" in df.columns
    assert "days_to_nearest_horror_release" in df.columns
    # subs=3480 → bucket 1
    assert (df["subs_bucket"] == 1).all()
    # published 10am UTC → 10
    hours = sorted(df["published_hour"].tolist())
    assert hours == [10, 18]


def test_build_feature_matrix_filters_shorts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from jason.models.features import build_feature_matrix

    db = _setup(monkeypatch, tmp_path)
    _seed(db, video_id="vid_long01", channel_id=CHANNEL_A, title="Long",
          subs=3480, published_at="2026-04-01T10:00:00Z", multiplier=2.0)
    # Insert a Short directly
    with duckdb.connect(str(db)) as con:
        con.execute(
            "INSERT INTO videos (id, channel_id, title, published_at, duration_s, is_short) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ["vid_short01", CHANNEL_A, "Short", "2026-04-01T10:00:00Z", 30, True],
        )
        con.execute(
            "INSERT INTO video_features (video_id, char_len) VALUES (?, ?)",
            ["vid_short01", 5],
        )
        con.execute(
            "INSERT INTO outliers (video_id, multiplier) VALUES (?, ?)",
            ["vid_short01", 5.0],
        )

    df = build_feature_matrix(db_path=db, only_with_multiplier=True)
    assert "vid_short01" not in df.index
    assert "vid_long01" in df.index


def test_build_feature_matrix_only_with_multiplier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from jason.models.features import build_feature_matrix

    db = _setup(monkeypatch, tmp_path)
    _seed(db, video_id="vid_w001", channel_id=CHANNEL_A, title="With",
          subs=3480, published_at="2026-04-01T10:00:00Z", multiplier=1.5)
    _seed(db, video_id="vid_no001", channel_id=CHANNEL_A, title="Without",
          subs=3480, published_at="2026-04-02T10:00:00Z")

    only = build_feature_matrix(db_path=db, only_with_multiplier=True)
    assert list(only.index) == ["vid_w001"]

    full = build_feature_matrix(db_path=db, only_with_multiplier=False)
    assert set(full.index) == {"vid_w001", "vid_no001"}


def test_horror_distance_zero_for_same_day(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from jason.models.features import build_feature_matrix

    db = _setup(monkeypatch, tmp_path)
    with duckdb.connect(str(db)) as con:
        con.execute(
            "INSERT INTO horror_releases (tmdb_id, title, release_date) VALUES (?, ?, ?)",
            [1, "X", "2026-04-01"],
        )
    _seed(db, video_id="vid_d001", channel_id=CHANNEL_A, title="T",
          subs=3480, published_at="2026-04-01T00:00:00Z", multiplier=1.0)
    _seed(db, video_id="vid_d002", channel_id=CHANNEL_A, title="T",
          subs=3480, published_at="2026-04-08T00:00:00Z", multiplier=1.0)

    df = build_feature_matrix(db_path=db, only_with_multiplier=True)
    assert df.loc["vid_d001", "days_to_nearest_horror_release"] == 0
    assert df.loc["vid_d002", "days_to_nearest_horror_release"] == 7


def test_halloween_week_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from jason.models.features import build_feature_matrix

    db = _setup(monkeypatch, tmp_path)
    _seed(db, video_id="vid_hal01", channel_id=CHANNEL_A, title="Halloween",
          subs=3480, published_at="2026-10-31T10:00:00Z", multiplier=1.0)
    _seed(db, video_id="vid_jul01", channel_id=CHANNEL_A, title="July",
          subs=3480, published_at="2026-07-15T10:00:00Z", multiplier=1.0)

    df = build_feature_matrix(db_path=db, only_with_multiplier=True)
    assert df.loc["vid_hal01", "is_halloween_week"] == 1
    assert df.loc["vid_jul01", "is_halloween_week"] == 0
