"""Tests for jason.ingestion.youtube_data — fully mocked, no live API calls."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
import respx
from httpx import Response

from jason.config import get_settings
from jason.ingestion.youtube_data import (
    YT_CHANNELS_URL,
    YT_PLAYLIST_ITEMS_URL,
    YT_VIDEOS_URL,
    ingest_channel,
    is_short_video,
    parse_iso_duration,
)

CHANNEL_ID = "UCabc12345678901234567890"
UPLOADS_ID = "UUabc12345678901234567890"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "iso, expected",
    [
        ("PT0S", 0),
        ("PT45S", 45),
        ("PT4M13S", 4 * 60 + 13),
        ("PT1H", 3600),
        ("PT1H2M3S", 3600 + 120 + 3),
        ("P1DT2H", 86400 + 7200),
        ("", 0),
        ("garbage", 0),
    ],
)
def test_parse_iso_duration(iso: str, expected: int) -> None:
    assert parse_iso_duration(iso) == expected


@pytest.mark.parametrize(
    "duration_s, title, description, expected",
    [
        (45, "normal title", "", True),       # well below cap
        (60, "edge case", "", True),          # legacy 60s threshold (still a Short)
        (180, "boundary", "", True),           # current 180s cap
        (181, "just past the cap", "", False), # crosses into long-form
        (300, "Trailer #Shorts", "", True),   # tag in title overrides duration
        (300, "Trailer", "Veja em #shorts!", True),  # tag in description
        (300, "Long shortcut", "no tag here", False),  # 'short' substring without #
        (3600, "Full review", "", False),     # full-length video
    ],
)
def test_is_short_video(duration_s: int, title: str, description: str, expected: bool) -> None:
    assert is_short_video(duration_s, title, description) is expected


# ---------------------------------------------------------------------------
# End-to-end ingest_channel with mocked HTTP
# ---------------------------------------------------------------------------


def _setup_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    db = tmp_path / "warehouse.duckdb"
    raw_dir = tmp_path / "raw"
    monkeypatch.setenv("YOUTUBE_DATA_API_KEY", "fake-key")
    monkeypatch.setenv("DUCKDB_PATH", str(db))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    # Apply the real schema so foreign keys work.
    db.parent.mkdir(parents=True, exist_ok=True)
    schema = Path("migrations/001_init.sql").read_text(encoding="utf-8")
    with duckdb.connect(str(db)) as con:
        con.execute(schema)
    return db, raw_dir


def _channel_response() -> dict:
    return {
        "items": [
            {
                "id": CHANNEL_ID,
                "snippet": {"title": "Hora do Terror", "customUrl": "@horadoterror"},
                "statistics": {"subscriberCount": "42000"},
                "contentDetails": {"relatedPlaylists": {"uploads": UPLOADS_ID}},
            }
        ]
    }


def _playlist_page(video_ids: list[str], next_token: str | None = None) -> dict:
    body: dict = {
        "items": [{"contentDetails": {"videoId": vid}} for vid in video_ids],
    }
    if next_token:
        body["nextPageToken"] = next_token
    return body


def _video_item(
    vid: str, *, duration: str = "PT8M30S", title: str = "Filme Perturbador EXPLICADO",
    views: int = 12345, likes: int = 678, comments: int = 90, description: str = "",
    published: str = "2026-04-01T18:00:00Z",
) -> dict:
    return {
        "id": vid,
        "snippet": {
            "title": title,
            "description": description,
            "publishedAt": published,
            "thumbnails": {
                "maxres": {"url": f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg"},
                "high": {"url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"},
            },
        },
        "contentDetails": {"duration": duration},
        "statistics": {
            "viewCount": str(views),
            "likeCount": str(likes),
            "commentCount": str(comments),
        },
    }


@respx.mock
def test_ingest_channel_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, raw_dir = _setup_settings(monkeypatch, tmp_path)

    respx.get(YT_CHANNELS_URL).mock(return_value=Response(200, json=_channel_response()))
    respx.get(YT_PLAYLIST_ITEMS_URL).mock(
        return_value=Response(200, json=_playlist_page(["vid_aaaa001", "vid_aaaa002"]))
    )
    respx.get(YT_VIDEOS_URL).mock(
        return_value=Response(
            200,
            json={
                "items": [
                    _video_item("vid_aaaa001", duration="PT8M30S", views=12345),
                    _video_item("vid_aaaa002", duration="PT45S", title="Trailer #shorts", views=999),
                ]
            },
        )
    )

    result = ingest_channel(CHANNEL_ID)

    assert result["video_count"] == 2
    assert result["snapshot_count"] == 2
    assert result["raw_dump_path"].exists()
    assert result["raw_dump_path"].read_text(encoding="utf-8").count("\n") == 2

    with duckdb.connect(str(db)) as con:
        ch = con.execute("SELECT id, title, handle, subs FROM channels").fetchone()
        assert ch == (CHANNEL_ID, "Hora do Terror", "horadoterror", 42000)

        rows = con.execute(
            "SELECT id, duration_s, is_short FROM videos ORDER BY id"
        ).fetchall()
        assert rows == [("vid_aaaa001", 510, False), ("vid_aaaa002", 45, True)]

        snaps = con.execute(
            "SELECT video_id, views, likes FROM video_stats_snapshots ORDER BY video_id"
        ).fetchall()
        assert snaps == [("vid_aaaa001", 12345, 678), ("vid_aaaa002", 999, 678)]


@respx.mock
def test_ingest_channel_paginates_playlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, _ = _setup_settings(monkeypatch, tmp_path)

    respx.get(YT_CHANNELS_URL).mock(return_value=Response(200, json=_channel_response()))
    respx.get(YT_PLAYLIST_ITEMS_URL).mock(
        side_effect=[
            Response(200, json=_playlist_page(["vid_p1_001", "vid_p1_002"], next_token="TOKEN_2")),
            Response(200, json=_playlist_page(["vid_p2_001"])),
        ]
    )
    respx.get(YT_VIDEOS_URL).mock(
        return_value=Response(
            200,
            json={
                "items": [
                    _video_item("vid_p1_001"),
                    _video_item("vid_p1_002"),
                    _video_item("vid_p2_001"),
                ]
            },
        )
    )

    result = ingest_channel(CHANNEL_ID)
    assert result["video_count"] == 3

    with duckdb.connect(str(db)) as con:
        count = con.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        assert count == 3


@respx.mock
def test_ingest_channel_is_idempotent_on_videos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running twice should keep one row per video and append a 2nd snapshot."""
    db, _ = _setup_settings(monkeypatch, tmp_path)

    respx.get(YT_CHANNELS_URL).mock(return_value=Response(200, json=_channel_response()))
    respx.get(YT_PLAYLIST_ITEMS_URL).mock(
        return_value=Response(200, json=_playlist_page(["vid_idem0001"]))
    )
    # Different captured timestamps -> different snapshot rows.
    respx.get(YT_VIDEOS_URL).mock(
        side_effect=[
            Response(200, json={"items": [_video_item("vid_idem0001", views=1000)]}),
            Response(200, json={"items": [_video_item("vid_idem0001", views=1500)]}),
        ]
    )

    ingest_channel(CHANNEL_ID)
    # Force a different captured_at by sleeping is gross — instead, verify
    # the upsert + snapshot semantics directly.
    import time
    time.sleep(1.1)
    ingest_channel(CHANNEL_ID)

    with duckdb.connect(str(db)) as con:
        videos = con.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        snaps = con.execute("SELECT COUNT(*) FROM video_stats_snapshots").fetchone()[0]
        views_history = con.execute(
            "SELECT views FROM video_stats_snapshots ORDER BY captured_at"
        ).fetchall()
    assert videos == 1
    assert snaps == 2
    assert [r[0] for r in views_history] == [1000, 1500]


def test_missing_api_key_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOUTUBE_DATA_API_KEY", "")
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "wh.duckdb"))
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="YOUTUBE_DATA_API_KEY"):
        ingest_channel(CHANNEL_ID)
