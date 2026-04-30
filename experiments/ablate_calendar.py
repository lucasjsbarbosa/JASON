"""Ablation experiment: is the model learning 'good title' or 'when to upload'?

Top-4 feature importances (gain) on the current model:
  days_to_nearest_horror_release, caps_ratio, duration_s, char_len.

Three of those are calendar/channel-level (NOT title craft). Suspeita levantada
no review externo: o modelo pode ser mais 'when to upload' do que 'good title'.

3 variants, mesma config (Optuna best params + 5 seeds + stratified split):

  (a) Baseline: tudo
  (b) Sem calendar: drop days_to_nearest_horror_release, published_hour,
      published_dow, is_halloween_week, is_friday_13_week. Mantém duration_s.
  (c) Sem calendar + sem duration: variante (b) menos duration_s.

Interpretation:
  (a→b) grande, (b→c) pequeno: calendar carrega o sinal, duration ruído
  (a→b) pequeno, (b→c) grande: duration é o que importa
  Ambos pequenos: título carrega o sinal real (foco em ranking objective ou
  label quality faz mais sentido que mais features de calendar)
  Ambos grandes: feature mix balanceado

Reporta também Counter(val.subs_bucket) — tier_1 esparso pode invalidar
todo o claim 'pairwise=0.633 generaliza pra @babygiulybaby'.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from jason.models.train import train
from jason.models.tune import load_best_params

CALENDAR_FEATURES = [
    "days_to_nearest_horror_release",
    "published_hour",
    "published_dow",
    "is_halloween_week",
    "is_friday_13_week",
]

VARIANTS = {
    "baseline": [],
    "no_calendar": CALENDAR_FEATURES,
    "no_calendar_no_duration": [*CALENDAR_FEATURES, "duration_s"],
}


def _bucket_distribution() -> Counter[int]:
    """Read val subs_bucket distribution from the just-trained baseline meta."""
    import duckdb  # noqa: PLC0415

    from jason.config import get_settings  # noqa: PLC0415
    settings = get_settings()
    with duckdb.connect(str(settings.duckdb_path), read_only=True) as con:
        rows = con.execute(
            """
            SELECT c.subs FROM channels c
            JOIN videos v ON v.channel_id = c.id
            JOIN outliers o ON o.video_id = v.id
            WHERE v.is_short = false
            """,
        ).fetchall()
    buckets: list[int] = []
    for (subs,) in rows:
        if subs is None or subs < 1000:
            buckets.append(0)
        elif subs < 10_000:
            buckets.append(1)
        elif subs < 100_000:
            buckets.append(2)
        elif subs < 1_000_000:
            buckets.append(3)
        else:
            buckets.append(4)
    return Counter(buckets)


def main() -> None:
    out_dir = Path("experiments")
    out_dir.mkdir(parents=True, exist_ok=True)

    best = load_best_params()
    if best is None:
        raise SystemExit("No best_params.json — run `jason model tune` first.")

    seeds = (42, 10042, 20042, 30042, 40042)

    print("=== bucket distribution (entire outliers pool, not just val) ===")
    dist = _bucket_distribution()
    bucket_names = {
        0: "tier_0 (<1k)", 1: "tier_1 (1k-10k)", 2: "tier_2 (10k-100k)",
        3: "tier_3 (100k-1M)", 4: "tier_4 (1M+)",
    }
    for b in sorted(dist.keys()):
        print(f"  {bucket_names[b]:<22} n={dist[b]}")
    print()

    results = {}
    for name, drop in VARIANTS.items():
        artifact_dir = Path("src/jason/models/artifacts") / f"ablation_{name}"
        print(f"=== variant: {name} ===")
        if drop:
            print(f"  dropping: {drop}")
        else:
            print("  baseline (no drops)")

        result = train(
            params=best,
            seeds=seeds,
            stratify_by_channel=True,
            drop_features=drop,
            artifact_dir=artifact_dir,
        )
        results[name] = {
            "n_train": result.n_train,
            "n_val": result.n_val,
            "spearman": result.spearman,
            "pairwise_intra_bucket_accuracy": result.pairwise_intra_bucket_accuracy,
            "feature_importance_top": dict(
                list(result.feature_importance.items())[:8],
            ),
        }
        print(
            f"  spearman={result.spearman:.4f} "
            f"pair_acc={result.pairwise_intra_bucket_accuracy:.4f}",
        )
        print()

    # Deltas
    base_acc = results["baseline"]["pairwise_intra_bucket_accuracy"]
    no_cal_acc = results["no_calendar"]["pairwise_intra_bucket_accuracy"]
    no_cal_dur_acc = results["no_calendar_no_duration"]["pairwise_intra_bucket_accuracy"]

    print("=== deltas ===")
    print(f"  baseline                     : {base_acc:.4f}")
    print(f"  no_calendar                  : {no_cal_acc:.4f} (Δ={no_cal_acc - base_acc:+.4f})")
    print(f"  no_calendar_no_duration      : {no_cal_dur_acc:.4f} (Δ={no_cal_dur_acc - base_acc:+.4f})")
    print()
    print("=== interpretation ===")
    a_to_b = base_acc - no_cal_acc
    b_to_c = no_cal_acc - no_cal_dur_acc
    if a_to_b > 0.05 and b_to_c < 0.02:
        print("  CALENDAR is the signal carrier. Duration is noise.")
        print("  Implication: model leans on 'when to upload', not title craft.")
    elif a_to_b < 0.02 and b_to_c > 0.05:
        print("  DURATION is the signal carrier.")
        print("  Implication: video length matters more than calendar.")
    elif a_to_b < 0.02 and b_to_c < 0.02:
        print("  TITLE features carry the signal — calendar+duration are minor.")
        print("  Implication: invest in ranking objective (LambdaRank) or label quality.")
    else:
        print("  Mixed: both calendar and duration carry signal, title contributes too.")

    # Persist
    out_json = out_dir / "ablate_calendar_results.json"
    out_json.write_text(json.dumps(
        {
            "bucket_distribution": dict(dist),
            "results": results,
            "deltas": {
                "baseline_to_no_calendar": no_cal_acc - base_acc,
                "no_calendar_to_no_calendar_no_duration": no_cal_dur_acc - no_cal_acc,
            },
        },
        indent=2,
    ), encoding="utf-8")
    print(f"\n→ results: {out_json}")


if __name__ == "__main__":
    main()
