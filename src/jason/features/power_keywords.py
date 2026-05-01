"""Power keywords: n-gram log-odds dos outliers vs baseline, por theme_id.

Pra cada subgênero (theme_id), descobre quais bi/trigrams aparecem
desproporcionalmente nos títulos de outliers (p>=90) vs no baseline do
mesmo tema (todos os vídeos não-outliers do tema). Mostra à criadora
"que palavra está bombando neste subgênero agora".

Método: log-odds com Dirichlet smoothing (Monroe et al. 2008). Mais
robusto que TF-IDF pra comparar duas distribuições de tamanhos
diferentes — produz score com erro padrão calibrado, sem dominância
de palavras frequentes.

z = (log(p_outlier / (1-p_outlier)) - log(p_baseline / (1-p_baseline)))
    / sqrt(1/(c_outlier + alpha) + 1/(c_baseline + alpha))

Trigrams + bigrams. Stopwords PT-BR removidas. Token min_count >= 3.
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

import duckdb

from jason.config import get_settings

logger = logging.getLogger(__name__)


_STOPWORDS_PT = {
    "a", "o", "e", "de", "da", "do", "das", "dos", "um", "uma", "uns", "umas",
    "que", "se", "no", "na", "nos", "nas", "em", "por", "para", "com", "sem",
    "ao", "aos", "à", "às", "é", "são", "foi", "ser", "ter", "tem", "tinha",
    "como", "mas", "ou", "também", "tambem", "muito", "mais", "menos",
    "ja", "já", "ainda", "só", "sob", "sobre", "depois", "antes", "este",
    "esta", "esse", "essa", "isso", "aquele", "aquela", "aquilo", "lhe",
    "the", "of", "and", "or", "to", "in", "on", "at", "is", "are", "for",
    "by", "with", "from", "an",
}


_TOKEN_RE = re.compile(r"[a-z0-9çãáéíóúâêôàü]+", re.IGNORECASE)


def _tokenize(title: str) -> list[str]:
    """Lowercase, ASCII-fold optional (keep accents for PT-BR), split on
    non-word. Filters tokens with len < 2 and stopwords."""
    s = title.lower()
    # Keep accented chars but strip emojis / pure punctuation.
    toks = _TOKEN_RE.findall(s)
    return [t for t in toks if len(t) >= 2 and t not in _STOPWORDS_PT]


def _ascii_fold(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _ngrams(tokens: list[str], n: int) -> Iterable[str]:
    for i in range(len(tokens) - n + 1):
        yield " ".join(tokens[i : i + n])


def _count_ngrams(titles: list[str], ns: tuple[int, ...] = (2, 3)) -> Counter[str]:
    c: Counter[str] = Counter()
    for t in titles:
        toks = _tokenize(t)
        for n in ns:
            c.update(_ngrams(toks, n))
    return c


def compute_power_keywords(
    *,
    db_path: Path | None = None,
    theme_id: int,
    top_k: int = 25,
    min_count: int = 3,
    alpha: float = 0.5,
) -> list[dict]:
    """Returns top-k power n-grams for `theme_id`.

    Each entry: {ngram, z_score, outlier_count, baseline_count, lift}.
    Sorted by z_score desc.
    """
    settings = get_settings()
    db = db_path or settings.duckdb_path

    with duckdb.connect(str(db), read_only=True) as con:
        outlier_titles = [
            r[0] for r in con.execute(
                """
                SELECT v.title FROM videos v
                JOIN video_features f ON f.video_id = v.id
                JOIN outliers o ON o.video_id = v.id
                WHERE f.theme_id = ? AND o.percentile_in_channel >= 90
                  AND v.is_short = false
                """, [theme_id],
            ).fetchall()
        ]
        baseline_titles = [
            r[0] for r in con.execute(
                """
                SELECT v.title FROM videos v
                JOIN video_features f ON f.video_id = v.id
                LEFT JOIN outliers o ON o.video_id = v.id
                WHERE f.theme_id = ?
                  AND (o.percentile_in_channel IS NULL OR o.percentile_in_channel < 90)
                  AND v.is_short = false
                """, [theme_id],
            ).fetchall()
        ]

    if not outlier_titles or not baseline_titles:
        return []

    out_counts = _count_ngrams(outlier_titles)
    base_counts = _count_ngrams(baseline_titles)
    total_out = sum(out_counts.values())
    total_base = sum(base_counts.values())

    results = []
    for ngram, c_out in out_counts.items():
        if c_out < min_count:
            continue
        c_base = base_counts.get(ngram, 0)
        # Smoothed proportions.
        p_out = (c_out + alpha) / (total_out + alpha * 2)
        p_base = (c_base + alpha) / (total_base + alpha * 2)
        # Log-odds ratio with smoothed variance.
        try:
            log_odds_diff = (
                math.log(p_out / (1 - p_out))
                - math.log(p_base / (1 - p_base))
            )
            var = 1.0 / (c_out + alpha) + 1.0 / (c_base + alpha)
            z = log_odds_diff / math.sqrt(var)
        except (ValueError, ZeroDivisionError):
            continue
        lift = (c_out / max(total_out, 1)) / max(c_base / max(total_base, 1), 1e-9)
        results.append({
            "ngram": ngram,
            "z_score": float(z),
            "outlier_count": int(c_out),
            "baseline_count": int(c_base),
            "lift": float(lift),
        })

    results.sort(key=lambda r: r["z_score"], reverse=True)
    return results[:top_k]


def list_themes_with_outliers(
    *, db_path: Path | None = None, min_outliers: int = 5,
) -> list[dict]:
    """Lists theme_ids with at least min_outliers outliers (p>=90).

    Used by UI to populate the theme selector for the keyword endpoint.
    Each row: {theme_id, theme_label, outlier_count}.
    """
    settings = get_settings()
    db = db_path or settings.duckdb_path
    with duckdb.connect(str(db), read_only=True) as con:
        rows = con.execute(
            """
            SELECT f.theme_id, ANY_VALUE(f.theme_label) AS theme_label,
                   COUNT(*) AS outlier_count
            FROM video_features f
            JOIN outliers o ON o.video_id = f.video_id
            JOIN videos v ON v.id = f.video_id
            WHERE o.percentile_in_channel >= 90
              AND f.theme_id IS NOT NULL AND f.theme_id >= 0
              AND v.is_short = false
            GROUP BY f.theme_id
            HAVING COUNT(*) >= ?
            ORDER BY outlier_count DESC
            """, [min_outliers],
        ).fetchall()
    return [
        {"theme_id": int(r[0]), "theme_label": r[1], "outlier_count": int(r[2])}
        for r in rows
    ]
