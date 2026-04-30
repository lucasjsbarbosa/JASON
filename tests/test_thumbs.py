"""Tests for jason.thumbs — text_overlay_advisor + frame_scorer (DI for cv2)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from jason.config import get_settings
from jason.thumbs.text_overlay_advisor import suggest_overlay


def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db = tmp_path / "warehouse.duckdb"
    monkeypatch.setenv("DUCKDB_PATH", str(db))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    db.parent.mkdir(parents=True, exist_ok=True)
    for sql_file in (
        "001_init.sql", "004_video_features.sql", "005_embeddings.sql",
        "006_topics.sql",
    ):
        with duckdb.connect(str(db)) as con:
            con.execute(Path(f"migrations/{sql_file}").read_text(encoding="utf-8"))
    return db


def _seed_outlier(db: Path, *, video_id: str, title: str, theme_id: int = -1,
                  multiplier: float = 4.0, percentile: float = 95.0) -> None:
    with duckdb.connect(str(db)) as con:
        con.execute("INSERT OR IGNORE INTO channels (id, title) VALUES (?, ?)", ["UCx", "C"])
        con.execute(
            "INSERT INTO videos (id, channel_id, title, published_at, is_short) "
            "VALUES (?, ?, ?, ?, ?)",
            [video_id, "UCx", title, "2026-04-01T00:00:00Z", False],
        )
        con.execute(
            "INSERT INTO video_features (video_id, theme_id) VALUES (?, ?)",
            [video_id, theme_id],
        )
        con.execute(
            "INSERT INTO outliers (video_id, multiplier, percentile_in_channel) VALUES (?, ?, ?)",
            [video_id, multiplier, percentile],
        )


def test_suggest_overlay_picks_keywords_from_outliers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _setup(monkeypatch, tmp_path)
    _seed_outlier(db, video_id="vid_o001", title="Hereditário FINAL EXPLICADO")
    _seed_outlier(db, video_id="vid_o002", title="TOP 10 PERTURBADORES de 2024")
    _seed_outlier(db, video_id="vid_o003", title="O Filme Mais INSANO Do Ano")

    overlay = suggest_overlay(db_path=db)
    assert overlay["text_present"] is True
    assert overlay["max_words"] == 3
    # At least one of the three relevant keywords should have been picked up
    examples_set = set(overlay["examples"])
    assert {"FINAL", "EXPLICADO", "PERTURBADOR", "INSANO", "TOP"} & examples_set


def test_suggest_overlay_falls_back_when_no_outliers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _setup(monkeypatch, tmp_path)
    overlay = suggest_overlay(db_path=db)
    # Default fallback list
    assert "EXPLICADO" in overlay["examples"]


def test_suggest_overlay_filters_by_theme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _setup(monkeypatch, tmp_path)
    _seed_outlier(db, video_id="vid_t001", title="TOP 10 PERTURBADORES", theme_id=1)
    _seed_outlier(db, video_id="vid_t002", title="FINAL EXPLICADO", theme_id=2)

    overlay_t1 = suggest_overlay(theme_id=1, db_path=db)
    overlay_t2 = suggest_overlay(theme_id=2, db_path=db)
    assert "TOP" in overlay_t1["examples"] or "PERTURBADOR" in overlay_t1["examples"]
    assert "EXPLICADO" in overlay_t2["examples"] or "FINAL" in overlay_t2["examples"]


# ---------------------------------------------------------------------------
# frame_scorer — outlier centroid logic (cv2 not exercised, frame paths fake)
# ---------------------------------------------------------------------------


def test_outlier_centroid_returns_none_when_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from jason.thumbs.frame_scorer import _outlier_centroid

    db = _setup(monkeypatch, tmp_path)
    assert _outlier_centroid(db_path=db) is None


def test_outlier_centroid_averages_thumbnails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from jason.thumbs.frame_scorer import _outlier_centroid

    db = _setup(monkeypatch, tmp_path)
    e1 = [1.0] + [0.0] * 511
    e2 = [0.0] + [1.0] + [0.0] * 510
    with duckdb.connect(str(db)) as con:
        con.execute("INSERT OR IGNORE INTO channels (id, title) VALUES (?, ?)", ["UCx", "C"])
        for vid, emb in [("vid_c001", e1), ("vid_c002", e2)]:
            con.execute(
                "INSERT INTO videos (id, channel_id, title, published_at, is_short) "
                "VALUES (?, ?, ?, ?, ?)",
                [vid, "UCx", "T", "2026-04-01T00:00:00Z", False],
            )
            con.execute(
                "INSERT INTO video_features (video_id, thumb_embedding) VALUES (?, ?)",
                [vid, emb],
            )
            con.execute(
                "INSERT INTO outliers (video_id, multiplier, percentile_in_channel) VALUES (?, ?, ?)",
                [vid, 4.0, 95.0],
            )

    centroid = _outlier_centroid(db_path=db)
    assert centroid is not None
    assert len(centroid) == 512
    # Mean of [1,0,...] and [0,1,0,...] is [.5,.5,0,...], normalized to [.707,.707,0,...]
    assert abs(centroid[0] - 0.707) < 0.01
    assert abs(centroid[1] - 0.707) < 0.01
