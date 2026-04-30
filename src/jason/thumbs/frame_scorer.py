"""Score candidate frames vs the niche's outlier thumbnails (CLIP similarity).

Per CLAUDE.md Fase 4.5:
    score = 0.4 * face_score + 0.6 * outlier_similarity

`face_score`: 1 face = 1.0, 2 faces = 0.8, 0 faces = 0.0, 3+ = 0.5 (cluttered).
`outlier_similarity`: cosine of frame's CLIP embedding vs the centroid of
outlier thumbnails (`percentile_in_channel >= 90`, optionally same theme_id).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb

from jason.config import get_settings

logger = logging.getLogger(__name__)


def face_score(frame_path: Path) -> float:
    """Cheap Haar-cascade face count → score 0..1. No model download."""
    import cv2  # noqa: PLC0415

    classifier = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml",
    )
    img = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
    if img is None:
        return 0.0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    faces = classifier.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(60, 60))
    n = len(faces)
    if n == 0:
        return 0.0
    if n == 1:
        return 1.0
    if n == 2:
        return 0.8
    return 0.5


def _outlier_embeddings(
    *,
    db_path: Path,
    theme_id: int | None = None,
    percentile_threshold: float = 90.0,
) -> list[list[float]]:
    """Raw outlier thumb_embeddings (optionally same theme).

    Returns the list of L2-normalized 512-d vectors. Caller decides what to do
    with them — centroid (washes-out distinctive signals) vs max-sim top-K
    (premia 1 clone) vs mean(top-K) (robusto, recomendado).
    """
    sql = """
        SELECT f.thumb_embedding
        FROM video_features f
        JOIN outliers o ON o.video_id = f.video_id
        WHERE f.thumb_embedding IS NOT NULL
          AND o.percentile_in_channel >= ?
    """
    params: list[Any] = [percentile_threshold]
    if theme_id is not None:
        sql += " AND f.theme_id = ?"
        params.append(theme_id)

    with duckdb.connect(str(db_path), read_only=True) as con:
        rows = con.execute(sql, params).fetchall()
    return [list(r[0]) for r in rows if r[0] is not None]


def outlier_similarity_for_frame(
    frame_path: Path,
    *,
    outlier_embeddings: list[list[float]],
    top_k: int = 5,
    encode_fn: Callable[[list[Path]], list[list[float]]] | None = None,
) -> float:
    """Mean cosine similarity to the top-K most similar outlier thumbs.

    Why mean(top-K) instead of centroid OR max:

    - **Centroid washes out distinctive signals**: averaging 1352 diverse
      horror outliers (slasher + possessão + found footage + true crime)
      gives a vector pointing at "generic horror". A frame near that
      centroid is near the AVERAGE — which is what passes unnoticed.
    - **Pure max premia clones**: a frame near a single outlier maxes the
      score; a frame mildly similar to several distinct winning patterns
      is penalized. We want the latter.
    - **mean(top-K)** captures "this frame matches multiple winning
      structures", robust to single-outlier overfit.
    """
    if not outlier_embeddings:
        return 0.0
    if encode_fn is None:
        from jason.features.embeddings import _default_thumb_encoder  # noqa: PLC0415
        encode_fn = _default_thumb_encoder()

    frame_vec = encode_fn([frame_path])[0]
    sims = [
        sum(a * b for a, b in zip(frame_vec, emb, strict=True))
        for emb in outlier_embeddings
    ]
    sims.sort(reverse=True)
    take = sims[: min(top_k, len(sims))]
    return sum(take) / len(take)


def score_frames(
    frame_paths: list[Path],
    *,
    db_path: Path | None = None,
    theme_id: int | None = None,
    top_k_similarity: int = 5,
    encode_fn: Callable[[list[Path]], list[list[float]]] | None = None,
) -> list[dict[str, Any]]:
    """For each frame: face_score + mean(top-K outlier_similarity) → combined.

    Returns list ordered best→worst. `top_k_similarity` controls how many
    of the closest outlier thumbnails contribute to the similarity score
    (default 5 — mean of top-5 cosine sims).
    """
    settings = get_settings()
    db = db_path or settings.duckdb_path

    outliers = _outlier_embeddings(db_path=db, theme_id=theme_id)
    if not outliers:
        logger.warning(
            "no outlier thumbnails with percentile >= 90 (theme=%s) — "
            "outlier_similarity will be 0 for all frames", theme_id,
        )

    out = []
    for p in frame_paths:
        face = face_score(p)
        sim = (
            outlier_similarity_for_frame(
                p, outlier_embeddings=outliers,
                top_k=top_k_similarity, encode_fn=encode_fn,
            )
            if outliers
            else 0.0
        )
        combined = 0.4 * face + 0.6 * max(sim, 0.0)
        out.append({
            "path": p,
            "face_score": face,
            "outlier_similarity": sim,
            "combined": combined,
        })

    out.sort(key=lambda r: r["combined"], reverse=True)
    return out
