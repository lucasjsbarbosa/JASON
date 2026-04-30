"""Pairwise intra-bucket accuracy desagregado por subs_bucket.

A métrica agregada é dominada pelos tiers com mais videos (3 + 4).
Pra @babygiulybaby (tier_1), o que importa é o pairwise DENTRO do tier_1.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from jason.models.predict import _load_artifacts, _featurize_for_score  # noqa: PLC0415
from jason.models.features import build_feature_matrix
from jason.models.train import _stratified_temporal_split, _stack_or_none, _featurize, _fit_kmeans, TITLE_KMEANS_K, THUMB_KMEANS_K


def _pairwise_for_bucket(y_true: np.ndarray, y_pred: np.ndarray, mask: np.ndarray) -> tuple[int, int]:
    """Returns (correct_pairs, total_pairs) within the masked subset."""
    idx = np.where(mask)[0]
    if len(idx) < 2:
        return 0, 0
    correct = 0
    total = 0
    for i_pos in range(len(idx)):
        for j_pos in range(i_pos + 1, len(idx)):
            i, j = idx[i_pos], idx[j_pos]
            if y_true[i] == y_true[j]:
                continue
            total += 1
            if (y_pred[i] - y_pred[j]) * (y_true[i] - y_true[j]) > 0:
                correct += 1
    return correct, total


def main() -> None:
    import pandas as pd  # noqa: PLC0415

    artifacts = _load_artifacts()
    boosters = artifacts["boosters"]
    meta = artifacts["meta"]
    feature_columns = meta["feature_columns"]

    # Reconstruct val set with the same stratified split (seed via np_state below)
    df = build_feature_matrix(only_with_multiplier=True)
    df["target"] = np.log1p(df["multiplier"])

    title_arr = _stack_or_none(df["title_embedding"], 768)
    thumb_arr = _stack_or_none(df["thumb_embedding"], 512)
    title_km = _fit_kmeans(title_arr, TITLE_KMEANS_K) if title_arr is not None else None
    thumb_km = _fit_kmeans(thumb_arr, THUMB_KMEANS_K) if thumb_arr is not None else None

    _train_df, val_df = _stratified_temporal_split(df, val_frac=0.2)

    X_va = _featurize(val_df, title_kmeans=title_km, thumb_kmeans=thumb_km)
    # Reorder cols to match training
    X_va = X_va[[c for c in feature_columns if c in X_va.columns]]

    y_va = val_df["target"].values
    buckets = val_df["subs_bucket"].values

    # Average ensemble
    preds = np.mean([b.predict(X_va) for b in boosters], axis=0)

    # Per bucket
    bucket_names = {
        0: "tier_0 (<1k)", 1: "tier_1 (1k-10k)", 2: "tier_2 (10k-100k)",
        3: "tier_3 (100k-1M)", 4: "tier_4 (1M+)",
    }
    print(f"{'bucket':<22}{'n_val':>8}{'pairs':>10}{'acc':>10}")
    for b in sorted(np.unique(buckets)):
        mask = buckets == b
        n = int(mask.sum())
        correct, total = _pairwise_for_bucket(y_va, preds, mask)
        if total == 0:
            print(f"{bucket_names[b]:<22}{n:>8}{0:>10}{'n/a':>10}")
        else:
            acc = correct / total
            print(f"{bucket_names[b]:<22}{n:>8}{total:>10}{acc:>10.4f}")

    # Aggregated
    correct_total = 0
    total_total = 0
    for b in np.unique(buckets):
        c, t = _pairwise_for_bucket(y_va, preds, buckets == b)
        correct_total += c
        total_total += t
    print()
    print(f"{'AGGREGATED':<22}{len(y_va):>8}{total_total:>10}{correct_total/total_total:>10.4f}")


if __name__ == "__main__":
    main()
