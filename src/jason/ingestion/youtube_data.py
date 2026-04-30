"""YouTube Data API v3 client for channel + video ingestion.

Walks a channel's "uploads" playlist via `playlistItems.list` (1 quota unit per
50-video page), then fetches snippet+statistics+contentDetails for each batch
via `videos.list` (1 unit per 50 IDs). For ~200 videos this costs ~8 units —
well under the 10k/day default quota.

Metrics (views/likes/comments) are written to `video_stats_snapshots`, NOT to
`videos`. This is the heart of the v1.1 age-bias correction: a 2-year-old video
isn't an outlier just because it accumulated more views.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import httpx

from jason.config import get_settings

logger = logging.getLogger(__name__)

YT_API_BASE = "https://www.googleapis.com/youtube/v3"
YT_CHANNELS_URL = f"{YT_API_BASE}/channels"
YT_PLAYLIST_ITEMS_URL = f"{YT_API_BASE}/playlistItems"
YT_VIDEOS_URL = f"{YT_API_BASE}/videos"

VIDEOS_BATCH_SIZE = 50  # max permitted by videos.list

# YouTube raised the Shorts duration cap from 60s to 180s in 2024. Channels
# that publish vertical content rarely add `#shorts` to title/description, so
# duration is the only reliable post-hoc signal. False positives (e.g. a 90s
# trailer that's actually long-form) are rare and downstream models filter
# Shorts out anyway — better to over-flag than miss the bulk of vertical content.
SHORTS_DURATION_CAP_S = 180

_ISO_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)
_SHORTS_TAG_RE = re.compile(r"#shorts\b", re.IGNORECASE)


def parse_iso_duration(iso: str) -> int:
    """Parse a YouTube ISO-8601 duration ('PT4M13S', 'PT1H2M', 'PT0S') to seconds.

    YouTube only emits days for very long live streams; we still handle them.
    Returns 0 for unrecognized strings rather than raising — a missing duration
    shouldn't break a whole channel ingest.
    """
    if not iso:
        return 0
    m = _ISO_DURATION_RE.match(iso)
    if not m:
        logger.warning("unparseable ISO duration: %r", iso)
        return 0
    parts = {k: int(v) if v else 0 for k, v in m.groupdict().items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def is_short_video(duration_s: int, title: str, description: str) -> bool:
    """Detect Shorts: <=SHORTS_DURATION_CAP_S OR #shorts tag in title/description."""
    if duration_s and duration_s <= SHORTS_DURATION_CAP_S:
        return True
    return bool(_SHORTS_TAG_RE.search(title or "") or _SHORTS_TAG_RE.search(description or ""))


def _pick_thumbnail(thumbs: dict[str, Any]) -> str | None:
    for size in ("maxres", "standard", "high", "medium", "default"):
        if size in thumbs and "url" in thumbs[size]:
            return thumbs[size]["url"]
    return None


def _fetch_channel_metadata(
    channel_id: str, api_key: str, client: httpx.Client
) -> dict[str, Any]:
    """Single channels.list call: snippet, statistics, contentDetails (1 unit)."""
    response = client.get(
        YT_CHANNELS_URL,
        params={
            "part": "snippet,statistics,contentDetails",
            "id": channel_id,
            "key": api_key,
        },
        timeout=10.0,
    )
    response.raise_for_status()
    items = response.json().get("items", [])
    if not items:
        raise ValueError(f"channel not found: {channel_id}")
    item = items[0]
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    uploads = item["contentDetails"]["relatedPlaylists"]["uploads"]
    subs_raw = stats.get("subscriberCount")
    return {
        "id": channel_id,
        "title": snippet.get("title"),
        "handle": (snippet.get("customUrl") or "").lstrip("@") or None,
        "subs": int(subs_raw) if subs_raw is not None else None,
        "uploads_playlist_id": uploads,
    }


