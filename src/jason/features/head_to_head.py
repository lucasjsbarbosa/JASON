"""Compara o canal próprio vs um canal vizinho em packaging e temas.

Saída pra UI: numbers que respondem "o que esse canal faz que eu não
faço, e em que tema ele bate forte que eu não toquei?". Não é um juízo
absoluto — é uma diff de packaging.

Métricas:
- outlier_rate: % de vídeos elegíveis (long-form, com baseline) que
  caíram em p>=90 no próprio canal.
- median_views_at_28d: distribuição estabilizada (descarta vídeos com
  idade < 28d).
- packaging_use: por feature booleana, % dos vídeos do canal usando ela.
- top_themes: top-N temas por contagem de outliers do canal.
- coverage_gap: temas hot no vizinho ausentes no próprio canal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from jason.config import get_settings

_PACKAGING_FEATURES = (
    "has_explained_keyword",
    "has_ranking_keyword",
    "has_curiosity_keyword",
    "has_extreme_adjective",
    "has_caps_word",
    "has_number",
    "has_question_mark",
    "has_first_person",
)


def _channel_summary(con: duckdb.DuckDBPyConnection, channel_id: str) -> dict[str, Any]:
    base = con.execute(
        """
        SELECT c.id, c.title, c.handle, c.subs
        FROM channels c WHERE c.id = ?
        """, [channel_id],
    ).fetchone()
    if not base:
        return {}
    long_total = con.execute(
        """
        SELECT COUNT(*) FROM videos v
        WHERE v.channel_id = ? AND v.is_short = false
        """, [channel_id],
    ).fetchone()[0]

    eligible_with_outlier = con.execute(
        """
        SELECT COUNT(*) FROM videos v
        JOIN outliers o ON o.video_id = v.id
        WHERE v.channel_id = ? AND v.is_short = false
          AND o.percentile_in_channel IS NOT NULL
        """, [channel_id],
    ).fetchone()[0]

    p90_count = con.execute(
        """
        SELECT COUNT(*) FROM videos v
        JOIN outliers o ON o.video_id = v.id
        WHERE v.channel_id = ? AND v.is_short = false
          AND o.percentile_in_channel >= 90
        """, [channel_id],
    ).fetchone()[0]

    median_views = con.execute(
        """
        SELECT MEDIAN(s.views) FROM videos v
        JOIN video_stats_snapshots s ON s.video_id = v.id
        WHERE v.channel_id = ? AND v.is_short = false
          AND s.days_since_publish BETWEEN 25 AND 31
        """, [channel_id],
    ).fetchone()[0]

    return {
        "id": base[0],
        "title": base[1],
        "handle": base[2],
        "subs": int(base[3] or 0),
        "long_total": int(long_total),
        "outliers_p90": int(p90_count),
        "outlier_rate": (
            float(p90_count) / float(eligible_with_outlier)
            if eligible_with_outlier else None
        ),
        "median_views_at_28d": int(median_views) if median_views else None,
    }


def _packaging_use(
    con: duckdb.DuckDBPyConnection, channel_id: str,
) -> dict[str, float]:
    """Returns {feature: pct_of_long_videos_using_it}."""
    select_clauses = ", ".join(
        f"AVG(CAST(f.{c} AS INTEGER)) AS {c}" for c in _PACKAGING_FEATURES
    )
    row = con.execute(
        f"""
        SELECT {select_clauses} FROM videos v
        JOIN video_features f ON f.video_id = v.id
        WHERE v.channel_id = ? AND v.is_short = false
        """, [channel_id],
    ).fetchone()
    return {
        c: (float(v) if v is not None else 0.0)
        for c, v in zip(_PACKAGING_FEATURES, row, strict=True)
    }


def _top_themes(
    con: duckdb.DuckDBPyConnection, channel_id: str, *, limit: int = 8,
) -> list[dict[str, Any]]:
    """Top themes by outlier count for a channel."""
    rows = con.execute(
        """
        SELECT f.theme_id, ANY_VALUE(f.theme_label) AS label, COUNT(*) AS n
        FROM videos v
        JOIN video_features f ON f.video_id = v.id
        JOIN outliers o ON o.video_id = v.id
        WHERE v.channel_id = ? AND v.is_short = false
          AND o.percentile_in_channel >= 90
          AND f.theme_id IS NOT NULL AND f.theme_id >= 0
        GROUP BY f.theme_id
        ORDER BY n DESC
        LIMIT ?
        """, [channel_id, limit],
    ).fetchall()
    return [
        {"theme_id": int(r[0]), "label": r[1], "outlier_count": int(r[2])}
        for r in rows
    ]


def head_to_head(
    *, db_path: Path | None = None, own_channel_id: str, neighbor_channel_id: str,
) -> dict[str, Any]:
    """Compare two channels side-by-side. own = canal próprio."""
    settings = get_settings()
    db = db_path or settings.duckdb_path

    with duckdb.connect(str(db), read_only=True) as con:
        own = _channel_summary(con, own_channel_id)
        nb = _channel_summary(con, neighbor_channel_id)
        if not own or not nb:
            return {"error": "channel not found"}
        own_pkg = _packaging_use(con, own_channel_id)
        nb_pkg = _packaging_use(con, neighbor_channel_id)
        own_themes = _top_themes(con, own_channel_id)
        nb_themes = _top_themes(con, neighbor_channel_id)

    own_theme_ids = {t["theme_id"] for t in own_themes}
    coverage_gap = [
        t for t in nb_themes if t["theme_id"] not in own_theme_ids
    ]

    pkg_diff = []
    for feat in _PACKAGING_FEATURES:
        pkg_diff.append({
            "feature": feat,
            "own_pct": own_pkg[feat],
            "neighbor_pct": nb_pkg[feat],
            "delta": nb_pkg[feat] - own_pkg[feat],
        })
    pkg_diff.sort(key=lambda r: abs(r["delta"]), reverse=True)

    return {
        "own": own,
        "neighbor": nb,
        "packaging_diff": pkg_diff,
        "own_themes": own_themes,
        "neighbor_themes": nb_themes,
        "coverage_gap": coverage_gap,
    }
