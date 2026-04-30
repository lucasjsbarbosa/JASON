"""Tests for jason.ingestion.youtube_analytics — service is mocked."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import duckdb
import pytest

from jason.config import get_settings
from jason.ingestion.youtube_analytics import _persist, pull_metrics


def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db = tmp_path / "warehouse.duckdb"
    monkeypatch.setenv("DUCKDB_PATH", str(db))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID", "fake-id")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET", "fake-secret")
    get_settings.cache_clear()
    db.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db)) as con:
        con.execute(Path("migrations/008_yt_analytics.sql").read_text(encoding="utf-8"))
    return db


def _mock_service(rows: list[list]) -> SimpleNamespace:
    """Build a mock googleapiclient service with a `.reports().query().execute()` chain."""
    response = {
        "columnHeaders": [
            {"name": "day"},
            {"name": "video"},
            {"name": "views"},
            {"name": "estimatedMinutesWatched"},
            {"name": "impressions"},
            {"name": "impressionClickThroughRate"},
            {"name": "averageViewDuration"},
            {"name": "averageViewPercentage"},
        ],
        "rows": rows,
    }
    query = MagicMock()
    query.execute.return_value = response
    reports = MagicMock()
    reports.query.return_value = query
    service = MagicMock()
    service.reports.return_value = reports
    return service


# ---------------------------------------------------------------------------


def test_persist_maps_columns_to_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _setup(monkeypatch, tmp_path)
    headers = [
        {"name": "day"}, {"name": "video"}, {"name": "views"},
        {"name": "impressions"}, {"name": "impressionClickThroughRate"},
        {"name": "averageViewDuration"}, {"name": "averageViewPercentage"},
    ]
    rows = [
        ["2026-04-15", "vid_aaa01", 1234, 50000, 4.2, 320.5, 65.7],
        ["2026-04-16", "vid_aaa01", 1500, 60000, 4.5, 330.1, 67.0],
    ]
    with duckdb.connect(str(db)) as con:
        n = _persist(con, headers, rows)
    assert n == 2

    with duckdb.connect(str(db)) as con:
        out = con.execute(
            "SELECT video_id, date, views, impressions, impression_ctr, "
            "avg_view_duration_seconds, avg_view_percentage "
            "FROM youtube_analytics_metrics ORDER BY date"
        ).fetchall()
    assert len(out) == 2
    assert out[0][0] == "vid_aaa01"
    assert out[0][2] == 1234
    assert abs(out[0][4] - 4.2) < 1e-6
    assert abs(out[0][5] - 320.5) < 1e-6


def test_pull_metrics_with_mock_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _setup(monkeypatch, tmp_path)
    rows = [
        ["2026-04-29", "vid_b00001", 100, 4000, 5000, 3.5, 250.0, 50.0],
        ["2026-04-29", "vid_b00002", 250, 12000, 8000, 4.1, 320.0, 60.0],
        ["2026-04-30", "vid_b00001", 120, 4500, 5500, 3.7, 260.0, 52.0],
    ]
    service = _mock_service(rows)

    result = pull_metrics(
        start_date=date(2026, 4, 29), end_date=date(2026, 4, 30),
        db_path=db, service=service,
    )
    assert result["rows"] == 3
    assert result["start_date"] == "2026-04-29"
    assert result["end_date"] == "2026-04-30"

    with duckdb.connect(str(db)) as con:
        n_rows = con.execute("SELECT COUNT(*) FROM youtube_analytics_metrics").fetchone()[0]
        n_videos = con.execute(
            "SELECT COUNT(DISTINCT video_id) FROM youtube_analytics_metrics"
        ).fetchone()[0]
    assert n_rows == 3
    assert n_videos == 2


def test_pull_metrics_upserts_on_repeat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same (video_id, date) on a second pull should UPDATE not duplicate."""
    db = _setup(monkeypatch, tmp_path)
    first = _mock_service([["2026-04-29", "vid_x00001", 100, 4000, 5000, 3.0, 200.0, 40.0]])
    second = _mock_service([["2026-04-29", "vid_x00001", 200, 8000, 10000, 4.0, 250.0, 60.0]])

    pull_metrics(start_date=date(2026, 4, 29), end_date=date(2026, 4, 29),
                 db_path=db, service=first)
    pull_metrics(start_date=date(2026, 4, 29), end_date=date(2026, 4, 29),
                 db_path=db, service=second)

    with duckdb.connect(str(db)) as con:
        rows = con.execute(
            "SELECT views, impressions FROM youtube_analytics_metrics"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0] == (200, 10000)
