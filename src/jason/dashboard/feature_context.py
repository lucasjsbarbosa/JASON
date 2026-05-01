"""Distribution context pra features do modelo — \"o que seria melhor?\".

A explicação SHAP-like diz que `char_len = 65` atrapalhou, mas não fala se é
porque está GRANDE ou PEQUENO demais. Este módulo carrega a distribuição
dessa feature nos outliers do nicho (p≥90) e devolve uma frase comparando
o valor candidato com o típico vencedor.

Cache: as distribuições mudam só quando rodamos `jason features outliers`.
Carregadas on-demand e mantidas no processo via @lru_cache. Reset manual via
`reset_cache()`.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import duckdb

from jason.config import get_settings

logger = logging.getLogger(__name__)


# --- queries -------------------------------------------------------------


_NUMERIC_FEATURES = {
    "char_len":    "f.char_len",
    "word_count":  "f.word_count",
    "caps_ratio":  "f.caps_ratio",
    "duration_s":  "v.duration_s",
}

# Bool features cuja "ajuda/atrapalho" depende só de % nos outliers.
_BOOL_FEATURES = {
    "has_caps_word":         "f.has_caps_word",
    "has_number":            "f.has_number",
    "has_emoji":             "f.has_emoji",
    "has_question_mark":     "f.has_question_mark",
    "has_first_person":      "f.has_first_person",
    "has_explained_keyword": "f.has_explained_keyword",
    "has_ranking_keyword":   "f.has_ranking_keyword",
    "has_curiosity_keyword": "f.has_curiosity_keyword",
    "has_extreme_adjective": "f.has_extreme_adjective",
}


_TIER_BOUNDS = {
    0: (0, 1_000),
    1: (1_000, 10_000),
    2: (10_000, 100_000),
    3: (100_000, 1_000_000),
    4: (1_000_000, 10**12),
}


def _tier_label(bucket: int) -> str:
    """Human-friendly tier label, matches dashboard.humanize."""
    return {
        0: "muito pequeno (até 1k)",
        1: "pequeno (1k–10k)",
        2: "médio (10k–100k)",
        3: "grande (100k–1M)",
        4: "muito grande (1M+)",
    }.get(bucket, f"tier_{bucket}")


def _read_outlier_pool(
    db_path: Path, subs_bucket: int | None = None,
) -> list[tuple[Any, ...]]:
    """Pull outlier rows + multiplier. When `subs_bucket` is set, restrict to
    that tier — crucial because what counts as 'high CAPS' or 'long video'
    differs radically by channel size (tier_1 outliers cluster at 23% caps
    median; tier_4 at 79%). Without filtering, the context shown to a 1k-10k
    creator is dominated by 1M+ data and contradicts what the model learned."""
    sql = """
        SELECT f.char_len, f.word_count, f.caps_ratio, v.duration_s,
               f.has_caps_word, f.has_number, f.has_emoji,
               f.has_question_mark, f.has_first_person,
               f.has_explained_keyword, f.has_ranking_keyword,
               f.has_curiosity_keyword, f.has_extreme_adjective,
               EXTRACT(HOUR FROM v.published_at) AS pub_hour_utc,
               EXTRACT(DOW FROM v.published_at) AS pub_dow,
               o.multiplier
        FROM video_features f
        JOIN videos v ON v.id = f.video_id
        JOIN outliers o ON o.video_id = v.id
        JOIN channels c ON c.id = v.channel_id
        WHERE v.is_short = false AND o.percentile_in_channel >= 90
    """
    params: list[Any] = []
    if subs_bucket is not None and subs_bucket in _TIER_BOUNDS:
        lo, hi = _TIER_BOUNDS[subs_bucket]
        sql += " AND c.subs >= ? AND c.subs < ?"
        params.extend([lo, hi])
    with duckdb.connect(str(db_path), read_only=True) as con:
        return con.execute(sql, params).fetchall()


@lru_cache(maxsize=8)
def _outlier_distribution(
    db_path_str: str, subs_bucket: int | None = None,
) -> dict[str, Any]:
    """Compute distribution stats for the outlier pool, optionally restricted
    to a tier. Cached per (db, tier); call `reset_cache()` after re-running
    outliers."""
    rows = _read_outlier_pool(Path(db_path_str), subs_bucket=subs_bucket)
    if not rows:
        return {"n": 0}

    n = len(rows)

    def _quantiles(values: list[float]) -> dict[str, float]:
        s = sorted(v for v in values if v is not None)
        if not s:
            return {"n": 0, "median": 0, "p25": 0, "p75": 0}
        return {
            "n": len(s),
            "median": s[len(s) // 2],
            "p25": s[len(s) // 4],
            "p75": s[3 * len(s) // 4],
        }

    char_len   = _quantiles([float(r[0]) for r in rows if r[0] is not None])
    word_count = _quantiles([float(r[1]) for r in rows if r[1] is not None])
    caps_ratio = _quantiles([float(r[2]) for r in rows if r[2] is not None])
    duration   = _quantiles([float(r[3]) for r in rows if r[3] is not None])

    bool_rates: dict[str, float] = {}
    bool_lifts: dict[str, dict[str, float]] = {}
    bool_cols = list(_BOOL_FEATURES.keys())
    for i, col in enumerate(bool_cols):
        idx = 4 + i
        with_flag = [float(r[15]) for r in rows if r[idx] and r[15] is not None]
        without_flag = [float(r[15]) for r in rows if not r[idx] and r[15] is not None]
        bool_rates[col] = sum(1 for r in rows if r[idx]) / n
        # Median multiplier of outliers WITH the flag vs WITHOUT.
        # This is the "lift" — does using this feature actually distinguish
        # bigger outliers from smaller outliers within the tier?
        def _median(vs: list[float]) -> float | None:
            if not vs:
                return None
            s = sorted(vs)
            return s[len(s) // 2]
        bool_lifts[col] = {
            "median_with": _median(with_flag) or 0.0,
            "median_without": _median(without_flag) or 0.0,
            "n_with": len(with_flag),
            "n_without": len(without_flag),
        }

    # Hour distribution: top N hours sorted by frequency. Stored as UTC; we
    # convert to BRT in the user-facing string (consistent w/ humanize.py).
    hour_counts: dict[int, int] = {}
    for r in rows:
        if r[13] is not None:
            h = int(r[13])
            hour_counts[h] = hour_counts.get(h, 0) + 1

    dow_counts: dict[int, int] = {}
    for r in rows:
        if r[14] is not None:
            d = int(r[14])
            dow_counts[d] = dow_counts.get(d, 0) + 1

    return {
        "n": n,
        "char_len": char_len,
        "word_count": word_count,
        "caps_ratio": caps_ratio,
        "duration_s": duration,
        "bool_rates": bool_rates,
        "bool_lifts": bool_lifts,
        "hour_counts": hour_counts,  # UTC keys
        "dow_counts": dow_counts,
        "subs_bucket": subs_bucket,
    }


def reset_cache() -> None:
    """Drop the cached distribution. Use after `jason features outliers`."""
    _outlier_distribution.cache_clear()


# --- string formatters ---------------------------------------------------


def _classify_quantile(value: float, q: dict[str, float]) -> tuple[str, str]:
    """Returns (position, hint) where position ∈ {muito-baixo, baixo, ok,
    alto, muito-alto} and hint is a natural-language note."""
    if q["n"] == 0:
        return "ok", ""
    if value < q["p25"]:
        return "baixo", f"abaixo do típico vencedor (p25={q['p25']:.0f}, p75={q['p75']:.0f})"
    if value > q["p75"]:
        return "alto", f"acima do típico vencedor (p25={q['p25']:.0f}, p75={q['p75']:.0f})"
    return "ok", f"dentro da faixa típica vencedora ({q['p25']:.0f}–{q['p75']:.0f})"


def _utc_to_brt(h: int) -> int:
    return (h - 3) % 24


def context_for(
    feature: str,
    raw_value: Any,
    *,
    db_path: Path | None = None,
    subs_bucket: int | None = None,
) -> str:
    """Returns a short natural-language string with what a "good" value
    would look like for this feature, given the outlier distribution.

    When `subs_bucket` is set, the distribution is restricted to that tier.
    Without it, mixing tier_1 (1k-10k) with tier_4 (1M+) gives misleading
    context because `caps_ratio` median jumps from 23% to 79% across tiers.

    Empty string when no actionable context exists (cluster IDs, raw IDs, etc.).
    """
    settings = get_settings()
    db = db_path or settings.duckdb_path
    dist = _outlier_distribution(str(db), subs_bucket=subs_bucket)
    if dist.get("n", 0) == 0:
        # Fall back to global if tier-specific has no rows.
        if subs_bucket is not None:
            dist = _outlier_distribution(str(db), subs_bucket=None)
        if dist.get("n", 0) == 0:
            return ""

    # Prefix that makes the comparison's scope explicit. The user sees
    # "no seu tier" vs "no nicho geral" and knows which pool the % refers to.
    scope_prefix = (
        f"Outliers do seu tamanho ({_tier_label(subs_bucket)}): "
        if subs_bucket is not None and dist.get("subs_bucket") == subs_bucket
        else "Nicho geral: "
    )

    # Numeric — quantile-based positioning, per-feature formatting
    if feature in _NUMERIC_FEATURES:
        try:
            v = float(raw_value)
        except (TypeError, ValueError):
            return ""
        q = dist[feature]
        if q["n"] == 0:
            return ""
        if feature == "duration_s":
            pos = "abaixo" if v < q["p25"] else ("acima" if v > q["p75"] else "dentro")
            band = f"{q['p25']/60:.0f}–{q['p75']/60:.0f} min"
            ideal = f"{q['median']/60:.0f} min"
            if pos == "dentro":
                return f"{scope_prefix}dentro da faixa vencedora ({band}, ideal ~{ideal})"
            return f"{scope_prefix}{pos} da faixa vencedora ({band}, ideal ~{ideal})"
        if feature == "caps_ratio":
            v_pct = v * 100
            p25_pct, p75_pct, med_pct = q["p25"]*100, q["p75"]*100, q["median"]*100
            pos = "abaixo" if v_pct < p25_pct else ("acima" if v_pct > p75_pct else "dentro")
            if pos == "dentro":
                return f"{scope_prefix}dentro da faixa ({p25_pct:.0f}–{p75_pct:.0f}%, ideal ~{med_pct:.0f}%)"
            return (
                f"{scope_prefix}{pos} da faixa ({p25_pct:.0f}–{p75_pct:.0f}%) "
                f"— outliers usam ~{med_pct:.0f}%"
            )
        if feature == "char_len":
            pos = "abaixo" if v < q["p25"] else ("acima" if v > q["p75"] else "dentro")
            band = f"{q['p25']:.0f}–{q['p75']:.0f}"
            ideal = f"{q['median']:.0f}"
            if pos == "dentro":
                return f"{scope_prefix}dentro da faixa ({band} chars, ideal ~{ideal})"
            return f"{scope_prefix}{pos} da faixa ({band} chars, ideal ~{ideal})"
        if feature == "word_count":
            pos = "abaixo" if v < q["p25"] else ("acima" if v > q["p75"] else "dentro")
            band = f"{q['p25']:.0f}–{q['p75']:.0f}"
            ideal = f"{q['median']:.0f}"
            if pos == "dentro":
                return f"{scope_prefix}dentro da faixa ({band} palavras, ideal ~{ideal})"
            return f"{scope_prefix}{pos} da faixa ({band} palavras, ideal ~{ideal})"
        # Fallback genérico
        _pos, hint = _classify_quantile(v, q)
        return hint

    # Boolean — show share of outliers using it AND lift in median multiplier.
    # The lift is the key: rate alone misleads (a feature can be rare but
    # carry a 4× multiplier difference, like has_explained_keyword in tier_1).
    # The descriptive line should reinforce or qualify the SHAP, not contradict.
    if feature in _BOOL_FEATURES:
        rate = dist["bool_rates"].get(feature)
        if rate is None:
            return ""
        pct = rate * 100
        lift_data = dist.get("bool_lifts", {}).get(feature, {})
        med_with = lift_data.get("median_with") or 0.0
        med_without = lift_data.get("median_without") or 0.0
        n_with = lift_data.get("n_with", 0)
        n_without = lift_data.get("n_without", 0)
        # Lift: how much bigger is the median multiplier of outliers WITH the
        # flag vs outliers WITHOUT? Only trustworthy when both samples ≥5.
        has_lift = n_with >= 5 and n_without >= 5 and med_without > 0
        lift_ratio = (med_with / med_without) if has_lift else 1.0

        rarity = "raro" if rate < 0.2 else ("comum" if rate > 0.6 else "regular")
        if has_lift and lift_ratio >= 1.5:
            tail = (
                f"quem usa vira outlier {lift_ratio:.1f}× maior "
                f"(mediana {med_with:.1f}× vs {med_without:.1f}×)"
            )
        elif has_lift and lift_ratio <= 0.7:
            tail = (
                f"quem usa vira outlier MENOR (mediana {med_with:.1f}× vs "
                f"{med_without:.1f}× sem)"
            )
        else:
            tail = "sem distinção forte de retorno"

        return f"{scope_prefix}{rarity} ({pct:.0f}% dos vencedores usam) — {tail}"

    # published_hour — show top-3 horários BRT
    if feature == "published_hour":
        if not dist["hour_counts"]:
            return ""
        top = sorted(dist["hour_counts"].items(), key=lambda kv: -kv[1])[:3]
        brt_top = [f"{_utc_to_brt(h):02d}h" for h, _ in top]
        try:
            cand_brt = _utc_to_brt(int(float(raw_value)))
        except (TypeError, ValueError):
            return f"{scope_prefix}horários mais fortes {', '.join(brt_top)} BRT"
        match_strength = next(
            (n for h, n in top if _utc_to_brt(h) == cand_brt), None,
        )
        if match_strength:
            return f"{scope_prefix}{cand_brt:02d}h BRT é top-3 dos horários vencedores"
        return f"{scope_prefix}horários mais fortes {', '.join(brt_top)} BRT"

    # published_dow — top-3 dias
    if feature == "published_dow":
        if not dist["dow_counts"]:
            return ""
        names = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"]
        top = sorted(dist["dow_counts"].items(), key=lambda kv: -kv[1])[:3]
        top_str = ", ".join(names[d] for d, _ in top if 0 <= d <= 6)
        try:
            cand = int(float(raw_value))
            in_top = cand in [d for d, _ in top]
            cand_name = names[cand] if 0 <= cand <= 6 else str(cand)
        except (TypeError, ValueError):
            return f"{scope_prefix}dias mais fortes {top_str}"
        if in_top:
            return f"{scope_prefix}{cand_name} é top-3 dos dias vencedores"
        return f"{scope_prefix}dias mais fortes {top_str}"

    # cluster IDs / theme_id / franchise_id / days_to_release: skip
    return ""
