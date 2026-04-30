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


def _outlier_centroid(
    *,
    db_path: Path,
    theme_id: int | None = None,
    percentile_threshold: float = 90.0,
) -> list[float] | None:
    """Average thumb_embedding of outlier thumbnails (optionally same theme).
    Returns None if no qualifying samples exist."""
    import numpy as np  # noqa: PLC0415

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
    if not rows:
        return None

    arr = np.array([list(r[0]) for r in rows], dtype=np.float32)
    centroid = arr.mean(axis=0)
    norm = float(np.linalg.norm(centroid))
    if norm > 0:
        centroid = centroid / norm
    return centroid.tolist()


def outlier_similarity_for_frame(
    frame_path: Path,
    *,
    centroid: list[float],
    encode_fn: Callable[[list[Path]], list[list[float]]] | None = None,
) -> float:
    """Cosine similarity of frame's CLIP embedding to the precomputed centroid."""
    if encode_fn is None:
        from jason.features.embeddings import _default_thumb_encoder  # noqa: PLC0415
        encode_fn = _default_thumb_encoder()

    vec = encode_fn([frame_path])[0]
    return sum(a * b for a, b in zip(vec, centroid, strict=True))


def score_frames(
    frame_paths: list[Path],
    *,
    db_path: Path | None = None,
    theme_id: int | None = None,
    encode_fn: Callable[[list[Path]], list[list[float]]] | None = None,
) -> list[dict[str, Any]]:
    """For each frame: face_score + outlier_similarity → combined score.
    Returns list ordered best→worst."""
    settings = get_settings()
    db = db_path or settings.duckdb_path

    centroid = _outlier_centroid(db_path=db, theme_id=theme_id)
    if centroid is None:
        logger.warning(
            "no outlier thumbnails with percentile >= 90 (theme=%s) — "
            "outlier_similarity will be 0 for all frames", theme_id,
        )

    out = []
    for p in frame_paths:
        face = face_score(p)
        sim = outlier_similarity_for_frame(p, centroid=centroid, encode_fn=encode_fn) if centroid else 0.0
        combined = 0.4 * face + 0.6 * max(sim, 0.0)
        out.append({
            "path": p,
            "face_score": face,
            "outlier_similarity": sim,
            "combined": combined,
        })

    out.sort(key=lambda r: r["combined"], reverse=True)
    return out
