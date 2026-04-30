"""YouTube Analytics API v2 — OAuth flow + daily metrics pull (canal próprio).

CTR, AVD, and retention are *private* metrics: only the channel owner can
read them. So unlike `youtube_data` (anonymous API key, public data), this
module needs OAuth 2.0 with the user's consent — first run opens a browser
on `localhost`, persists the token to `YOUTUBE_OAUTH_TOKEN_PATH`, and
refreshes silently from then on.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from jason.config import get_settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/yt-analytics.readonly"]

ANALYTICS_METRICS = (
    "views,"
    "estimatedMinutesWatched,"
    "impressions,"
    "impressionClickThroughRate,"
    "averageViewDuration,"
    "averageViewPercentage"
)


def _build_client_config(client_id: str, client_secret: str) -> dict[str, Any]:
    """Build the InstalledAppFlow config from `.env` values (no JSON file)."""
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def authenticate(*, force_reauth: bool = False) -> Any:
    """Open the OAuth browser flow if needed; return cached/refreshed creds.

    Args:
        force_reauth: ignore any existing token and re-prompt the user.
    """
    from google.auth.transport.requests import Request  # noqa: PLC0415
    from google.oauth2.credentials import Credentials  # noqa: PLC0415
    from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: PLC0415

    settings = get_settings()
    if not settings.youtube_oauth_client_id or not settings.youtube_oauth_client_secret:
        raise RuntimeError(
            "YOUTUBE_OAUTH_CLIENT_ID / YOUTUBE_OAUTH_CLIENT_SECRET not set in .env. "
            "Create an OAuth client (Desktop app) at "
            "console.cloud.google.com/apis/credentials and paste both."
        )

    token_path = settings.youtube_oauth_token_path
    token_path.parent.mkdir(parents=True, exist_ok=True)

    creds = None
    if not force_reauth and token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token and not force_reauth:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
        logger.info("refreshed youtube analytics token")
        return creds

    config = _build_client_config(
        settings.youtube_oauth_client_id, settings.youtube_oauth_client_secret,
    )
    flow = InstalledAppFlow.from_client_config(config, SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    logger.info("authorized + cached new token at %s", token_path)
    return creds


def _build_service(creds: Any) -> Any:
    from googleapiclient.discovery import build  # noqa: PLC0415

    return build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)


def _query_report(
    service: Any,
    *,
    start_date: date,
    end_date: date,
    metrics: str = ANALYTICS_METRICS,
) -> dict[str, Any]:
    return service.reports().query(
        ids="channel==MINE",
        startDate=start_date.isoformat(),
        endDate=end_date.isoformat(),
        metrics=metrics,
        dimensions="day,video",
    ).execute()


def _persist(con: duckdb.DuckDBPyConnection, headers: list[dict], rows: list[list]) -> int:
    """Map the API response to youtube_analytics_metrics rows."""
    col_idx = {h["name"]: i for i, h in enumerate(headers)}
    inserted = 0
    for row in rows:
        d = row[col_idx["day"]]
        vid = row[col_idx["video"]]
        params = [
            vid,
            d,
            row[col_idx["views"]] if "views" in col_idx else None,
            row[col_idx["impressions"]] if "impressions" in col_idx else None,
            row[col_idx["impressionClickThroughRate"]] if "impressionClickThroughRate" in col_idx else None,
            row[col_idx["averageViewDuration"]] if "averageViewDuration" in col_idx else None,
            row[col_idx["averageViewPercentage"]] if "averageViewPercentage" in col_idx else None,
        ]
        con.execute(
            """
            INSERT INTO youtube_analytics_metrics
                (video_id, date, views, impressions, impression_ctr,
                 avg_view_duration_seconds, avg_view_percentage)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (video_id, date) DO UPDATE SET
                views                     = EXCLUDED.views,
                impressions               = EXCLUDED.impressions,
                impression_ctr            = EXCLUDED.impression_ctr,
                avg_view_duration_seconds = EXCLUDED.avg_view_duration_seconds,
                avg_view_percentage       = EXCLUDED.avg_view_percentage,
                fetched_at                = now()
            """,
            params,
        )
        inserted += 1
    return inserted


def pull_metrics(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    db_path: Path | None = None,
    creds: Any | None = None,
    service: Any | None = None,
) -> dict[str, Any]:
    """Fetch daily-by-video metrics for the configured window. Default: last 30 days.

    Args:
        creds: optional pre-authorized credentials object (DI for tests).
        service: optional pre-built googleapiclient service (DI for tests).
            If passed, `creds` is unused and the OAuth flow is skipped.
    """
    settings = get_settings()
    db = db_path or settings.duckdb_path

    today = datetime.now(UTC).date()
    end = end_date or today
    start = start_date or (today - timedelta(days=30))

    if service is None:
        creds = creds or authenticate()
        service = _build_service(creds)

    response = _query_report(service, start_date=start, end_date=end)

    headers = response.get("columnHeaders", [])
    rows = response.get("rows", [])

    with duckdb.connect(str(db)) as con:
        n = _persist(con, headers, rows)

    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "rows": n,
    }
