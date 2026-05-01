"""Sugere quais subgêneros valem a pena cobrir agora.

Combina 4 sinais:

1. tmdb_upcoming  : releases de horror nos próximos N dias batendo o tema
                    (matching por keyword no título do release vs theme_label).
2. theme_momentum : delta de p>=90 nos últimos 30 dias vs 30-60 dias
                    anteriores — tema esquentando ou esfriando.
3. neighbor_consensus : quantos canais vizinhos diferentes bateram p>=90
                    nesse tema nas últimas 8 semanas.
4. coverage_gap   : 1 se o canal próprio nunca bateu p>=90 nesse tema.

Score final é soma normalizada (cada sinal em [0, 1]). Output:
ranking de temas com scores individuais expostos pra UI explicar.
"""

from __future__ import annotations

import math
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from jason.config import get_settings


def _ascii_fold(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s.lower())
        if unicodedata.category(c) != "Mn"
    )


def _theme_keywords(label: str | None) -> set[str]:
    """Extract searchable keywords from a BERTopic theme label.

    Labels look like '4_terror_pesadelo_assustador_um' — drop the topic id,
    drop generic horror filler, keep specific words.
    """
    if not label:
        return set()
    parts = _ascii_fold(label).split("_")
    if parts and parts[0].isdigit():
        parts = parts[1:]
    generic = {
        "terror", "horror", "filme", "filmes", "que", "um", "uma", "de",
        "da", "do", "para", "com", "como", "este", "essa", "esse", "isto",
        "cinema",
    }
    return {p for p in parts if len(p) >= 4 and p not in generic}


def _tmdb_upcoming_score(
    con: duckdb.DuckDBPyConnection, *, theme_keywords: set[str], horizon_days: int,
) -> tuple[float, list[str]]:
    """Returns (score in [0, 1], list of matching release titles)."""
    if not theme_keywords:
        return 0.0, []
    today = datetime.now().date()
    horizon = today + timedelta(days=horizon_days)
    rows = con.execute(
        """
        SELECT title, release_date FROM horror_releases
        WHERE release_date >= ? AND release_date <= ?
        """,
        [today, horizon],
    ).fetchall()
    matches = []
    for title, _date in rows:
        folded = _ascii_fold(title)
        if any(kw in folded for kw in theme_keywords):
            matches.append(title)
    if not matches:
        return 0.0, []
    # Diminishing returns: 1 match = 0.4, 2 = 0.65, 3+ = 0.85
    score = min(1.0, 0.4 + math.log(1 + len(matches)) * 0.25)
    return score, matches[:5]


def _theme_momentum_score(
    con: duckdb.DuckDBPyConnection, *, theme_id: int,
) -> tuple[float, dict[str, int]]:
    """Compares p>=90 count last 30d vs 30-60d ago.

    Score = clip((recent - prior) / max(prior, 1), -1, 1) → [-1, 1] → mapped
    to [0, 1] by max(0, x). Negative momentum (esfriando) gets 0.
    """
    today = datetime.now().date()
    recent_start = today - timedelta(days=30)
    prior_start = today - timedelta(days=60)
    recent = con.execute(
        """
        SELECT COUNT(*) FROM videos v
        JOIN video_features f ON f.video_id = v.id
        JOIN outliers o ON o.video_id = v.id
        WHERE f.theme_id = ? AND o.percentile_in_channel >= 90
          AND v.published_at >= ?
        """, [theme_id, recent_start],
    ).fetchone()[0]
    prior = con.execute(
        """
        SELECT COUNT(*) FROM videos v
        JOIN video_features f ON f.video_id = v.id
        JOIN outliers o ON o.video_id = v.id
        WHERE f.theme_id = ? AND o.percentile_in_channel >= 90
          AND v.published_at >= ? AND v.published_at < ?
        """, [theme_id, prior_start, recent_start],
    ).fetchone()[0]
    if prior == 0 and recent == 0:
        return 0.0, {"recent": 0, "prior": 0}
    if prior == 0:
        return 0.7, {"recent": recent, "prior": 0}
    delta = (recent - prior) / max(prior, 1)
    return max(0.0, min(1.0, delta)), {"recent": int(recent), "prior": int(prior)}


