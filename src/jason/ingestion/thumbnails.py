"""Download thumbnail images for known videos.

Reads `videos.thumbnail_url` (populated by `youtube_data.py` with the highest
available resolution YouTube returned), saves to `data/thumbnails/{video_id}.jpg`,
and skips files that already exist. The maxres URL is used directly — no quota
hit; the YouTube CDN serves it as a regular static asset.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import duckdb
import httpx

from jason.config import get_settings

logger = logging.getLogger(__name__)


def _read_thumbnail_targets(
    con: duckdb.DuckDBPyConnection, channel_id: str | None
) -> list[tuple[str, str]]:
    """Return (video_id, thumbnail_url) pairs for videos whose URL is known."""
    if channel_id:
        rows = con.execute(
            "SELECT id, thumbnail_url FROM videos "
            "WHERE channel_id = ? AND thumbnail_url IS NOT NULL",
            [channel_id],
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT id, thumbnail_url FROM videos WHERE thumbnail_url IS NOT NULL"
        ).fetchall()
    return rows


def download_thumbnail(
    video_id: str,
    url: str,
    *,
    target_dir: Path,
    client: httpx.Client,
    force: bool = False,
) -> tuple[str, Path | None]:
    """Download a single thumbnail. Returns ('downloaded'|'skipped'|'failed', path).

    The path is None only on failure; on skip it's the existing file path.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{video_id}.jpg"

    if target.exists() and not force:
        return "skipped", target

    try:
        response = client.get(url, timeout=15.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("thumbnail %s failed: %s", video_id, exc)
        return "failed", None

    # YouTube's CDN occasionally responds 200 with an empty body for missing
    # maxres assets. Persisting that creates a 0-byte ghost file that the
    # next run skips and that the embedder can't decode — count as failed
    # and leave nothing behind.
    if not response.content:
        logger.warning("thumbnail %s: empty response body", video_id)
        return "failed", None

    target.write_bytes(response.content)
    return "downloaded", target


def download_all(
    *,
    db_path: Path | None = None,
    target_dir: Path | None = None,
    channel_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Walk known videos and download every thumbnail not yet on disk.

    Args:
        db_path: optional DuckDB override (defaults to settings.duckdb_path).
        target_dir: optional override (defaults to `<DATA_DIR>/thumbnails`).
        channel_id: optional UC... filter.
        force: re-download even if the file already exists.

    Returns:
        dict with `requested`, `downloaded`, `skipped`, `failed`.
    """
    settings = get_settings()
    db = db_path or settings.duckdb_path
    out_dir = target_dir or (settings.data_dir / "thumbnails")

    # We only read videos.thumbnail_url here — open read-only so this can run
    # alongside the Streamlit dashboard (which holds its own read connection).
    with duckdb.connect(str(db), read_only=True) as con:
        targets = _read_thumbnail_targets(con, channel_id)

    if not targets:
        return {"requested": 0, "downloaded": 0, "skipped": 0, "failed": 0}

    counts = {"downloaded": 0, "skipped": 0, "failed": 0}
    with httpx.Client() as client:
        for video_id, url in targets:
            status, _ = download_thumbnail(
                video_id, url, target_dir=out_dir, client=client, force=force
            )
            counts[status] += 1

    counts["requested"] = len(targets)
    return counts
