"""LightGBM regressor for `log1p(multiplier)`.

Per CLAUDE.md Fase 3:
    target  = log1p(outliers.multiplier)
    split   = 80% oldest by published_at → train, 20% newest → val
    metrics = Spearman correlation (overall) + pairwise ranking accuracy
              within each `subs_bucket` (the metric that matters because
              ranking small-channel titles by big-channel patterns is
              exactly the failure mode we want to avoid)
    artifact = models/artifacts/multiplier_v1/ (lgb model + kmeans + meta json)

Heavy ML deps (`lightgbm`, `scikit-learn`, `pandas`) live in `[dependency-groups.ml]`.
Lazy-imported so this module's import doesn't pull them.
"""

from __future__ import annotations

import json
import logging
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jason.config import get_settings
from jason.models.features import (
    CATEGORICAL_COLS,
    SCALAR_FEATURE_COLS,
    build_feature_matrix,
)

if TYPE_CHECKING:  # pragma: no cover
    import numpy as np
    import pandas as pd
    from sklearn.cluster import KMeans

logger = logging.getLogger(__name__)

ARTIFACT_VERSION = "v1"
TITLE_KMEANS_K = 20
THUMB_KMEANS_K = 20


@dataclass
class TrainResult:
    n_train: int
    n_val: int
    spearman: float
    pairwise_intra_bucket_accuracy: float
    feature_importance: dict[str, float]
    artifact_dir: Path


def _stack_or_none(series: pd.Series, expected_dim: int) -> np.ndarray | None:
    """Stack a series of list[float] into an (n, dim) array. Returns None if
    fewer than half the rows have a vector — k-means won't help."""
    import numpy as np  # noqa: PLC0415
    import pandas as pd  # noqa: PLC0415

    # Pandas Series fed by DuckDB delivers pd.NA for nulls (not Python None),
    # and FLOAT[N] arrays come through as tuples — so we normalize both.
    def _is_missing(v: Any) -> bool:
        try:
            return bool(pd.isna(v))
        except (TypeError, ValueError):
            return False

    valid_count = sum(1 for v in series if not _is_missing(v))
    if valid_count < len(series) // 2:
        return None
    rows = [
        list(v) if not _is_missing(v) else [0.0] * expected_dim
        for v in series
    ]
    return np.array(rows, dtype=np.float32)


