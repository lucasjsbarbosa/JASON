"""Suggest text-overlay style for the thumbnail, declaratively.

Per CLAUDE.md Fase 4.5: "Output é declarativo, não imagem renderizada — exemplo:
    {"text_present": true, "text_position": "top_left", "text_color": "yellow",
     "max_words": 3, "examples": ["EXPLICADO", "FINAL", "PERTURBADOR"]}"

V1 picks examples from the most-niche-flagged outlier titles in the same theme.
A future version could OCR actual outlier thumbnails to recover real overlay
patterns (color/position) — for now we ship a sensible heuristic default.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from jason.config import get_settings


def suggest_overlay(
    *,
    theme_id: int | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Suggest a text overlay style (declarative) for a new thumbnail."""
    settings = get_settings()
    db = db_path or settings.duckdb_path

    sql = """
        SELECT v.title
        FROM videos v
        JOIN video_features f ON f.video_id = v.id
        JOIN outliers o ON o.video_id = v.id
        WHERE o.percentile_in_channel >= 90 AND v.is_short = false
    """
    params: list[Any] = []
    if theme_id is not None:
        sql += " AND f.theme_id = ?"
        params.append(theme_id)
    sql += " ORDER BY o.multiplier DESC LIMIT 30"

    with duckdb.connect(str(db), read_only=True) as con:
        rows = con.execute(sql, params).fetchall()

    # Tokens we consider "good overlay candidates" — short, punchy, CAPS in the source
    keyword_pool = (
        "EXPLICADO", "FINAL", "PERTURBADOR", "INSANO", "ABSURDO", "CHOCANTE",
        "TOP", "MELHORES", "PIORES", "SECRETO", "PROIBIDO",
    )

    examples: list[str] = []
    seen: set[str] = set()
    for (title,) in rows:
        upper = title.upper()
        for kw in keyword_pool:
            if kw in upper and kw not in seen:
                examples.append(kw)
                seen.add(kw)
        if len(examples) >= 5:
            break

    if not examples:
        examples = ["EXPLICADO", "FINAL", "PERTURBADOR"]  # fallback

    return {
        "text_present": True,
        "text_position": "top_left",
        "text_color": "yellow",
        "max_words": 3,
        "examples": examples[:5],
        "note": "Edite a thumb final no Photoshop/Canva — JASON sugere padrão; não renderiza imagem.",
    }
