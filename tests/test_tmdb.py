"""Tests for jason.ingestion.tmdb — fully mocked with respx."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest
import respx
from httpx import Response

from jason.config import get_settings
from jason.ingestion.tmdb import (
    TMDB_DISCOVER_MOVIE_URL,
    fetch_releases,
    ingest_tmdb_releases,
)


def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, api_key: str = "tmdb-fake") -> Path:
    db = tmp_path / "warehouse.duckdb"
    monkeypatch.setenv("TMDB_API_KEY", api_key)
    monkeypatch.setenv("DUCKDB_PATH", str(db))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    db.parent.mkdir(parents=True, exist_ok=True)
    schema_001 = Path("migrations/001_init.sql").read_text(encoding="utf-8")
    schema_003 = Path("migrations/003_horror_releases.sql").read_text(encoding="utf-8")
    with duckdb.connect(str(db)) as con:
        con.execute(schema_001)
        con.execute(schema_003)
    return db


def _result(tmdb_id: int, title: str, release_date: str) -> dict:
    return {
        "id": tmdb_id,
        "title": title,
        "release_date": release_date,
    }


def _page(results: list[dict], *, page: int, total_pages: int) -> dict:
    return {"page": page, "results": results, "total_pages": total_pages}


# ---------------------------------------------------------------------------
# fetch_releases — pagination
# ---------------------------------------------------------------------------


@respx.mock
def test_fetch_releases_paginates() -> None:
    respx.get(TMDB_DISCOVER_MOVIE_URL).mock(
        side_effect=[
            Response(200, json=_page(
                [_result(1, "Movie A", "2026-01-15"), _result(2, "Movie B", "2026-02-01")],
                page=1, total_pages=2,
            )),
            Response(200, json=_page(
                [_result(3, "Movie C", "2026-03-10")], page=2, total_pages=2,
            )),
        ]
    )

    results = list(fetch_releases(
        gte=date(2026, 1, 1), lte=date(2026, 6, 30), api_key="k",
    ))
    assert [r["id"] for r in results] == [1, 2, 3]


@respx.mock
def test_fetch_releases_stops_at_last_page() -> None:
    """Single page — only one HTTP call."""
    route = respx.get(TMDB_DISCOVER_MOVIE_URL).mock(
        return_value=Response(200, json=_page(
            [_result(1, "Solo", "2026-04-01")], page=1, total_pages=1,
        ))
    )
    results = list(fetch_releases(
        gte=date(2026, 1, 1), lte=date(2026, 12, 31), api_key="k",
    ))
    assert len(results) == 1
    assert route.call_count == 1


# ---------------------------------------------------------------------------
# ingest_tmdb_releases — DB persistence
# ---------------------------------------------------------------------------


@respx.mock
def test_ingest_tmdb_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _setup(monkeypatch, tmp_path)
    respx.get(TMDB_DISCOVER_MOVIE_URL).mock(
        return_value=Response(200, json=_page(
            [
                _result(101, "Hereditário 2", "2026-10-31"),
                _result(102, "Sobrenatural: O Início", "2026-11-15"),
            ],
            page=1, total_pages=1,
        ))
    )

    result = ingest_tmdb_releases()
    assert result == {"requested": 2, "inserted": 2, "updated": 0, "skipped": 0}

    with duckdb.connect(str(db)) as con:
        rows = con.execute(
            "SELECT tmdb_id, title, release_date, release_type, country "
            "FROM horror_releases ORDER BY tmdb_id"
        ).fetchall()
    assert rows == [
        (101, "Hereditário 2", date(2026, 10, 31), "3|4", "BR"),
        (102, "Sobrenatural: O Início", date(2026, 11, 15), "3|4", "BR"),
    ]


@respx.mock
def test_ingest_tmdb_upsert_updates_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A second run with a renamed/rescheduled title should update, not duplicate."""
    db = _setup(monkeypatch, tmp_path)
    respx.get(TMDB_DISCOVER_MOVIE_URL).mock(
        side_effect=[
            Response(200, json=_page(
                [_result(201, "Title A", "2026-09-01")], page=1, total_pages=1,
            )),
            Response(200, json=_page(
                [_result(201, "Title A (Renamed)", "2026-09-15")], page=1, total_pages=1,
            )),
        ]
    )

    r1 = ingest_tmdb_releases()
    r2 = ingest_tmdb_releases()
    assert r1 == {"requested": 1, "inserted": 1, "updated": 0, "skipped": 0}
    assert r2 == {"requested": 1, "inserted": 0, "updated": 1, "skipped": 0}

    with duckdb.connect(str(db)) as con:
        rows = con.execute("SELECT title, release_date FROM horror_releases").fetchall()
    assert rows == [("Title A (Renamed)", date(2026, 9, 15))]


@respx.mock
def test_ingest_tmdb_skips_missing_release_date(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _setup(monkeypatch, tmp_path)
    respx.get(TMDB_DISCOVER_MOVIE_URL).mock(
        return_value=Response(200, json=_page(
            [
                _result(301, "Has Date", "2026-08-01"),
                {"id": 302, "title": "No Date"},  # release_date missing
                {"id": 303, "title": "Empty Date", "release_date": ""},
            ],
            page=1, total_pages=1,
        ))
    )

    result = ingest_tmdb_releases()
    assert result["requested"] == 3
    assert result["inserted"] == 1
    assert result["skipped"] == 2

    with duckdb.connect(str(db)) as con:
        ids = [r[0] for r in con.execute("SELECT tmdb_id FROM horror_releases").fetchall()]
    assert ids == [301]


def test_missing_api_key_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(monkeypatch, tmp_path, api_key="")
    with pytest.raises(RuntimeError, match="TMDB_API_KEY"):
        ingest_tmdb_releases()


@respx.mock
def test_ingest_tmdb_passes_window_to_query(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the query string carries the right date filters."""
    _setup(monkeypatch, tmp_path)
    route = respx.get(TMDB_DISCOVER_MOVIE_URL).mock(
        return_value=Response(200, json=_page([], page=1, total_pages=1))
    )

    ingest_tmdb_releases(window_past=30, window_future=10, region="US")

    assert route.call_count == 1
    call = route.calls.last
    assert call.request.url.params["region"] == "US"
    assert call.request.url.params["with_genres"] == "27"
    assert call.request.url.params["with_release_type"] == "3|4"
    # gte should be ~30 days ago, lte ~10 days ahead — exact value depends on
    # today's date; we just verify they parse to valid ISO dates.
    gte = date.fromisoformat(call.request.url.params["primary_release_date.gte"])
    lte = date.fromisoformat(call.request.url.params["primary_release_date.lte"])
    assert (lte - gte).days == 40
