"""Tests for jason.features.title_features."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from jason.config import get_settings
from jason.features.title_features import (
    compute_title_features,
    extract_features,
)

CHANNEL_A = "UCfeatA00000000000000000"
CHANNEL_B = "UCfeatB00000000000000000"


def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db = tmp_path / "warehouse.duckdb"
    monkeypatch.setenv("DUCKDB_PATH", str(db))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    db.parent.mkdir(parents=True, exist_ok=True)
    schema_001 = Path("migrations/001_init.sql").read_text(encoding="utf-8")
    schema_004 = Path("migrations/004_video_features.sql").read_text(encoding="utf-8")
    with duckdb.connect(str(db)) as con:
        con.execute(schema_001)
        con.execute(schema_004)
    return db


def _seed(db: Path, rows: list[tuple[str, str, str]]) -> None:
    """rows: (channel_id, video_id, title)."""
    with duckdb.connect(str(db)) as con:
        for ch in {r[0] for r in rows}:
            con.execute("INSERT INTO channels (id, title) VALUES (?, ?)", [ch, "C"])
        for ch, vid, title in rows:
            con.execute(
                "INSERT INTO videos (id, channel_id, title, published_at) VALUES (?, ?, ?, ?)",
                [vid, ch, title, "2026-04-01T00:00:00Z"],
            )


# ---------------------------------------------------------------------------
# Pure feature extraction
# ---------------------------------------------------------------------------


def test_extract_features_simple() -> None:
    f = extract_features("Hereditario foi explicado")
    assert f["char_len"] == len("Hereditario foi explicado")
    assert f["word_count"] == 3
    assert f["has_number"] is False
    assert f["has_emoji"] is False
    assert f["has_question_mark"] is False
    assert f["has_caps_word"] is False
    assert f["has_first_person"] is False
    assert f["has_explained_keyword"] is True
    assert f["has_ranking_keyword"] is False


def test_extract_features_caps_and_emoji() -> None:
    f = extract_features("As 12 Máscaras de JASON Voorhees | Sexta-feira 13 👹")
    assert f["has_number"] is True
    assert f["has_emoji"] is True
    assert f["has_caps_word"] is True       # "JASON"
    assert f["caps_ratio"] > 0.0


def test_extract_features_ranking_and_extreme() -> None:
    f = extract_features("Top 10 piores filmes mais perturbadores de 2026")
    assert f["has_ranking_keyword"] is True
    assert f["has_number"] is True
    assert f["has_extreme_adjective"] is True


def test_extract_features_curiosity_and_first_person() -> None:
    f = extract_features("Por que ninguém fala desse filme que EU achei chocante?")
    assert f["has_curiosity_keyword"] is True
    assert f["has_first_person"] is True
    assert f["has_question_mark"] is True
    assert f["has_extreme_adjective"] is True   # chocante
    assert f["has_caps_word"] is False           # "EU" is 2 chars — below the 3+ threshold


def test_extract_features_caps_word_threshold() -> None:
    """has_caps_word requires 3+ consecutive uppercase letters."""
    assert extract_features("EU sou novo aqui").get("has_caps_word") is False
    assert extract_features("FBI investiga").get("has_caps_word") is True
    assert extract_features("PERTURBADORA cena").get("has_caps_word") is True


def test_extract_features_accent_normalization() -> None:
    """Niche regexes match across accents and capitalization."""
    assert extract_features("Final EXPLICADO").get("has_explained_keyword") is True
    assert extract_features("EXPLICAÇÃO completa").get("has_explained_keyword") is True
    assert extract_features("explicada").get("has_explained_keyword") is True


def test_extract_features_empty_string() -> None:
    f = extract_features("")
    assert f["char_len"] == 0
    assert f["word_count"] == 0
    assert f["caps_ratio"] == 0.0
    assert f["has_number"] is False


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------


def test_compute_title_features_writes_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _setup(monkeypatch, tmp_path)
    _seed(
        db,
        [
            (CHANNEL_A, "vid_feat0001", "Final EXPLICADO de Hereditário"),
            (CHANNEL_A, "vid_feat0002", "Top 10 filmes perturbadores"),
        ],
    )

    result = compute_title_features()
    assert result == {"requested": 2, "computed": 2}

    with duckdb.connect(str(db)) as con:
        rows = con.execute(
            "SELECT video_id, has_explained_keyword, has_ranking_keyword, has_extreme_adjective "
            "FROM video_features ORDER BY video_id"
        ).fetchall()
    assert rows == [
        ("vid_feat0001", True, False, False),
        ("vid_feat0002", False, True, True),
    ]


def test_compute_title_features_skips_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _setup(monkeypatch, tmp_path)
    _seed(db, [(CHANNEL_A, "vid_skip0001", "Tudo EXPLICADO")])

    r1 = compute_title_features()
    r2 = compute_title_features()
    assert r1["computed"] == 1
    assert r2["computed"] == 0  # nothing pending second time

    with duckdb.connect(str(db)) as con:
        count = con.execute("SELECT COUNT(*) FROM video_features").fetchone()[0]
    assert count == 1


def test_compute_title_features_force_recomputes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _setup(monkeypatch, tmp_path)
    _seed(db, [(CHANNEL_A, "vid_force0001", "Top 10")])

    compute_title_features()
    r2 = compute_title_features(force=True)
    assert r2["computed"] == 1


def test_compute_title_features_channel_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _setup(monkeypatch, tmp_path)
    _seed(
        db,
        [
            (CHANNEL_A, "vid_chA00001", "EXPLICADO chA"),
            (CHANNEL_B, "vid_chB00001", "EXPLICADO chB"),
        ],
    )
    result = compute_title_features(channel_id=CHANNEL_A)
    assert result == {"requested": 1, "computed": 1}

    with duckdb.connect(str(db)) as con:
        ids = [r[0] for r in con.execute("SELECT video_id FROM video_features").fetchall()]
    assert ids == ["vid_chA00001"]
