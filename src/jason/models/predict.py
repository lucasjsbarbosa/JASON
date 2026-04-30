"""Score a candidate title (and optionally thumbnail) with the trained model.

Loads the artifacts written by `train.py`. The score is the predicted
`log1p(multiplier)`; the function exposes it as both raw log-space and the
exponentiated multiplier value (more interpretable: "this title looks like
a 3.2× outlier for this channel").
"""

from __future__ import annotations

import json
import logging
import pickle
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from jason.config import get_settings
from jason.models.features import (
    CATEGORICAL_COLS,
    SCALAR_FEATURE_COLS,
    assemble_score_row,
)
from jason.models.train import ARTIFACT_VERSION

logger = logging.getLogger(__name__)


def _artifact_dir() -> Path:
    return Path(__file__).parent / "artifacts" / f"multiplier_{ARTIFACT_VERSION}"


def _load_artifacts(artifact_dir: Path | None = None) -> dict[str, Any]:
    import lightgbm as lgb  # noqa: PLC0415

    art = artifact_dir or _artifact_dir()
    if not art.exists():
        raise FileNotFoundError(
            f"no model artifacts at {art}. Run `jason model train` first."
        )

    meta = json.loads((art / "meta.json").read_text(encoding="utf-8"))

    # Ensemble-aware load. Older artifacts (pre-ensemble) only have model.lgb;
    # newer ones list `seeds` in meta and have model_seed_<s>.lgb per seed.
    seeds = meta.get("seeds")
    if seeds:
        boosters = [
            lgb.Booster(model_file=str(art / f"model_seed_{s}.lgb")) for s in seeds
        ]
    else:
        boosters = [lgb.Booster(model_file=str(art / "model.lgb"))]

    title_km = None
    thumb_km = None
    if (art / "title_kmeans.pkl").exists():
        with (art / "title_kmeans.pkl").open("rb") as f:
            title_km = pickle.load(f)  # noqa: S301
    if (art / "thumb_kmeans.pkl").exists():
        with (art / "thumb_kmeans.pkl").open("rb") as f:
            thumb_km = pickle.load(f)  # noqa: S301

    return {
        "boosters": boosters,
        "meta": meta,
        "title_kmeans": title_km,
        "thumb_kmeans": thumb_km,
    }


def _featurize_for_score(
    row: pd.DataFrame, *, title_kmeans, thumb_kmeans, feature_columns: list[str]
) -> pd.DataFrame:
    X = row[list(SCALAR_FEATURE_COLS)].copy()
    for c in CATEGORICAL_COLS:
        X[c] = row[c].astype("category")

    if title_kmeans is not None:
        emb = row["title_embedding"].iloc[0]
        if emb is None:
            emb = [0.0] * title_kmeans.n_features_in_
        X["title_cluster"] = pd.Categorical(title_kmeans.predict(np.array([emb], dtype=np.float32)))
    if thumb_kmeans is not None:
        emb = row["thumb_embedding"].iloc[0]
        if emb is None:
            emb = [0.0] * thumb_kmeans.n_features_in_
        X["thumb_cluster"] = pd.Categorical(thumb_kmeans.predict(np.array([emb], dtype=np.float32)))

    # Reorder to the exact training column order so LightGBM doesn't complain.
    return X[feature_columns]


def score_title(
    title: str,
    channel_id: str,
    *,
    duration_s: int = 600,
    published_at: datetime | None = None,
    title_embedding: list[float] | None = None,
    thumb_embedding: list[float] | None = None,
    artifact_dir: Path | None = None,
    db_path: Path | None = None,
) -> dict[str, float]:
    """Predict the expected multiplier for a candidate title on `channel_id`.

    Returns:
        dict with `log_multiplier` (raw model output) and `multiplier`
        (exponentiated, the human-readable "outlier score").
    """
    settings = get_settings()
    artifacts = _load_artifacts(artifact_dir)
    boosters = artifacts["boosters"]
    meta = artifacts["meta"]

    pub = published_at or datetime.now(UTC).replace(microsecond=0)
    row = assemble_score_row(
        title=title,
        channel_id=channel_id,
        published_at=pub,
        duration_s=duration_s,
        title_embedding=title_embedding,
        thumb_embedding=thumb_embedding,
        db_path=db_path or settings.duckdb_path,
    )

    X = _featurize_for_score(
        row,
        title_kmeans=artifacts["title_kmeans"],
        thumb_kmeans=artifacts["thumb_kmeans"],
        feature_columns=meta["feature_columns"],
    )

    # Ensemble: average log-space predictions across boosters.
    log_mult = float(np.mean([b.predict(X)[0] for b in boosters]))
    return {"log_multiplier": log_mult, "multiplier": float(np.expm1(log_mult))}


