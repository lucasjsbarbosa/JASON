"""Resolve YouTube @handles to channel IDs (UC...) with DuckDB cache.

The YouTube Data API endpoint `channels.list?forHandle=` costs 1 quota unit per
call and does NOT support batching. We cache results in `handle_cache` so that
re-running ingestion against the same handles is free after the first pass.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import httpx

from jason.config import get_settings

logger = logging.getLogger(__name__)

YT_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"


def _normalize(handle: str) -> str:
    """Lowercase and strip leading '@' for use as a stable cache key."""
    return handle.strip().lstrip("@").lower()


def _ensure_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS handle_cache (
            handle      VARCHAR PRIMARY KEY,
            channel_id  VARCHAR,
            resolved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _fetch_one(handle_norm: str, api_key: str, client: httpx.Client) -> str | None:
    """Hit channels.list?forHandle= for a single handle. Returns UC... or None."""
    response = client.get(
        YT_CHANNELS_URL,
        params={"part": "id", "forHandle": f"@{handle_norm}", "key": api_key},
        timeout=10.0,
    )
    response.raise_for_status()
    data = response.json()
    items = data.get("items", [])
    if not items:
        return None
    return items[0]["id"]


def resolve_handles(
    handles: list[str],
    *,
    db_path: Path | None = None,
    force_refresh: bool = False,
) -> dict[str, str | None]:
    """Resolve a batch of @handles to channel IDs, using DuckDB cache.

    Args:
        handles: list of @handles or bare names (case-insensitive).
        db_path: optional override for DuckDB path (defaults to settings).
        force_refresh: ignore cache and re-query the API for every handle.

    Returns:
        dict mapping the original input string to its channel_id, or None when
        YouTube did not recognize the handle.
    """
    settings = get_settings()
    api_key = settings.youtube_data_api_key
    if not api_key:
        raise RuntimeError(
            "YOUTUBE_DATA_API_KEY not set — populate it in .env (see .env.example)"
        )

    db = db_path or settings.duckdb_path
    db.parent.mkdir(parents=True, exist_ok=True)

    results: dict[str, str | None] = {}

    with duckdb.connect(str(db)) as con, httpx.Client() as client:
        _ensure_table(con)

        for original in handles:
            norm = _normalize(original)
            if not norm:
                continue

            if not force_refresh:
                cached = con.execute(
                    "SELECT channel_id FROM handle_cache WHERE handle = ?",
                    [norm],
                ).fetchone()
                if cached is not None:
                    results[original] = cached[0]
                    logger.debug("cache hit: @%s -> %s", norm, cached[0])
                    continue

            try:
                channel_id = _fetch_one(norm, api_key, client)
            except httpx.HTTPError as exc:
                logger.warning("resolve failed for @%s: %s", norm, exc)
                results[original] = None
                continue

            con.execute(
                """
                INSERT INTO handle_cache (handle, channel_id, resolved_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT (handle) DO UPDATE SET
                    channel_id = EXCLUDED.channel_id,
                    resolved_at = EXCLUDED.resolved_at
                """,
                [norm, channel_id],
            )
            results[original] = channel_id

    return results