def _neighbor_consensus_score(
    con: duckdb.DuckDBPyConnection,
    *,
    theme_id: int,
    own_channel_id: str,
    weeks: int = 8,
) -> tuple[float, int]:
    """How many distinct neighbor channels hit p>=90 in this theme recently."""
    since = datetime.now().date() - timedelta(weeks=weeks)
    n = con.execute(
        """
        SELECT COUNT(DISTINCT v.channel_id) FROM videos v
        JOIN video_features f ON f.video_id = v.id
        JOIN outliers o ON o.video_id = v.id
        WHERE f.theme_id = ? AND o.percentile_in_channel >= 90
          AND v.published_at >= ? AND v.channel_id != ?
        """, [theme_id, since, own_channel_id],
    ).fetchone()[0] or 0
    # Saturating: 1 neighbor = 0.4, 2 = 0.6, 3 = 0.75, 5+ = 0.9, 8+ = 1.0
    score = min(1.0, math.log(1 + n) / math.log(9))
    return float(score), int(n)


def _coverage_gap_score(
    con: duckdb.DuckDBPyConnection, *, theme_id: int, own_channel_id: str,
) -> float:
    """1.0 if own channel has 0 outliers in this theme; 0 otherwise."""
    n = con.execute(
        """
        SELECT COUNT(*) FROM videos v
        JOIN video_features f ON f.video_id = v.id
        JOIN outliers o ON o.video_id = v.id
        WHERE f.theme_id = ? AND o.percentile_in_channel >= 90
          AND v.channel_id = ?
        """, [theme_id, own_channel_id],
    ).fetchone()[0] or 0
    return 1.0 if n == 0 else 0.0


def suggest_themes(
    *,
    db_path: Path | None = None,
    own_channel_id: str | None = None,
    horizon_days: int = 60,
    min_neighbor_outliers: int = 3,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Ranks themes by combined score.

    Returns one dict per theme: theme_id, label, label_human, scores
    (per-signal), score_total, evidence (matches + counts).
    """
    settings = get_settings()
    db = db_path or settings.duckdb_path
    own = own_channel_id or settings.own_channel_id
    if not own:
        raise ValueError("own_channel_id not configured")

    with duckdb.connect(str(db), read_only=True) as con:
        themes = con.execute(
            """
            SELECT f.theme_id, ANY_VALUE(f.theme_label) AS label,
                   COUNT(*) AS n_total
            FROM video_features f
            JOIN videos v ON v.id = f.video_id
            JOIN outliers o ON o.video_id = v.id
            WHERE v.is_short = false AND o.percentile_in_channel >= 90
              AND f.theme_id IS NOT NULL AND f.theme_id >= 0
              AND v.channel_id != ?
            GROUP BY f.theme_id
            HAVING COUNT(*) >= ?
            """, [own, min_neighbor_outliers],
        ).fetchall()

        results = []
        for theme_id, label, _n_total in themes:
            kws = _theme_keywords(label)
            tmdb_score, matches = _tmdb_upcoming_score(
                con, theme_keywords=kws, horizon_days=horizon_days,
            )
            momentum, mc = _theme_momentum_score(con, theme_id=int(theme_id))
            consensus, n_neighbors = _neighbor_consensus_score(
                con, theme_id=int(theme_id), own_channel_id=own,
            )
            gap = _coverage_gap_score(
                con, theme_id=int(theme_id), own_channel_id=own,
            )
            # Weighted sum. Coverage gap is binary multiplier on consensus
            # so "everyone is doing it AND I'm not" gets the loudest score.
            total = (
                0.30 * tmdb_score
                + 0.25 * momentum
                + 0.30 * consensus
                + 0.15 * gap
            )
            results.append({
                "theme_id": int(theme_id),
                "label": label,
                "scores": {
                    "tmdb_upcoming": float(tmdb_score),
                    "momentum": float(momentum),
                    "neighbor_consensus": float(consensus),
                    "coverage_gap": float(gap),
                },
                "evidence": {
                    "tmdb_titles": matches,
                    "momentum_counts": mc,
                    "n_neighbors_recent": n_neighbors,
                    "own_has_p90_in_theme": gap == 0.0,
                },
                "score_total": float(total),
            })

    results.sort(key=lambda r: r["score_total"], reverse=True)
    return results[:top_k]
