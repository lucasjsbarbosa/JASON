"""Hyperparameter tuning for the multiplier regressor via Optuna.

Optimizes pairwise_intra_bucket_accuracy (the metric that matters per
CLAUDE.md — ranking small-channel titles by big-channel patterns is the
exact failure mode we want to avoid).

The search uses TPE (Tree-structured Parzen Estimator) which converges
faster than random/grid for low-dimensional spaces (~8 hyperparams here).
Each trial trains a single booster (no ensemble at tune time — ensemble is
applied AFTER best params are picked) and reports val accuracy.

Persists best params to `<artifact_dir>/best_params.json`. `train()` reads
them when the CLI flag `--best-params` is set.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from jason.models.train import ARTIFACT_VERSION, train

logger = logging.getLogger(__name__)


def _artifact_dir() -> Path:
    return Path(__file__).parent / "artifacts" / f"multiplier_{ARTIFACT_VERSION}"


def _objective(trial: Any) -> float:
    params = {
        "learning_rate": trial.suggest_float("learning_rate", 0.005, 0.2, log=True),
        "num_leaves": trial.suggest_int("num_leaves", 15, 255),
        "min_child_samples": trial.suggest_int("min_child_samples", 5, 100),
        "lambda_l1": trial.suggest_float("lambda_l1", 1e-8, 10.0, log=True),
        "lambda_l2": trial.suggest_float("lambda_l2", 1e-8, 10.0, log=True),
        "feature_fraction": trial.suggest_float("feature_fraction", 0.5, 1.0),
        "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
        "bagging_freq": trial.suggest_int("bagging_freq", 0, 10),
        "max_depth": trial.suggest_int("max_depth", 3, 14),
    }

    result = train(
        params=params,
        seeds=(42,),
        stratify_by_channel=True,
        persist=False,
    )
    return result.pairwise_intra_bucket_accuracy


def tune(
    *,
    n_trials: int = 50,
    timeout_seconds: int | None = None,
    output_path: Path | None = None,
    show_progress: bool = True,
) -> dict[str, Any]:
    """Run Optuna search and persist best params.

    Args:
        n_trials: number of trials (each trains one booster ~30-60s).
        timeout_seconds: optional wall-clock cap for the search.
        output_path: where to write best_params.json (default: artifacts dir).
        show_progress: TPE progress bar.

    Returns:
        dict with `best_params`, `best_score`, `n_trials_completed`.
    """
    import optuna  # noqa: PLC0415

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    out = output_path or (_artifact_dir() / "best_params.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=8, n_warmup_steps=0),
    )
    study.optimize(
        _objective,
        n_trials=n_trials,
        timeout=timeout_seconds,
        show_progress_bar=show_progress,
    )

    payload = {
        "best_params": study.best_params,
        "best_score": float(study.best_value),
        "n_trials_completed": len(study.trials),
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("tune wrote %s — best pair_acc=%.4f", out, study.best_value)
    return payload


def load_best_params(*, path: Path | None = None) -> dict[str, Any] | None:
    """Read best params persisted by `tune()`. Returns None if not present."""
    p = path or (_artifact_dir() / "best_params.json")
    if not p.exists():
        return None
    payload = json.loads(p.read_text(encoding="utf-8"))
    return payload.get("best_params")
