"""TMDb release calendar ingest — feeds `days_to_nearest_horror_release`.

Uses `/discover/movie` v3 with `with_genres=27` (Horror) and
`with_release_type=3|4` (theatrical OR digital). The default region is `BR`
since the canal is PT-BR; the relevant signal is when a horror movie hits
Brazilian audiences (theaters or streaming) — that's when search and
recommendation traffic for adjacent reviews spikes.

Pages 20 results at a time. With a 18-month window, expect ~5-15 pages.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import httpx

from jason.config import get_settings

logger = logging.getLogger(__name__)

TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_DISCOVER_MOVIE_URL = f"{TMDB_API_BASE}/discover/movie"
HORROR_GENRE_ID = 27
DEFAULT_RELEASE_TYPE_FILTER = "3|4"  # theatrical OR digital
DEFAULT_REGION = "BR"


def _discover_page(
    client: httpx.Client,
    api_key: str,
    *,
    gte: date,
    lte: date,
    page: int,
    region: str,
    release_type: str,
) -> dict[str, Any]:
    params = {
        "api_key": api_key,
        "language": "pt-BR",
        "with_genres": str(HORROR_GENRE_ID),
        "with_release_type": release_type,
        "primary_release_date.gte": gte.isoformat(),
        "primary_release_date.lte": lte.isoformat(),
        "region": region,
        "page": str(page),
        "sort_by": "primary_release_date.asc",
    }
    response = client.get(TMDB_DISCOVER_MOVIE_URL, params=params, timeout=15.0)
    response.raise_for_status()
    return response.json()


def fetch_releases(
    *,
    gte: date,
    lte: date,
    api_key: str,
    region: str = DEFAULT_REGION,
    release_type: str = DEFAULT_RELEASE_TYPE_FILTER,
) -> Iterator[dict[str, Any]]:
    """Yield each horror release in [gte, lte] for `region`. Paginates internally."""
    with httpx.Client() as client:
        page = 1
        while True:
            data = _discover_page(
                client, api_key, gte=gte, lte=lte, page=page,
                region=region, release_type=release_type,
            )
            yield from data.get("results", [])
            total_pages = data.get("total_pages", 1)
            if page >= total_pages:
                return
            page += 1


def _normalize(item: dict[str, Any], *, release_type: str, country: str) -> dict[str, Any] | None:
    rdate = item.get("release_date")
    if not rdate:
        return None
    return {
        "tmdb_id": int(item["id"]),
        "title": item.get("title") or item.get("original_title") or "",
        "release_date": datetime.strptime(rdate, "%Y-%m-%d").date(),
        "release_type": release_type,
        "country": country,
    }


def ingest_tmdb_releases(
    *,
    window_past: int = 365,
    window_future: int = 180,
    db_path: Path | None = None,
    region: str = DEFAULT_REGION,
    release_type: str = DEFAULT_RELEASE_TYPE_FILTER,
) -> dict[str, Any]:
    """Pull horror releases for the configured window and upsert into horror_releases.

    Args:
        window_past: days behind today to start (default 365).
        window_future: days ahead of today to end (default 180).
        db_path: optional DuckDB override.
        region: 2-char ISO region (default 'BR').
        release_type: TMDb release type filter (default '3|4' = theatrical OR digital).

    Returns:
        dict with `requested`, `inserted`, `updated`, `skipped` (rows without release_date).
    """
    settings = get_settings()
    api_key = settings.tmdb_api_key
    if not api_key:
        raise RuntimeError(
            "TMDB_API_KEY not set — get a free key at themoviedb.org/settings/api"
        )

    today = datetime.now(UTC).date()
    gte = today - timedelta(days=window_past)
    lte = today + timedelta(days=window_future)
    logger.info("fetching TMDb horror releases for %s [%s, %s]", region, gte, lte)

    db = db_path or settings.duckdb_path
    counts = {"requested": 0, "inserted": 0, "updated": 0, "skipped": 0}

    with duckdb.connect(str(db)) as con:
        for raw in fetch_releases(
            gte=gte, lte=lte, api_key=api_key,
            region=region, release_type=release_type,
        ):
            counts["requested"] += 1
            row = _normalize(raw, release_type=release_type, country=region)
            if row is None:
                counts["skipped"] += 1
                continue
            existed = con.execute(
                "SELECT 1 FROM horror_releases WHERE tmdb_id = ?",
                [row["tmdb_id"]],
            ).fetchone()
            con.execute(
                """
                INSERT INTO horror_releases
                    (tmdb_id, title, release_date, release_type, country)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (tmdb_id) DO UPDATE SET
                    title        = EXCLUDED.title,
                    release_date = EXCLUDED.release_date,
                    release_type = EXCLUDED.release_type,
                    country      = EXCLUDED.country
                """,
                [row["tmdb_id"], row["title"], row["release_date"], row["release_type"], row["country"]],
            )
            if existed:
                counts["updated"] += 1
            else:
                counts["inserted"] += 1

    logger.info("tmdb ingest done: %s", counts)
    return counts
