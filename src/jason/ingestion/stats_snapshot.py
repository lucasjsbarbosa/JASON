"""Daily stats snapshot job.

For every video already known in `videos`, hit `videos.list?part=statistics`
in batches of 50 IDs (1 quota unit per batch) and append a fresh row to
`video_stats_snapshots`. This is the **age-bias correction** in action: by
sampling repeatedly over time we can interpolate `views_at_28d` for any video,
regardless of when it was published.

Idempotent within a single calendar second: repeated calls within ~1s would
collide on the (video_id, captured_at) PK and be silently dropped.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import httpx

from jason.config import get_settings
from jason.ingestion.youtube_data import (
    VIDEOS_BATCH_SIZE,
    YT_VIDEOS_URL,
    _chunked,
)

logger = logging.getLogger(__name__)


def _fetch_stats_only(
    video_ids: list[str], api_key: str, client: httpx.Client
) -> Iterator[dict[str, Any]]:
    """Yield {id, viewCount, likeCount, commentCount} for each batch (50 IDs)."""
    for batch in _chunked(video_ids, VIDEOS_BATCH_SIZE):
        response = client.get(
            YT_VIDEOS_URL,
            params={
                "part": "statistics",
                "id": ",".join(batch),
                "key": api_key,
            },
            timeout=15.0,
        )
        response.raise_for_status()
        yield from response.json().get("items", [])


def _read_known_videos(
    con: duckdb.DuckDBPyConnection, channel_id: str | None
) -> list[tuple[str, datetime]]:
    """Return (video_id, published_at) for all (or one channel's) known videos."""
    if channel_id:
        rows = con.execute(
            "SELECT id, published_at FROM videos WHERE channel_id = ?",
            [channel_id],
        ).fetchall()
    else:
        rows = con.execute("SELECT id, published_at FROM videos").fetchall()
    return rows


def snapshot_all(
    *,
    db_path: Path | None = None,
    channel_id: str | None = None,
) -> dict[str, Any]:
    """Append a fresh stats snapshot for every (or one channel's) known video.

    Args:
        db_path: optional DuckDB override (defaults to settings.duckdb_path).
        channel_id: optional UC... filter — snapshot only this channel's videos.

    Returns:
        dict with `requested`, `snapshotted`, `missing` (videos the API didn't
        return — likely private/deleted), and `captured_at`.
    """
    settings = get_settings()
    api_key = settings.youtube_data_api_key
    if not api_key:
        raise RuntimeError(
            "YOUTUBE_DATA_API_KEY not set — populate it in .env (see .env.example)"
        )

    db = db_path or settings.duckdb_path
    captured_at = datetime.now(UTC).replace(microsecond=0)

    with duckdb.connect(str(db)) as con:
        known = _read_known_videos(con, channel_id)
        if not known:
            logger.warning("no videos in DB to snapshot (channel_filter=%s)", channel_id)
            return {
                "requested": 0,
                "snapshotted": 0,
                "missing": 0,
                "captured_at": captured_at,
            }

        published_lookup: dict[str, datetime] = {}
        for vid, pub in known:
            if isinstance(pub, str):
                pub = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=UTC)
            published_lookup[vid] = pub

        ids = list(published_lookup.keys())
        logger.info("snapshotting %d videos at %s", len(ids), captured_at.isoformat())

        seen_ids: set[str] = set()
        with httpx.Client() as client:
            for item in _fetch_stats_only(ids, api_key, client):
                vid = item["id"]
                stats = item.get("statistics", {})
                pub = published_lookup[vid]
                days_since_publish = max((captured_at - pub).days, 0)
                con.execute(
                    """
                    INSERT INTO video_stats_snapshots
                        (video_id, captured_at, days_since_publish, views, likes, comments)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (video_id, captured_at) DO NOTHING
                    """,
                    [
                        vid,
                        captured_at,
                        days_since_publish,
                        int(stats["viewCount"]) if "viewCount" in stats else None,
                        int(stats["likeCount"]) if "likeCount" in stats else None,
                        int(stats["commentCount"]) if "commentCount" in stats else None,
                    ],
                )
                seen_ids.add(vid)

        missing = set(ids) - seen_ids
        if missing:
            logger.warning(
                "%d videos not returned by API (likely private/deleted): %s",
                len(missing),
                sorted(missing)[:5],
            )

    return {
        "requested": len(ids),
        "snapshotted": len(seen_ids),
        "missing": len(missing),
        "captured_at": captured_at,
    }
