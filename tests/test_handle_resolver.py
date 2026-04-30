"""Tests for jason.ingestion.handle_resolver."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
import respx
from httpx import Response

from jason.config import get_settings
from jason.ingestion.handle_resolver import (
    YT_CHANNELS_URL,
    _normalize,
    resolve_handles,
)


def _reset_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, api_key: str = "fake-key") -> Path:
    """Point settings at a fresh tmp DuckDB and clear the lru_cache."""
    db = tmp_path / "warehouse.duckdb"
    monkeypatch.setenv("YOUTUBE_DATA_API_KEY", api_key)
    monkeypatch.setenv("DUCKDB_PATH", str(db))
    get_settings.cache_clear()
    return db


def test_normalize() -> None:
    assert _normalize("@HoradoTerror") == "horadoterror"
    assert _normalize("HoradoTerror") == "horadoterror"
    assert _normalize("  @CarBosa  ") == "carbosa"
    assert _normalize("") == ""


@respx.mock
def test_resolve_one_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_settings(monkeypatch, tmp_path)
    respx.get(YT_CHANNELS_URL).mock(
        return_value=Response(200, json={"items": [{"id": "UCabc12345678901234567890"}]})
    )

    result = resolve_handles(["@HoradoTerror"])
    assert result == {"@HoradoTerror": "UCabc12345678901234567890"}


@respx.mock
def test_cache_hit_skips_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _reset_settings(monkeypatch, tmp_path)

    db.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db)) as con:
        con.execute(
            "CREATE TABLE handle_cache (handle VARCHAR PRIMARY KEY, channel_id VARCHAR, "
            "resolved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        con.execute(
            "INSERT INTO handle_cache (handle, channel_id) VALUES (?, ?)",
            ["horadoterror", "UCcached1234567890123456"],
        )

    route = respx.get(YT_CHANNELS_URL)

    result = resolve_handles(["@HoradoTerror"])
    assert result == {"@HoradoTerror": "UCcached1234567890123456"}
    assert route.call_count == 0


@respx.mock
def test_force_refresh_bypasses_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _reset_settings(monkeypatch, tmp_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db)) as con:
        con.execute(
            "CREATE TABLE handle_cache (handle VARCHAR PRIMARY KEY, channel_id VARCHAR, "
            "resolved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        con.execute(
            "INSERT INTO handle_cache (handle, channel_id) VALUES (?, ?)",
            ["horadoterror", "UCold00000000000000000000"],
        )

    respx.get(YT_CHANNELS_URL).mock(
        return_value=Response(200, json={"items": [{"id": "UCnew00000000000000000000"}]})
    )

    result = resolve_handles(["@HoradoTerror"], force_refresh=True)
    assert result == {"@HoradoTerror": "UCnew00000000000000000000"}


@respx.mock
def test_handle_not_found_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_settings(monkeypatch, tmp_path)
    respx.get(YT_CHANNELS_URL).mock(return_value=Response(200, json={"items": []}))

    result = resolve_handles(["@FakeChannelDoesNotExist"])
    assert result == {"@FakeChannelDoesNotExist": None}


def test_missing_api_key_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_settings(monkeypatch, tmp_path, api_key="")

    with pytest.raises(RuntimeError, match="YOUTUBE_DATA_API_KEY"):
        resolve_handles(["@whatever"])


@respx.mock
def test_batch_mixed_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """First handle hits API, second is not found, third comes from cache."""
    db = _reset_settings(monkeypatch, tmp_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db)) as con:
        con.execute(
            "CREATE TABLE handle_cache (handle VARCHAR PRIMARY KEY, channel_id VARCHAR, "
            "resolved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        con.execute(
            "INSERT INTO handle_cache (handle, channel_id) VALUES (?, ?)",
            ["carbosa", "UCcarbosa00000000000000"],
        )

    respx.get(YT_CHANNELS_URL).mock(
        side_effect=[
            Response(200, json={"items": [{"id": "UChora00000000000000000000"}]}),
            Response(200, json={"items": []}),
        ]
    )

    result = resolve_handles(["@HoradoTerror", "@DoesNotExist", "@Carbosa"])
    assert result == {
        "@HoradoTerror": "UChora00000000000000000000",
        "@DoesNotExist": None,
        "@Carbosa": "UCcarbosa00000000000000",
    }
