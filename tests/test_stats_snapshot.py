"""Tests for jason.ingestion.stats_snapshot — fully mocked."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest
import respx
from httpx import Response

from jason.config import get_settings
from jason.ingestion.stats_snapshot import snapshot_all
from jason.ingestion.youtube_data import YT_VIDEOS_URL

CHANNEL_A = "UCchanA00000000000000000"
CHANNEL_B = "UCchanB00000000000000000"


def _setup_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db = tmp_path / "warehouse.duckdb"
    monkeypatch.setenv("YOUTUBE_DATA_API_KEY", "fake-key")
    monkeypatch.setenv("DUCKDB_PATH", str(db))
    get_settings.cache_clear()
    db.parent.mkdir(parents=True, exist_ok=True)
    schema = Path("migrations/001_init.sql").read_text(encoding="utf-8")
    with duckdb.connect(str(db)) as con:
        con.execute(schema)
    return db


def _seed_videos(db: Path, videos: list[tuple[str, str, str]]) -> None:
    """Insert (channel_id, video_id, published_at_iso) rows so snapshot_all can read them."""
    with duckdb.connect(str(db)) as con:
        seen_channels: set[str] = set()
        for channel_id, _, _ in videos:
            if channel_id in seen_channels:
                continue
            con.execute(
                "INSERT INTO channels (id, title) VALUES (?, ?) ON CONFLICT (id) DO NOTHING",
                [channel_id, "Test Channel"],
            )
            seen_channels.add(channel_id)
        for channel_id, vid, pub in videos:
            con.execute(
                """
                INSERT INTO videos (id, channel_id, title, published_at, duration_s, is_short)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [vid, channel_id, f"Title for {vid}", pub, 600, False],
            )


def _stats_item(vid: str, views: int, likes: int = 10, comments: int = 5) -> dict:
    return {
        "id": vid,
        "statistics": {
            "viewCount": str(views),
            "likeCount": str(likes),
            "commentCount": str(comments),
        },
    }


@respx.mock
def test_snapshot_all_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _setup_db(monkeypatch, tmp_path)
    pub_30d_ago = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    _seed_videos(
        db,
        [
            (CHANNEL_A, "vid_aaaa0001", pub_30d_ago),
            (CHANNEL_A, "vid_aaaa0002", pub_30d_ago),
        ],
    )
    respx.get(YT_VIDEOS_URL).mock(
        return_value=Response(
            200,
            json={"items": [_stats_item("vid_aaaa0001", 1000), _stats_item("vid_aaaa0002", 2000)]},
        )
    )

    result = snapshot_all()

    assert result["requested"] == 2
    assert result["snapshotted"] == 2
    assert result["missing"] == 0

    with duckdb.connect(str(db)) as con:
        rows = con.execute(
            "SELECT video_id, days_since_publish, views FROM video_stats_snapshots ORDER BY video_id"
        ).fetchall()
    assert rows[0][0] == "vid_aaaa0001"
    assert rows[0][1] in (29, 30)  # tolerate clock drift across the test
    assert rows[0][2] == 1000
    assert rows[1] == ("vid_aaaa0002", rows[0][1], 2000)


@respx.mock
def test_snapshot_skips_missing_videos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the API doesn't return a video (private/deleted), no row is written."""
    db = _setup_db(monkeypatch, tmp_path)
    pub = "2026-04-01T10:00:00Z"
    _seed_videos(
        db,
        [
            (CHANNEL_A, "vid_alive0001", pub),
            (CHANNEL_A, "vid_dead00001", pub),
        ],
    )
    # API returns only the live one.
    respx.get(YT_VIDEOS_URL).mock(
        return_value=Response(200, json={"items": [_stats_item("vid_alive0001", 500)]})
    )

    result = snapshot_all()

    assert result["requested"] == 2
    assert result["snapshotted"] == 1
    assert result["missing"] == 1

    with duckdb.connect(str(db)) as con:
        ids = [r[0] for r in con.execute("SELECT video_id FROM video_stats_snapshots").fetchall()]
    assert ids == ["vid_alive0001"]


@respx.mock
def test_snapshot_batches_above_50(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """75 videos -> 2 calls (50 + 25)."""
    db = _setup_db(monkeypatch, tmp_path)
    pub = "2026-03-01T10:00:00Z"
    videos = [(CHANNEL_A, f"vid_b{i:07d}", pub) for i in range(75)]
    _seed_videos(db, videos)

    route = respx.get(YT_VIDEOS_URL).mock(
        side_effect=[
            Response(
                200,
                json={"items": [_stats_item(f"vid_b{i:07d}", 100 + i) for i in range(50)]},
            ),
            Response(
                200,
                json={"items": [_stats_item(f"vid_b{i:07d}", 100 + i) for i in range(50, 75)]},
            ),
        ]
    )

    result = snapshot_all()
    assert route.call_count == 2
    assert result["snapshotted"] == 75


@respx.mock
def test_snapshot_channel_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--channel filters which videos are sent to the API."""
    db = _setup_db(monkeypatch, tmp_path)
    pub = "2026-04-01T10:00:00Z"
    _seed_videos(
        db,
        [
            (CHANNEL_A, "vid_chanA0001", pub),
            (CHANNEL_B, "vid_chanB0001", pub),
        ],
    )
    respx.get(YT_VIDEOS_URL).mock(
        return_value=Response(200, json={"items": [_stats_item("vid_chanA0001", 999)]})
    )

    result = snapshot_all(channel_id=CHANNEL_A)
    assert result["requested"] == 1
    assert result["snapshotted"] == 1

    with duckdb.connect(str(db)) as con:
        ids = [r[0] for r in con.execute("SELECT video_id FROM video_stats_snapshots").fetchall()]
    assert ids == ["vid_chanA0001"]


def test_snapshot_no_videos_in_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty DB shouldn't call the API at all."""
    _setup_db(monkeypatch, tmp_path)
    result = snapshot_all()
    assert result == {
        "requested": 0,
        "snapshotted": 0,
        "missing": 0,
        "captured_at": result["captured_at"],
    }


def test_snapshot_missing_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOUTUBE_DATA_API_KEY", "")
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "wh.duckdb"))
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="YOUTUBE_DATA_API_KEY"):
        snapshot_all()
