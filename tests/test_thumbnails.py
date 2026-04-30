"""Tests for jason.ingestion.thumbnails — fully mocked."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
import respx
from httpx import Response

from jason.config import get_settings
from jason.ingestion.thumbnails import download_all

CHANNEL_A = "UCthumbA0000000000000000"
CHANNEL_B = "UCthumbB0000000000000000"


def _setup_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    db = tmp_path / "warehouse.duckdb"
    thumbs_dir = tmp_path / "thumbnails"
    monkeypatch.setenv("DUCKDB_PATH", str(db))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    db.parent.mkdir(parents=True, exist_ok=True)
    schema = Path("migrations/001_init.sql").read_text(encoding="utf-8")
    with duckdb.connect(str(db)) as con:
        con.execute(schema)
    return db, thumbs_dir


def _seed(db: Path, rows: list[tuple[str, str, str | None]]) -> None:
    """rows: list of (channel_id, video_id, thumbnail_url-or-None)."""
    with duckdb.connect(str(db)) as con:
        seen: set[str] = set()
        for ch, _, _ in rows:
            if ch in seen:
                continue
            con.execute(
                "INSERT INTO channels (id, title) VALUES (?, ?) ON CONFLICT (id) DO NOTHING",
                [ch, "T"],
            )
            seen.add(ch)
        for ch, vid, url in rows:
            con.execute(
                "INSERT INTO videos (id, channel_id, title, published_at, thumbnail_url) "
                "VALUES (?, ?, ?, ?, ?)",
                [vid, ch, f"t-{vid}", "2026-04-01T00:00:00Z", url],
            )


@respx.mock
def test_download_all_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, thumbs_dir = _setup_db(monkeypatch, tmp_path)
    _seed(
        db,
        [
            (CHANNEL_A, "vid_thumb01", "https://i.ytimg.com/vi/vid_thumb01/maxresdefault.jpg"),
            (CHANNEL_A, "vid_thumb02", "https://i.ytimg.com/vi/vid_thumb02/maxresdefault.jpg"),
        ],
    )
    fake_jpeg = b"\xff\xd8\xff\xe0fake-jpeg"
    respx.get("https://i.ytimg.com/vi/vid_thumb01/maxresdefault.jpg").mock(
        return_value=Response(200, content=fake_jpeg)
    )
    respx.get("https://i.ytimg.com/vi/vid_thumb02/maxresdefault.jpg").mock(
        return_value=Response(200, content=fake_jpeg)
    )

    result = download_all()

    assert result == {"requested": 2, "downloaded": 2, "skipped": 0, "failed": 0}
    assert (thumbs_dir / "vid_thumb01.jpg").read_bytes() == fake_jpeg
    assert (thumbs_dir / "vid_thumb02.jpg").read_bytes() == fake_jpeg


@respx.mock
def test_download_skips_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, thumbs_dir = _setup_db(monkeypatch, tmp_path)
    _seed(db, [(CHANNEL_A, "vid_skip001", "https://example/already.jpg")])
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    (thumbs_dir / "vid_skip001.jpg").write_bytes(b"old-bytes")
    route = respx.get("https://example/already.jpg")

    result = download_all()
    assert result == {"requested": 1, "downloaded": 0, "skipped": 1, "failed": 0}
    assert route.call_count == 0
    assert (thumbs_dir / "vid_skip001.jpg").read_bytes() == b"old-bytes"


@respx.mock
def test_force_redownloads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, thumbs_dir = _setup_db(monkeypatch, tmp_path)
    _seed(db, [(CHANNEL_A, "vid_force001", "https://example/force.jpg")])
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    (thumbs_dir / "vid_force001.jpg").write_bytes(b"old-bytes")
    respx.get("https://example/force.jpg").mock(
        return_value=Response(200, content=b"NEW-bytes")
    )

    result = download_all(force=True)
    assert result == {"requested": 1, "downloaded": 1, "skipped": 0, "failed": 0}
    assert (thumbs_dir / "vid_force001.jpg").read_bytes() == b"NEW-bytes"


@respx.mock
def test_failed_download_does_not_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, thumbs_dir = _setup_db(monkeypatch, tmp_path)
    _seed(
        db,
        [
            (CHANNEL_A, "vid_fail001", "https://example/404.jpg"),
            (CHANNEL_A, "vid_ok00001", "https://example/ok.jpg"),
        ],
    )
    respx.get("https://example/404.jpg").mock(return_value=Response(404))
    respx.get("https://example/ok.jpg").mock(return_value=Response(200, content=b"ok"))

    result = download_all()
    assert result == {"requested": 2, "downloaded": 1, "skipped": 0, "failed": 1}
    assert (thumbs_dir / "vid_ok00001.jpg").exists()
    assert not (thumbs_dir / "vid_fail001.jpg").exists()


@respx.mock
def test_channel_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, thumbs_dir = _setup_db(monkeypatch, tmp_path)
    _seed(
        db,
        [
            (CHANNEL_A, "vid_chanA01", "https://example/A.jpg"),
            (CHANNEL_B, "vid_chanB01", "https://example/B.jpg"),
        ],
    )
    respx.get("https://example/A.jpg").mock(return_value=Response(200, content=b"A"))
    route_b = respx.get("https://example/B.jpg")

    result = download_all(channel_id=CHANNEL_A)
    assert result == {"requested": 1, "downloaded": 1, "skipped": 0, "failed": 0}
    assert route_b.call_count == 0
    assert (thumbs_dir / "vid_chanA01.jpg").exists()
    assert not (thumbs_dir / "vid_chanB01.jpg").exists()


def test_empty_db_returns_zeros(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_db(monkeypatch, tmp_path)
    assert download_all() == {"requested": 0, "downloaded": 0, "skipped": 0, "failed": 0}


def test_videos_without_url_are_excluded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, _ = _setup_db(monkeypatch, tmp_path)
    _seed(db, [(CHANNEL_A, "vid_nourl001", None)])
    result = download_all()
    assert result == {"requested": 0, "downloaded": 0, "skipped": 0, "failed": 0}


@respx.mock
def test_empty_response_counts_as_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """200 with empty body must NOT create a 0-byte file the embedder will choke on."""
    db, thumbs_dir = _setup_db(monkeypatch, tmp_path)
    _seed(db, [(CHANNEL_A, "vid_empty001", "https://example/empty.jpg")])
    respx.get("https://example/empty.jpg").mock(return_value=Response(200, content=b""))

    result = download_all()
    assert result == {"requested": 1, "downloaded": 0, "skipped": 0, "failed": 1}
    assert not (thumbs_dir / "vid_empty001.jpg").exists()