def _iter_video_ids(
    uploads_playlist_id: str, api_key: str, client: httpx.Client
) -> Iterator[str]:
    """Yield video IDs by paginating playlistItems (1 unit per page of 50)."""
    page_token: str | None = None
    while True:
        params: dict[str, str] = {
            "part": "contentDetails",
            "playlistId": uploads_playlist_id,
            "maxResults": "50",
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token
        response = client.get(YT_PLAYLIST_ITEMS_URL, params=params, timeout=10.0)
        response.raise_for_status()
        data = response.json()
        for item in data.get("items", []):
            vid = item.get("contentDetails", {}).get("videoId")
            if vid:
                yield vid
        page_token = data.get("nextPageToken")
        if not page_token:
            return


def _chunked(seq: list[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _fetch_video_details(
    video_ids: list[str], api_key: str, client: httpx.Client
) -> Iterator[dict[str, Any]]:
    """Yield raw video records, batched 50 IDs per call (1 unit per call)."""
    for batch in _chunked(video_ids, VIDEOS_BATCH_SIZE):
        response = client.get(
            YT_VIDEOS_URL,
            params={
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(batch),
                "key": api_key,
            },
            timeout=15.0,
        )
        response.raise_for_status()
        yield from response.json().get("items", [])


def _normalize_video(raw: dict[str, Any]) -> dict[str, Any]:
    """Flatten a videos.list item into the columns we store."""
    snippet = raw.get("snippet", {})
    content = raw.get("contentDetails", {})
    stats = raw.get("statistics", {})
    title = snippet.get("title", "")
    description = snippet.get("description", "")
    duration_s = parse_iso_duration(content.get("duration", ""))
    return {
        "id": raw["id"],
        "title": title,
        "description": description,
        "published_at": snippet.get("publishedAt"),
        "duration_s": duration_s,
        "is_short": is_short_video(duration_s, title, description),
        "thumbnail_url": _pick_thumbnail(snippet.get("thumbnails", {})),
        "views": int(stats["viewCount"]) if "viewCount" in stats else None,
        "likes": int(stats["likeCount"]) if "likeCount" in stats else None,
        "comments": int(stats["commentCount"]) if "commentCount" in stats else None,
    }


def _upsert_channel(con: duckdb.DuckDBPyConnection, ch: dict[str, Any]) -> None:
    con.execute(
        """
        INSERT INTO channels (id, handle, title, subs)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            handle = EXCLUDED.handle,
            title  = EXCLUDED.title,
            subs   = EXCLUDED.subs
        """,
        [ch["id"], ch["handle"], ch["title"], ch["subs"]],
    )


def _upsert_video(con: duckdb.DuckDBPyConnection, channel_id: str, v: dict[str, Any]) -> None:
    con.execute(
        """
        INSERT INTO videos (
            id, channel_id, title, description, published_at,
            duration_s, is_short, thumbnail_url
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            title         = EXCLUDED.title,
            description   = EXCLUDED.description,
            duration_s    = EXCLUDED.duration_s,
            is_short      = EXCLUDED.is_short,
            thumbnail_url = EXCLUDED.thumbnail_url
        """,
        [
            v["id"],
            channel_id,
            v["title"],
            v["description"],
            v["published_at"],
            v["duration_s"],
            v["is_short"],
            v["thumbnail_url"],
        ],
    )


def _insert_snapshot(
    con: duckdb.DuckDBPyConnection,
    video_id: str,
    captured_at: datetime,
    published_at: str,
    views: int | None,
    likes: int | None,
    comments: int | None,
) -> None:
    """Insert one row in video_stats_snapshots. PK is (video_id, captured_at)."""
    pub_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    days_since_publish = max((captured_at - pub_dt).days, 0)
    con.execute(
        """
        INSERT INTO video_stats_snapshots
            (video_id, captured_at, days_since_publish, views, likes, comments)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (video_id, captured_at) DO NOTHING
        """,
        [video_id, captured_at, days_since_publish, views, likes, comments],
    )


def _dump_raw(raw_dir: Path, channel_id: str, captured_at: datetime, items: list[dict[str, Any]]) -> Path:
    """Persist raw videos.list responses as JSONL before they touch the DB."""
    target_dir = raw_dir / channel_id
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = captured_at.strftime("%Y%m%dT%H%M%SZ")
    path = target_dir / f"{stamp}_videos.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    return path


def ingest_channel(
    channel_id: str,
    *,
    db_path: Path | None = None,
    raw_dir: Path | None = None,
) -> dict[str, Any]:
    """Pull a channel's metadata and full video catalog, write to DuckDB.

    Side effects:
        * Upserts a `channels` row (title/handle/subs refresh on each run).
        * Upserts one `videos` row per public video (no metrics).
        * Inserts one `video_stats_snapshots` row per video with `captured_at=now`.
        * Dumps the raw videos.list JSON to `data/raw/{channel_id}/<ts>_videos.jsonl`
          before the DB write, so reruns can be reconstructed if the schema evolves.

    Args:
        channel_id: UC... id (use handle_resolver to convert @handles first).
        db_path: optional override (defaults to settings.duckdb_path).
        raw_dir: optional override (defaults to settings.data_dir / 'raw').

    Returns:
        dict with `channel_id`, `video_count`, `snapshot_count`, `raw_dump_path`.
    """
    settings = get_settings()
    api_key = settings.youtube_data_api_key
    if not api_key:
        raise RuntimeError(
            "YOUTUBE_DATA_API_KEY not set — populate it in .env (see .env.example)"
        )

    db = db_path or settings.duckdb_path
    raw_root = raw_dir or (settings.data_dir / "raw")
    db.parent.mkdir(parents=True, exist_ok=True)
    captured_at = datetime.now(UTC).replace(microsecond=0)

    with httpx.Client() as client:
        channel = _fetch_channel_metadata(channel_id, api_key, client)
        logger.info("channel %s -> %s (%s subs)", channel_id, channel["title"], channel["subs"])

        video_ids = list(_iter_video_ids(channel["uploads_playlist_id"], api_key, client))
        logger.info("found %d videos in uploads playlist", len(video_ids))

        raw_items = list(_fetch_video_details(video_ids, api_key, client))

    raw_dump_path = _dump_raw(raw_root, channel_id, captured_at, raw_items)

    snapshot_count = 0
    with duckdb.connect(str(db)) as con:
        _upsert_channel(con, channel)
        for raw in raw_items:
            v = _normalize_video(raw)
            _upsert_video(con, channel_id, v)
            _insert_snapshot(
                con,
                video_id=v["id"],
                captured_at=captured_at,
                published_at=v["published_at"],
                views=v["views"],
                likes=v["likes"],
                comments=v["comments"],
            )
            snapshot_count += 1

    logger.info(
        "ingest done: channel=%s videos=%d snapshots=%d raw=%s",
        channel_id, len(raw_items), snapshot_count, raw_dump_path,
    )
    return {
        "channel_id": channel_id,
        "video_count": len(raw_items),
        "snapshot_count": snapshot_count,
        "raw_dump_path": raw_dump_path,
    }
