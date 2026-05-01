"""title_to_theme_dist: cosine similarity do title_embedding vs centroide
dos outliers (p>=90) no MESMO theme_id.

Mede "quão prototípico do subgênero vencedor este título está". Sinal
ortogonal ao caps_ratio / has_explained: captura semântica vs estrutura.

Algoritmo:
  1. Pra cada theme_id, computar centroide = mean(title_embedding) dos
     outliers p>=90 desse tema. Excluir tema do próprio vídeo se ele
     mesmo é outlier (evita data leak).
  2. Pra cada vídeo: cosine(title_embedding, centroide_do_seu_tema).
     Vídeos sem theme_id (Camada A noise) recebem 0.0.

Sample mínimo: tema com <5 outliers não tem centroide confiável → 0.0.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from jason.config import get_settings

logger = logging.getLogger(__name__)


def _compute_centroids(
    con: duckdb.DuckDBPyConnection, *, min_outliers: int = 5,
) -> dict[int, list[float]]:
    """For each theme_id with >= min_outliers, compute the centroid of
    title embeddings of its outliers (p>=90)."""
    rows = con.execute(
        """
        SELECT f.theme_id, f.title_embedding
        FROM video_features f
        JOIN outliers o ON o.video_id = f.video_id
        WHERE o.percentile_in_channel >= 90
          AND f.theme_id IS NOT NULL AND f.theme_id >= 0
          AND f.title_embedding IS NOT NULL
        """,
    ).fetchall()

    by_theme: dict[int, list[list[float]]] = {}
    for theme_id, emb in rows:
        if theme_id is None:
            continue
        by_theme.setdefault(int(theme_id), []).append(list(emb))

    centroids: dict[int, list[float]] = {}
    for theme_id, embs in by_theme.items():
        if len(embs) < min_outliers:
            continue
        # Element-wise mean. Already L2-normalized at encode time, so
        # mean is a reasonable centroid; re-normalize for cosine purity.
        n = len(embs)
        dim = len(embs[0])
        mean = [0.0] * dim
        for e in embs:
            for i in range(dim):
                mean[i] += e[i]
        for i in range(dim):
            mean[i] /= n
        norm = sum(x * x for x in mean) ** 0.5
        if norm > 0:
            mean = [x / norm for x in mean]
        centroids[theme_id] = mean

    logger.info("centroids computed for %d themes (n>=5 outliers)", len(centroids))
    return centroids


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def compute_theme_alignment(
    *,
    db_path: Path | None = None,
    channel_id: str | None = None,
    force: bool = False,
    show_progress: bool = False,
    min_outliers_per_theme: int = 5,
) -> dict[str, int]:
    """Compute title_to_theme_dist for every video with title_embedding + theme_id."""
    settings = get_settings()
    db = db_path or settings.duckdb_path

    with duckdb.connect(str(db)) as con:
        centroids = _compute_centroids(con, min_outliers=min_outliers_per_theme)
        if not centroids:
            return {"requested": 0, "computed": 0, "centroids": 0}

        sql = [
            "SELECT v.id, f.title_embedding, f.theme_id FROM videos v",
            "JOIN video_features f ON f.video_id = v.id",
        ]
        if force:
            sql.append("WHERE 1=1")
        else:
            sql.append("WHERE f.title_to_theme_dist IS NULL")
        params: list = []
        if channel_id:
            sql.append("AND v.channel_id = ?")
            params.append(channel_id)
        rows = con.execute(" ".join(sql), params).fetchall()

        if not rows:
            return {"requested": 0, "computed": 0, "centroids": len(centroids)}

        computed = 0
        no_centroid = 0
        no_embedding = 0
        for i, (vid, emb, theme_id) in enumerate(rows, start=1):
            if emb is None:
                no_embedding += 1
                # Persist 0.0 explicitly so we don't keep retrying NULL rows.
                con.execute(
                    "UPDATE video_features SET title_to_theme_dist = ?, "
                    "computed_at = now() WHERE video_id = ?",
                    [0.0, vid],
                )
                continue
            if theme_id is None or int(theme_id) < 0 or int(theme_id) not in centroids:
                no_centroid += 1
                con.execute(
                    "UPDATE video_features SET title_to_theme_dist = ?, "
                    "computed_at = now() WHERE video_id = ?",
                    [0.0, vid],
                )
                continue
            sim = _cosine(list(emb), centroids[int(theme_id)])
            con.execute(
                "UPDATE video_features SET title_to_theme_dist = ?, "
                "computed_at = now() WHERE video_id = ?",
                [float(sim), vid],
            )
            computed += 1
            if show_progress and (i % 1000 == 0 or i == len(rows)):
                logger.info(
                    "theme_alignment: %d/%d (no_centroid=%d, no_emb=%d)",
                    i, len(rows), no_centroid, no_embedding,
                )

    return {
        "requested": len(rows),
        "computed": computed,
        "centroids": len(centroids),
        "no_centroid": no_centroid,
        "no_embedding": no_embedding,
    }
