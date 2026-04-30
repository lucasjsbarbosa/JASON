"""RAG retrieval — find the closest outlier titles in the niche to a query.

Per CLAUDE.md Fase 4: "dado um tópico ou transcrição, calcula embedding,
faz busca por similaridade nos top-200 vídeos do nicho com
percentile_in_channel >= 90, retorna os 20 mais similares."

Until the outlier percentiles materialize (~28 days of snapshots), this
falls back to "high-niche-score" videos so the user can already prototype
the prompt structure.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb

from jason.config import get_settings

logger = logging.getLogger(__name__)


def _default_embedder() -> Callable[[str], list[float]]:
    """Lazy import — same model the title encoder uses, kept consistent."""
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    model = SentenceTransformer("paraphrase-multilingual-mpnet-base-v2")

    def encode(text: str) -> list[float]:
        v = model.encode([text], normalize_embeddings=True, show_progress_bar=False)[0]
        return list(map(float, v))

    return encode


def _candidate_pool_query(*, percentile_threshold: float, pool_size: int) -> tuple[str, list[Any]]:
    """SQL for the candidate pool: top-N most-outlier titles from the niche.
    Falls back to 'best niche-score' if no percentiles exist yet."""
    sql = """
        SELECT v.id, v.title, c.title AS channel_title, f.title_embedding,
               COALESCE(o.percentile_in_channel, 0.0) AS pct,
               COALESCE(o.multiplier, 0.0)            AS mult
        FROM videos v
        JOIN channels c ON c.id = v.channel_id
        JOIN video_features f ON f.video_id = v.id
        LEFT JOIN outliers o ON o.video_id = v.id
        WHERE v.is_short = false
          AND f.title_embedding IS NOT NULL
          AND o.percentile_in_channel >= ?
        ORDER BY o.percentile_in_channel DESC, o.multiplier DESC
        LIMIT ?
    """
    return sql, [percentile_threshold, pool_size]


def _fallback_pool_query(*, pool_size: int) -> tuple[str, list[Any]]:
    """Without outlier percentiles, rank by raw views as a coarse proxy for
    'this title actually packed a punch'. Joins the latest snapshot."""
    sql = """
        SELECT v.id, v.title, c.title AS channel_title, f.title_embedding,
               0.0 AS pct, 0.0 AS mult
        FROM videos v
        JOIN channels c ON c.id = v.channel_id
        JOIN video_features f ON f.video_id = v.id
        JOIN (
            SELECT video_id, MAX(views) AS views
            FROM video_stats_snapshots
            GROUP BY video_id
        ) latest ON latest.video_id = v.id
        WHERE v.is_short = false
          AND f.title_embedding IS NOT NULL
        ORDER BY latest.views DESC
        LIMIT ?
    """
    return sql, [pool_size]


def _cosine(a: list[float], b: list[float]) -> float:
    # Embeddings are already L2-normalized by the encoder, so dot == cosine.
    return sum(x * y for x, y in zip(a, b, strict=True))


def _mmr_select(
    items: list[dict[str, Any]],
    *,
    top_k: int,
    lambda_diversity: float,
) -> list[dict[str, Any]]:
    """Maximal Marginal Relevance selection.

    For each step, picks the candidate that maximizes:
        score(c) = λ · sim(query, c)  -  (1−λ) · max(sim(c, s) for s in selected)

    Each `items` entry must have `similarity` (vs query) and `embedding`
    (list[float], L2-normalized — dot equals cosine). When λ=1.0 this
    degrades to top-k by similarity (sanity check).
    """
    if not items:
        return []
    if top_k >= len(items):
        return sorted(items, key=lambda r: r["similarity"], reverse=True)

    pool = sorted(items, key=lambda r: r["similarity"], reverse=True)
    selected: list[dict[str, Any]] = [pool.pop(0)]

    while pool and len(selected) < top_k:
        best_idx = 0
        best_score = -float("inf")
        for i, c in enumerate(pool):
            max_sim_to_selected = max(
                _cosine(c["embedding"], s["embedding"]) for s in selected
            )
            score = lambda_diversity * c["similarity"] - (
                1.0 - lambda_diversity
            ) * max_sim_to_selected
            if score > best_score:
                best_score = score
                best_idx = i
        selected.append(pool.pop(best_idx))

    return selected


def search_outliers(
    query: str,
    *,
    db_path: Path | None = None,
    top_k: int = 20,
    percentile_threshold: float = 90.0,
    pool_size: int = 200,
    embedder: Callable[[str], list[float]] | None = None,
    lambda_diversity: float = 0.7,
) -> list[dict[str, Any]]:
    """Return `top_k` outlier titles in the niche, balanced via MMR.

    Top-k cosine alone clusters: when the query embeds near a dense region
    (a specific film), the 20 results end up near-duplicates and Claude
    receives one structure to riff on. MMR with `lambda_diversity` ∈ [0, 1]
    iteratively picks items balancing relevance to the query against
    novelty vs items already chosen:

        score(c) = λ · sim(query, c)  -  (1-λ) · max(sim(c, s) for s in selected)

    Args:
        query: free text (transcript summary, theme description, candidate
            title — anything that captures what the new video is about).
        top_k: how many similar titles to return.
        percentile_threshold: minimum `percentile_in_channel` for a video to
            enter the candidate pool. Default 90 (CLAUDE.md spec).
        pool_size: max size of the outlier pool to embedding-compare against.
        embedder: callable taking str returning list[float] (768d). Defaults
            to lazy-loaded sentence-transformers.
        lambda_diversity: λ in MMR. 1.0 → pure top-k (no diversity),
            0.0 → maximum diversity. Default 0.7 trades relevance vs
            non-redundancy moderately.

    Returns:
        List of dicts with `video_id`, `title`, `channel_title`,
        `percentile`, `multiplier`, `similarity` (cosine vs query).
    """
    settings = get_settings()
    db = db_path or settings.duckdb_path

    with duckdb.connect(str(db), read_only=True) as con:
        sql, params = _candidate_pool_query(
            percentile_threshold=percentile_threshold, pool_size=pool_size,
        )
        rows = con.execute(sql, params).fetchall()
        if not rows:
            logger.info(
                "no outliers with percentile >= %s — falling back to top-views pool",
                percentile_threshold,
            )
            sql, params = _fallback_pool_query(pool_size=pool_size)
            rows = con.execute(sql, params).fetchall()

    if not rows:
        return []

    encode_fn = embedder or _default_embedder()
    qv = encode_fn(query)

    scored = []
    for vid, title, channel_title, embedding, pct, mult in rows:
        if embedding is None:
            continue
        emb = list(embedding)
        scored.append({
            "video_id": vid,
            "title": title,
            "channel_title": channel_title,
            "percentile": float(pct),
            "multiplier": float(mult),
            "similarity": _cosine(qv, emb),
            "embedding": emb,
        })

    selected = _mmr_select(scored, top_k=top_k, lambda_diversity=lambda_diversity)
    # Drop the embedding from the public payload — it's only needed during MMR.
    for r in selected:
        r.pop("embedding", None)
    return selected