def _fit_kmeans(arr: np.ndarray, k: int) -> KMeans:
    from sklearn.cluster import KMeans  # noqa: PLC0415

    n_samples = len(arr)
    effective_k = min(k, max(2, n_samples // 2))
    km = KMeans(n_clusters=effective_k, n_init=5, random_state=42)
    km.fit(arr)
    return km


def _featurize(
    df: pd.DataFrame,
    *,
    title_kmeans: KMeans | None,
    thumb_kmeans: KMeans | None,
) -> pd.DataFrame:
    """Build the X matrix LightGBM consumes from the feature DataFrame."""
    import numpy as np  # noqa: PLC0415
    import pandas as pd  # noqa: PLC0415

    X = df[list(SCALAR_FEATURE_COLS)].copy()
    for c in CATEGORICAL_COLS:
        X[c] = df[c].astype("category")

    def _missing(v: Any) -> bool:
        try:
            return bool(pd.isna(v))
        except (TypeError, ValueError):
            return False

    if title_kmeans is not None:
        dim = title_kmeans.n_features_in_
        title_arr = np.array(
            [list(v) if not _missing(v) else [0.0] * dim for v in df["title_embedding"]],
            dtype=np.float32,
        )
        X["title_cluster"] = pd.Categorical(title_kmeans.predict(title_arr))
    if thumb_kmeans is not None:
        dim = thumb_kmeans.n_features_in_
        thumb_arr = np.array(
            [list(v) if not _missing(v) else [0.0] * dim for v in df["thumb_embedding"]],
            dtype=np.float32,
        )
        X["thumb_cluster"] = pd.Categorical(thumb_kmeans.predict(thumb_arr))
    return X


def _temporal_split(df: pd.DataFrame, val_frac: float = 0.2) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sort by published_at, take the oldest 1-val_frac as train."""
    import pandas as pd  # noqa: PLC0415

    df = df.copy()
    df["published_at"] = pd.to_datetime(df["published_at"])
    df = df.sort_values("published_at")
    n_val = max(1, int(round(len(df) * val_frac)))
    train = df.iloc[:-n_val]
    val = df.iloc[-n_val:]
    return train, val


def _stratified_temporal_split(
    df: pd.DataFrame, val_frac: float = 0.2,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-channel temporal split: each channel contributes its newest val_frac
    to val and the rest to train. Avoids the failure mode where a channel ends
    up only in val (or only in train) which corrupts the intra-bucket metric."""
    import pandas as pd  # noqa: PLC0415

    df = df.copy()
    df["published_at"] = pd.to_datetime(df["published_at"])
    train_parts: list[pd.DataFrame] = []
    val_parts: list[pd.DataFrame] = []
    for _ch, g in df.groupby("channel_id"):
        g = g.sort_values("published_at")
        if len(g) < 5:
            train_parts.append(g)
            continue
        n_val = max(1, int(round(len(g) * val_frac)))
        train_parts.append(g.iloc[:-n_val])
        val_parts.append(g.iloc[-n_val:])
    train = pd.concat(train_parts) if train_parts else df.iloc[:0]
    val = pd.concat(val_parts) if val_parts else df.iloc[:0]
    return train, val


def _spearman(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    from scipy.stats import spearmanr  # noqa: PLC0415

    rho, _p = spearmanr(y_true, y_pred)
    return float(rho)


def _pairwise_intra_bucket_accuracy(
    y_true: np.ndarray, y_pred: np.ndarray, buckets: np.ndarray
) -> float:
    """For each pair (i, j) with same bucket and y_true[i] != y_true[j]:
    accuracy = fraction where sign(y_pred[i] - y_pred[j]) == sign(y_true[i] - y_true[j]).
    """
    import numpy as np  # noqa: PLC0415

    correct = 0
    total = 0
    for b in np.unique(buckets):
        idx = np.where(buckets == b)[0]
        if len(idx) < 2:
            continue
        for i_pos in range(len(idx)):
            for j_pos in range(i_pos + 1, len(idx)):
                i, j = idx[i_pos], idx[j_pos]
                if y_true[i] == y_true[j]:
                    continue
                total += 1
                if (y_pred[i] - y_pred[j]) * (y_true[i] - y_true[j]) > 0:
                    correct += 1
    if total == 0:
        return float("nan")
    return correct / total


DEFAULT_PARAMS: dict[str, Any] = {
    "objective": "regression",
    "metric": "rmse",
    "learning_rate": 0.05,
    "num_leaves": 31,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "verbosity": -1,
}


def _train_one_booster(
    X_tr: pd.DataFrame, y_tr: np.ndarray, X_va: pd.DataFrame, y_va: np.ndarray,
    *, cat_features: list[str], params: dict[str, Any],
    num_boost_round: int = 500, early_stopping: int = 30,
) -> Any:
    import lightgbm as lgb  # noqa: PLC0415

    dtrain = lgb.Dataset(X_tr, label=y_tr, categorical_feature=cat_features)
    dval = lgb.Dataset(X_va, label=y_va, categorical_feature=cat_features, reference=dtrain)
    return lgb.train(
        params, dtrain,
        num_boost_round=num_boost_round,
        valid_sets=[dval],
        callbacks=[lgb.early_stopping(stopping_rounds=early_stopping), lgb.log_evaluation(0)],
    )


def train(
    *,
    db_path: Path | None = None,
    artifact_dir: Path | None = None,
    params: dict[str, Any] | None = None,
    seeds: tuple[int, ...] = (42,),
    stratify_by_channel: bool = False,
    num_boost_round: int = 500,
    persist: bool = True,
) -> TrainResult:
    """Train the multiplier regressor end-to-end and persist artifacts.

    Args:
        params: hyperparameter overrides merged into DEFAULT_PARAMS. When None,
            uses DEFAULT_PARAMS as-is.
        seeds: ensemble seeds. Default (42,) trains a single model. Multiple
            seeds train independent boosters whose predictions are averaged
            for evaluation and at inference (predict.py reads `seeds` from
            meta.json and averages).
        stratify_by_channel: when True, validation slice is per-channel last
            20% rather than dataset-wide. Avoids channels-only-in-val bias.
        persist: when False (used by tune()), runs the full pipeline but
            doesn't write artifacts.
    """
    import numpy as np  # noqa: PLC0415

    settings = get_settings()
    artifacts = artifact_dir or (Path(__file__).parent / "artifacts" / f"multiplier_{ARTIFACT_VERSION}")
    if persist:
        artifacts.mkdir(parents=True, exist_ok=True)

    df = build_feature_matrix(db_path=db_path or settings.duckdb_path, only_with_multiplier=True)
    if len(df) < 50:
        raise RuntimeError(
            f"only {len(df)} videos have a multiplier — need ~50+ to train. "
            "Run `jason features outliers` after snapshots accumulate ~28 days."
        )

    df["target"] = np.log1p(df["multiplier"])

    title_arr = _stack_or_none(df["title_embedding"], 768)
    thumb_arr = _stack_or_none(df["thumb_embedding"], 512)
    title_km = _fit_kmeans(title_arr, TITLE_KMEANS_K) if title_arr is not None else None
    thumb_km = _fit_kmeans(thumb_arr, THUMB_KMEANS_K) if thumb_arr is not None else None

    if stratify_by_channel:
        train_df, val_df = _stratified_temporal_split(df, val_frac=0.2)
    else:
        train_df, val_df = _temporal_split(df, val_frac=0.2)
    X_tr = _featurize(train_df, title_kmeans=title_km, thumb_kmeans=thumb_km)
    X_va = _featurize(val_df, title_kmeans=title_km, thumb_kmeans=thumb_km)
    y_tr = train_df["target"].values
    y_va = val_df["target"].values

    cat_features = [c for c in X_tr.columns if str(X_tr[c].dtype) == "category"]

    merged_params: dict[str, Any] = {**DEFAULT_PARAMS, **(params or {})}

    boosters: list[tuple[int, Any]] = []
    for seed in seeds:
        seed_params = {
            **merged_params,
            "seed": seed,
            "feature_fraction_seed": seed,
            "bagging_seed": seed,
        }
        booster = _train_one_booster(
            X_tr, y_tr, X_va, y_va,
            cat_features=cat_features, params=seed_params,
            num_boost_round=num_boost_round,
        )
        boosters.append((seed, booster))

    # Average predictions for evaluation (also what predict.py will do at inference).
    preds = np.mean([b.predict(X_va) for _, b in boosters], axis=0)
    rho = _spearman(y_va, preds)
    pair_acc = _pairwise_intra_bucket_accuracy(y_va, preds, val_df["subs_bucket"].values)

    # Importance: aggregate gain across boosters in the ensemble.
    importance_acc: dict[str, int] = {}
    for _seed, b in boosters:
        for name, val in zip(b.feature_name(), b.feature_importance(), strict=True):
            importance_acc[name] = importance_acc.get(name, 0) + int(val)
    importance = dict(sorted(importance_acc.items(), key=lambda kv: kv[1], reverse=True))

    if persist:
        for seed, booster in boosters:
            booster.save_model(str(artifacts / f"model_seed_{seed}.lgb"))
        # Backward-compat alias for downstream that still expects model.lgb.
        boosters[0][1].save_model(str(artifacts / "model.lgb"))
        if title_km is not None:
            with (artifacts / "title_kmeans.pkl").open("wb") as f:
                pickle.dump(title_km, f)
        if thumb_km is not None:
            with (artifacts / "thumb_kmeans.pkl").open("wb") as f:
                pickle.dump(thumb_km, f)
        meta = {
            "version": ARTIFACT_VERSION,
            "n_train": len(train_df),
            "n_val": len(val_df),
            "spearman": rho,
            "pairwise_intra_bucket_accuracy": pair_acc,
            "feature_importance": {k: int(v) for k, v in importance.items()},
            "feature_columns": list(X_tr.columns),
            "categorical_features": cat_features,
            "has_title_kmeans": title_km is not None,
            "has_thumb_kmeans": thumb_km is not None,
            "seeds": list(seeds),
            "stratified_by_channel": stratify_by_channel,
            "params": merged_params,
        }
        (artifacts / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    logger.info(
        "trained on %d / val %d (seeds=%s, stratified=%s), spearman=%.3f, pair_acc=%.3f",
        len(train_df), len(val_df), seeds, stratify_by_channel, rho, pair_acc,
    )

    return TrainResult(
        n_train=len(train_df),
        n_val=len(val_df),
        spearman=rho,
        pairwise_intra_bucket_accuracy=pair_acc,
        feature_importance={k: float(v) for k, v in importance.items()},
        artifact_dir=artifacts,
    )
