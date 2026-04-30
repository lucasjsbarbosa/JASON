"""Title + thumbnail embeddings.

Heavy ML deps (`torch`, `sentence-transformers`, `open_clip_torch`) live in
`[dependency-groups.ml]`. They're imported lazily so the test suite — which
injects fake encoders — doesn't need them installed.

Encoders are dependency-injected via `EncodeFn`, a callable that maps a list
of inputs to a list of float vectors. This keeps the persistence logic
testable without paying the model-download cost.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb

from jason.config import get_settings

logger = logging.getLogger(__name__)

TITLE_EMBED_DIM = 768   # paraphrase-multilingual-mpnet-base-v2
THUMB_EMBED_DIM = 512   # OpenCLIP ViT-B-32

# Type aliases for clarity
EncodeTextFn = Callable[[list[str]], list[list[float]]]
EncodeImageFn = Callable[[list[Path]], list[list[float]]]


# --- Default encoders (lazy import; only loaded when the user actually runs) -


def _default_title_encoder(*, show_progress: bool = False) -> EncodeTextFn:
    """Build the sentence-transformers PT-BR encoder. Downloads ~1GB on first call."""
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    model = SentenceTransformer("paraphrase-multilingual-mpnet-base-v2")

    def encode(texts: list[str]) -> list[list[float]]:
        vectors = model.encode(
            texts, normalize_embeddings=True, show_progress_bar=show_progress
        )
        return [list(map(float, v)) for v in vectors]

    return encode


def _default_thumb_encoder() -> EncodeImageFn:
    """Build the OpenCLIP ViT-B-32 image encoder. Downloads ~600MB on first call."""
    import open_clip  # noqa: PLC0415
    import torch  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
    model.eval()

    def encode(paths: list[Path]) -> list[list[float]]:
        images = [preprocess(Image.open(p).convert("RGB")).unsqueeze(0) for p in paths]
        batch = torch.cat(images, dim=0)
        with torch.no_grad():
            features = model.encode_image(batch)
            features = features / features.norm(dim=-1, keepdim=True)
        return [list(map(float, v)) for v in features.cpu().numpy()]

    return encode


# --- Helpers ---------------------------------------------------------------


def _ensure_features_row(con: duckdb.DuckDBPyConnection, video_ids: list[str]) -> None:
    """Insert a video_features row for any missing video_id. No-op if rows exist."""
    if not video_ids:
        return
    placeholders = ",".join(["(?)"] * len(video_ids))
    con.execute(
        f"""
        INSERT INTO video_features (video_id)
        SELECT v.id FROM (VALUES {placeholders}) AS v(id)
        WHERE v.id NOT IN (SELECT video_id FROM video_features)
        """,
        video_ids,
    )


# --- Title embeddings ------------------------------------------------------


def _read_pending_titles(
    con: duckdb.DuckDBPyConnection, *, channel_id: str | None, force: bool
) -> list[tuple[str, str]]:
    sql = ["SELECT v.id, v.title FROM videos v"]
    sql.append("LEFT JOIN video_features f ON f.video_id = v.id")
    if force:
        sql.append("WHERE 1=1")
    else:
        # Parens are critical: AND binds tighter than OR, so without them the
        # channel filter would only constrain the second branch of the OR.
        sql.append("WHERE (f.video_id IS NULL OR f.title_embedding IS NULL)")
    params: list[Any] = []
    if channel_id:
        sql.append("AND v.channel_id = ?")
        params.append(channel_id)
    return con.execute(" ".join(sql), params).fetchall()


def embed_titles(
    *,
    db_path: Path | None = None,
    channel_id: str | None = None,
    force: bool = False,
    encode_fn: EncodeTextFn | None = None,
    batch_size: int = 64,
    show_progress: bool = False,
) -> dict[str, int]:
    """Encode every (or one channel's) video title and persist to title_embedding.

    Args:
        encode_fn: callable taking list[str] returning list[list[float]] of length
            TITLE_EMBED_DIM. When None, builds the default sentence-transformers
            pipeline (downloads model on first call).
        show_progress: when True, the default encoder shows tqdm bars and the
            persistence loop logs every 10 batches. Used by the CLI for
            interactive runs; left False for tests / cron / Task Scheduler.
    """
    settings = get_settings()
    db = db_path or settings.duckdb_path

    with duckdb.connect(str(db)) as con:
        pending = _read_pending_titles(con, channel_id=channel_id, force=force)
        if not pending:
            return {"requested": 0, "encoded": 0}

        encoder = encode_fn or _default_title_encoder(show_progress=show_progress)

        ids = [r[0] for r in pending]
        _ensure_features_row(con, ids)

        total_batches = (len(pending) + batch_size - 1) // batch_size
        encoded = 0
        for batch_idx, i in enumerate(range(0, len(pending), batch_size), start=1):
            batch = pending[i : i + batch_size]
            vectors = encoder([t for _, t in batch])
            for (vid, _t), v in zip(batch, vectors, strict=True):
                if len(v) != TITLE_EMBED_DIM:
                    raise ValueError(
                        f"title encoder returned {len(v)}-dim vector, expected {TITLE_EMBED_DIM}"
                    )
                con.execute(
                    "UPDATE video_features SET title_embedding = ?, computed_at = now() "
                    "WHERE video_id = ?",
                    [v, vid],
                )
                encoded += 1
            if show_progress and (batch_idx % 10 == 0 or batch_idx == total_batches):
                logger.info(
                    "title embeddings: batch %d/%d (%d/%d titles)",
                    batch_idx, total_batches, encoded, len(pending),
                )

    logger.info("title embeddings: %d encoded", encoded)
    return {"requested": len(pending), "encoded": encoded}


# --- Thumbnail embeddings --------------------------------------------------


def _read_pending_thumbs(
    con: duckdb.DuckDBPyConnection,
    *,
    thumbs_dir: Path,
    channel_id: str | None,
    force: bool,
) -> list[tuple[str, Path]]:
    """Return (video_id, thumbnail_path) for videos with an on-disk thumbnail
    that doesn't yet have an embedding (or all, if force)."""
    sql = ["SELECT v.id FROM videos v"]
    sql.append("LEFT JOIN video_features f ON f.video_id = v.id")
    if force:
        sql.append("WHERE 1=1")
    else:
        # See _read_pending_titles re: parens.
        sql.append("WHERE (f.video_id IS NULL OR f.thumb_embedding IS NULL)")
    params: list[Any] = []
    if channel_id:
        sql.append("AND v.channel_id = ?")
        params.append(channel_id)
    rows = con.execute(" ".join(sql), params).fetchall()

    out: list[tuple[str, Path]] = []
    for (vid,) in rows:
        path = thumbs_dir / f"{vid}.jpg"
        if path.exists():
            out.append((vid, path))
    return out


def embed_thumbnails(
    *,
    db_path: Path | None = None,
    thumbs_dir: Path | None = None,
    channel_id: str | None = None,
    force: bool = False,
    encode_fn: EncodeImageFn | None = None,
    batch_size: int = 32,
    show_progress: bool = False,
) -> dict[str, int]:
    """Encode every on-disk thumbnail and persist to thumb_embedding.

    Skips videos without `data/thumbnails/{video_id}.jpg`. Run
    `jason ingest thumbnails` first to populate.

    A bad image (corrupt JPEG, 0-byte file) is logged and skipped — the
    surrounding batch is retried one-by-one so a single bad file doesn't
    discard the rest of the work.
    """
    settings = get_settings()
    db = db_path or settings.duckdb_path
    tdir = thumbs_dir or (settings.data_dir / "thumbnails")

    with duckdb.connect(str(db)) as con:
        pending = _read_pending_thumbs(
            con, thumbs_dir=tdir, channel_id=channel_id, force=force,
        )
        if not pending:
            return {"requested": 0, "encoded": 0, "skipped_invalid": 0}

        encoder = encode_fn or _default_thumb_encoder()

        ids = [vid for vid, _ in pending]
        _ensure_features_row(con, ids)

        total_batches = (len(pending) + batch_size - 1) // batch_size
        encoded = 0
        skipped_invalid = 0
        for batch_idx, i in enumerate(range(0, len(pending), batch_size), start=1):
            batch = pending[i : i + batch_size]
            try:
                vectors = encoder([p for _, p in batch])
            except Exception as exc:  # noqa: BLE001 — bad image kinds are open-ended
                logger.warning(
                    "thumb embeddings: batch %d failed (%s); retrying one-by-one",
                    batch_idx, exc,
                )
                vectors = []
                for _vid, p in batch:
                    try:
                        vectors.extend(encoder([p]))
                    except Exception as item_exc:  # noqa: BLE001
                        logger.warning("thumb embeddings: skipping %s (%s)", p, item_exc)
                        vectors.append(None)
                        skipped_invalid += 1
            for (vid, _p), v in zip(batch, vectors, strict=True):
                if v is None:
                    continue
                if len(v) != THUMB_EMBED_DIM:
                    raise ValueError(
                        f"thumb encoder returned {len(v)}-dim vector, expected {THUMB_EMBED_DIM}"
                    )
                con.execute(
                    "UPDATE video_features SET thumb_embedding = ?, computed_at = now() "
                    "WHERE video_id = ?",
                    [v, vid],
                )
                encoded += 1
            if show_progress and (batch_idx % 5 == 0 or batch_idx == total_batches):
                logger.info(
                    "thumb embeddings: batch %d/%d (%d encoded, %d skipped invalid)",
                    batch_idx, total_batches, encoded, skipped_invalid,
                )

    logger.info("thumb embeddings: %d encoded, %d skipped invalid", encoded, skipped_invalid)
    return {
        "requested": len(pending),
        "encoded": encoded,
        "skipped_invalid": skipped_invalid,
    }
