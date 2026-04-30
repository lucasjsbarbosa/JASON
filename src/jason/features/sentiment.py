"""Sentiment + Arousal scoring de títulos via transformers (PT-BR).

Skill ablation mostrou: title features carregam ~70% do signal do modelo.
Adicionar dimensão de sentimento (score contínuo POS/NEG) é o próximo
investimento natural — captura algo que regex de keyword não captura
(\"DEU MUITO RUIM\" e \"AMEI ESSE FILME\" têm `has_extreme_adjective=False`
mas sentimentos opostos).

pysentimiento usa modelo `RoBERTuito` fine-tunado em PT-BR. ~500MB de
weights baixados automaticamente no primeiro uso. Lazy import — deps
heavy só carregam quando função é chamada.

Output: float [-1.0, +1.0] onde -1 = muito negativo, +1 = muito positivo,
0 = neutro. Persistido em `video_features.sentiment_score`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb

from jason.config import get_settings

logger = logging.getLogger(__name__)


def _default_arousal_encoder(*, batch_size: int = 128) -> Callable[[list[str]], list[float]]:
    """Arousal = |sentiment_score| via mesma stack do sentiment.

    Berger & Milkman 2012 mostraram que arousal (intensidade emocional)
    prediz viralidade melhor que polaridade isolada. Polaridade extrema (POS
    forte OU NEG forte) é high-arousal; polaridade próxima de 0 (neutro) é
    low-arousal. Implementação direta: |P(POS) - P(NEG)| do mesmo modelo de
    sentiment que já roda em PT-BR.

    Pesquisa inicial mirou pysentimiento emotion task pra derivar arousal de
    7 emoções (joy/anger/fear/etc), mas o modelo PT não existe no HF —
    pysentimiento só tem emotion pra es/en/it. Usar magnitude do sentiment é
    funcionalmente o mesmo signal: cobre arousal, custa nada (mesmo modelo),
    e zero risco de modelo missing.
    """
    sentiment_encode = _default_sentiment_encoder(batch_size=batch_size)

    def encode(texts: list[str]) -> list[float]:
        # |sentiment| ∈ [0, 1] = arousal. Polaridade extrema = high arousal.
        return [abs(s) for s in sentiment_encode(texts)]

    return encode


def _default_sentiment_encoder(*, batch_size: int = 64) -> Callable[[list[str]], list[float]]:
    """Builds a pysentimiento PT-BR analyzer with GPU when available.

    Downloads ~500MB on first use. CPU é proibitivo (~8h pra 25k títulos)
    então forçamos `cuda` quando torch.cuda.is_available().
    """
    import torch  # noqa: PLC0415
    from transformers import pipeline  # noqa: PLC0415

    use_cuda = torch.cuda.is_available()
    device = 0 if use_cuda else -1  # 0 = first GPU, -1 = CPU pra transformers
    # pysentimiento's create_analyzer wraps a transformers pipeline but does
    # NOT route to GPU automatically — kwargs not forwarded. Bypass: use the
    # transformers pipeline directly with the same fine-tuned model. Same
    # output (POS/NEU/NEG + scores), 50-100x faster on GPU.
    pipe = pipeline(
        "sentiment-analysis",
        model="pysentimiento/bertweet-pt-sentiment",
        device=device,
        top_k=None,  # devolve todas as classes com scores
    )
    logger.info("sentiment encoder: %s", "GPU (cuda)" if use_cuda else "CPU")

    def encode(texts: list[str]) -> list[float]:
        out: list[float] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            # Pipeline aceita lista direto, retorna list[list[{label, score}]]
            results = pipe(batch, batch_size=batch_size, truncation=True)
            for item in results:
                # item = [{"label": "POS", "score": ...}, {"label": "NEU", ...}, ...]
                scores = {x["label"]: x["score"] for x in item}
                pos = scores.get("POS", 0.0)
                neg = scores.get("NEG", 0.0)
                out.append(float(pos - neg))
        return out

    return encode


def _read_pending(
    con: duckdb.DuckDBPyConnection,
    *,
    channel_id: str | None,
    force: bool,
    column: str = "sentiment_score",
) -> list[tuple[str, str]]:
    """Returns (video_id, title) for videos missing the target column (or all if force)."""
    sql = ["SELECT v.id, v.title FROM videos v"]
    sql.append("LEFT JOIN video_features f ON f.video_id = v.id")
    if force:
        sql.append("WHERE 1=1")
    else:
        sql.append(f"WHERE (f.video_id IS NULL OR f.{column} IS NULL)")
    params: list[Any] = []
    if channel_id:
        sql.append("AND v.channel_id = ?")
        params.append(channel_id)
    return con.execute(" ".join(sql), params).fetchall()


def compute_sentiment(
    *,
    db_path: Path | None = None,
    channel_id: str | None = None,
    force: bool = False,
    encode_fn: Callable[[list[str]], list[float]] | None = None,
    batch_size: int = 32,
    show_progress: bool = False,
) -> dict[str, int]:
    """Compute and persist sentiment_score for every (or one channel's) video title.

    Args:
        encode_fn: callable taking list[str] returning list[float] in [-1, +1].
            When None, builds the default pysentimiento PT-BR pipeline (downloads
            model on first call).
        force: recompute even if already populated.
    """
    settings = get_settings()
    db = db_path or settings.duckdb_path

    with duckdb.connect(str(db)) as con:
        pending = _read_pending(con, channel_id=channel_id, force=force)
        if not pending:
            return {"requested": 0, "encoded": 0}

        encoder = encode_fn or _default_sentiment_encoder()

        # Ensure video_features row exists for any new videos.
        ids = [r[0] for r in pending]
        placeholders = ",".join(["(?)"] * len(ids))
        con.execute(
            f"""
            INSERT INTO video_features (video_id)
            SELECT v.id FROM (VALUES {placeholders}) AS v(id)
            WHERE v.id NOT IN (SELECT video_id FROM video_features)
            """,
            ids,
        )

        total_batches = (len(pending) + batch_size - 1) // batch_size
        encoded = 0
        for batch_idx, i in enumerate(range(0, len(pending), batch_size), start=1):
            batch = pending[i : i + batch_size]
            scores = encoder([t for _, t in batch])
            for (vid, _t), s in zip(batch, scores, strict=True):
                con.execute(
                    "UPDATE video_features SET sentiment_score = ?, computed_at = now() "
                    "WHERE video_id = ?",
                    [float(s), vid],
                )
                encoded += 1
            if show_progress and (batch_idx % 20 == 0 or batch_idx == total_batches):
                logger.info(
                    "sentiment: batch %d/%d (%d/%d titles)",
                    batch_idx, total_batches, encoded, len(pending),
                )

    logger.info("sentiment: %d encoded", encoded)
    return {"requested": len(pending), "encoded": encoded}


def compute_arousal(
    *,
    db_path: Path | None = None,
    channel_id: str | None = None,
    force: bool = False,
    encode_fn: Callable[[list[str]], list[float]] | None = None,
    batch_size: int = 128,
    show_progress: bool = False,
) -> dict[str, int]:
    """Compute and persist arousal_score [0, 1] for every (or one channel's) title."""
    settings = get_settings()
    db = db_path or settings.duckdb_path

    with duckdb.connect(str(db)) as con:
        pending = _read_pending(con, channel_id=channel_id, force=force, column="arousal_score")
        if not pending:
            return {"requested": 0, "encoded": 0}

        encoder = encode_fn or _default_arousal_encoder()

        ids = [r[0] for r in pending]
        placeholders = ",".join(["(?)"] * len(ids))
        con.execute(
            f"""
            INSERT INTO video_features (video_id)
            SELECT v.id FROM (VALUES {placeholders}) AS v(id)
            WHERE v.id NOT IN (SELECT video_id FROM video_features)
            """,
            ids,
        )

        total_batches = (len(pending) + batch_size - 1) // batch_size
        encoded = 0
        for batch_idx, i in enumerate(range(0, len(pending), batch_size), start=1):
            batch = pending[i : i + batch_size]
            scores = encoder([t for _, t in batch])
            for (vid, _t), s in zip(batch, scores, strict=True):
                con.execute(
                    "UPDATE video_features SET arousal_score = ?, computed_at = now() WHERE video_id = ?",
                    [float(s), vid],
                )
                encoded += 1
            if show_progress and (batch_idx % 20 == 0 or batch_idx == total_batches):
                logger.info(
                    "arousal: batch %d/%d (%d/%d titles)",
                    batch_idx, total_batches, encoded, len(pending),
                )

    logger.info("arousal: %d encoded", encoded)
    return {"requested": len(pending), "encoded": encoded}
