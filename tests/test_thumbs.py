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


def test_outlier_embeddings_returns_empty_when_no_outliers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jason.thumbs.frame_scorer import _outlier_embeddings

    db = _setup(monkeypatch, tmp_path)
    assert _outlier_embeddings(db_path=db) == []


def test_outlier_similarity_uses_mean_top_k(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mean(top-K) should beat pure-max in distinguishing 'matches several
    winners' from 'clones one winner'. With K=2:
      • frame near outlier A only → score ~ avg(0.99, 0.10) ≈ 0.55
      • frame near A AND B equally → score ~ avg(0.71, 0.71) ≈ 0.71

    Higher score for the latter — exactly what we want."""
    from jason.thumbs.frame_scorer import outlier_similarity_for_frame

    # 3 outlier embeddings: A=[1,0,0], B=[0,1,0], C=[0,0,1] (orthogonal, distinct
    # winning patterns).
    outliers = [
        [1.0, 0.0, 0.0] + [0.0] * 509,
        [0.0, 1.0, 0.0] + [0.0] * 509,
        [0.0, 0.0, 1.0] + [0.0] * 509,
    ]

    # Frame 1: clone of A only (sim with A=1, B=0, C=0)
    frame1_path = tmp_path / "f1.jpg"
    frame1_path.write_bytes(b"x")
    encode_clone_a = lambda paths: [[1.0, 0.0, 0.0] + [0.0] * 509]  # noqa: E731
    sim1 = outlier_similarity_for_frame(
        frame1_path, outlier_embeddings=outliers, top_k=2, encode_fn=encode_clone_a,
    )
    # mean(top-2 of [1.0, 0.0, 0.0]) = mean(1.0, 0.0) = 0.5
    assert abs(sim1 - 0.5) < 0.01

    # Frame 2: 45° between A and B (sim with both ~ 0.707)
    frame2_path = tmp_path / "f2.jpg"
    frame2_path.write_bytes(b"x")
    blend = (1 / (2**0.5))
    encode_blend_ab = lambda paths: [[blend, blend, 0.0] + [0.0] * 509]  # noqa: E731
    sim2 = outlier_similarity_for_frame(
        frame2_path, outlier_embeddings=outliers, top_k=2, encode_fn=encode_blend_ab,
    )
    # mean(top-2 of [0.707, 0.707, 0]) = 0.707
    assert sim2 > sim1
    assert abs(sim2 - 0.707) < 0.01


def test_outlier_similarity_returns_zero_when_no_outliers(tmp_path: Path) -> None:
    from jason.thumbs.frame_scorer import outlier_similarity_for_frame

    p = tmp_path / "f.jpg"
    p.write_bytes(b"x")
    encoder = lambda paths: [[1.0] + [0.0] * 511]  # noqa: E731
    sim = outlier_similarity_for_frame(
        p, outlier_embeddings=[], top_k=5, encode_fn=encoder,
    )
    assert sim == 0.0