def score_title_with_explanation(
    title: str,
    channel_id: str,
    *,
    duration_s: int = 600,
    published_at: datetime | None = None,
    title_embedding: list[float] | None = None,
    thumb_embedding: list[float] | None = None,
    artifact_dir: Path | None = None,
    db_path: Path | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Score a title AND return per-feature contributions to the prediction.

    LightGBM's `predict(..., pred_contrib=True)` returns SHAP-like values:
    last column is the base/expected value, others are signed contributions
    (positive = pushed log_multiplier UP, negative = pushed it DOWN). We
    average across the ensemble and pick the absolute-largest contributors.

    Returns:
        dict like score_title's output plus `contributions`: list of
        `{feature, value, contribution}`, sorted by |contribution|, top_k.
    """
    settings = get_settings()
    artifacts = _load_artifacts(artifact_dir)
    boosters = artifacts["boosters"]
    meta = artifacts["meta"]

    # Compute title_embedding on-the-fly when caller didn't pass one.
    # Without this, title_cluster falls back to an arbitrary default and the
    # SHAP contribution for that feature is meaningless noise.
    if title_embedding is None and artifacts.get("title_kmeans") is not None:
        try:
            from jason.features.embeddings import _default_title_encoder  # noqa: PLC0415
            title_embedding = _default_title_encoder()([title])[0]
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not compute title_embedding on-the-fly: %s", exc)

    # Hide features whose values are fake fallbacks (caller didn't provide
    # the input, so the SHAP contribution is meaningless noise):
    #   - thumb_cluster: depends on thumb_embedding upload (not in /avaliar)
    #   - title_cluster: depends on title_embedding (now computed above; only
    #     suppress if that failed)
    #   - theme_id / franchise_id: would need BERTopic.transform on the
    #     candidate. Default is sentinel -1 (BERTopic noise cluster), which
    #     trains as a real category but doesn't reflect "we detected this
    #     subgenre" — it reflects "we didn't run topic detection".
    suppress_features: set[str] = {"theme_id", "franchise_id"}
    if thumb_embedding is None:
        suppress_features.add("thumb_cluster")
    if title_embedding is None:
        suppress_features.add("title_cluster")

    pub = published_at or datetime.now(UTC).replace(microsecond=0)
    row = assemble_score_row(
        title=title,
        channel_id=channel_id,
        published_at=pub,
        duration_s=duration_s,
        title_embedding=title_embedding,
        thumb_embedding=thumb_embedding,
        db_path=db_path or settings.duckdb_path,
    )
    X = _featurize_for_score(
        row,
        title_kmeans=artifacts["title_kmeans"],
        thumb_kmeans=artifacts["thumb_kmeans"],
        feature_columns=meta["feature_columns"],
    )

    # Per-feature SHAP-like contributions (averaged across ensemble).
    # Shape: (n_samples, n_features + 1) — last column is base value.
    contribs = np.mean(
        [b.predict(X, pred_contrib=True)[0] for b in boosters], axis=0,
    )
    feature_names = meta["feature_columns"]
    feat_contrib = [
        (name, c) for name, c in zip(feature_names, contribs[:-1], strict=True)
        if name not in suppress_features
    ]
    feat_contrib.sort(key=lambda x: abs(x[1]), reverse=True)

    explanation = []
    for fname, c in feat_contrib[:top_k]:
        # The actual feature value used at prediction time, for context.
        import contextlib  # noqa: PLC0415
        if fname in X.columns:
            v = X[fname].iloc[0]
            with contextlib.suppress(AttributeError, ValueError):
                v = v.item() if hasattr(v, "item") else v
            value = str(v)
        else:
            value = "?"
        explanation.append({
            "feature": fname,
            "value": value,
            "contribution": float(c),
            "direction": "up" if c > 0 else "down",
        })

    log_mult = float(np.mean([b.predict(X)[0] for b in boosters]))
    return {
        "log_multiplier": log_mult,
        "multiplier": float(np.expm1(log_mult)),
        "contributions": explanation,
        "base_value": float(contribs[-1]),
    }
