"""Readability scoring de títulos via Fernández-Huerta (PT-BR adaptation).

Banerjee & Urminsky 2024 mostraram interação positiva entre emoção e
readability — título emocional + fácil de ler ganha força; emocional +
difícil perde. textstat.fernandez_huerta() é a versão PT-BR do Flesch
Reading Ease (range 0-100, maior = mais fácil).

Pure CPU, ~30s pra 22k títulos.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from jason.config import get_settings

logger = logging.getLogger(__name__)


def compute_readability(
    *,
    db_path: Path | None = None,
    channel_id: str | None = None,
    force: bool = False,
) -> dict[str, int]:
    """Compute and persist `flesch_reading_ease` (Fernández-Huerta) for titles.

    Range: roughly 0-100. Higher = easier. Negative or >100 possible for
    weird titles (very short or all-caps). textstat handles edge cases.
    """
    import textstat  # noqa: PLC0415

    settings = get_settings()
    db = db_path or settings.duckdb_path

    # Configure textstat language to PT (uses fernandez_huerta).
    textstat.set_lang("pt_BR")

    with duckdb.connect(str(db)) as con:
        sql = ["SELECT v.id, v.title FROM videos v"]
        sql.append("LEFT JOIN video_features f ON f.video_id = v.id")
        if force:
            sql.append("WHERE 1=1")
        else:
            sql.append("WHERE (f.video_id IS NULL OR f.flesch_reading_ease IS NULL)")
        params: list = []
        if channel_id:
            sql.append("AND v.channel_id = ?")
            params.append(channel_id)
        pending = con.execute(" ".join(sql), params).fetchall()

        if not pending:
            return {"requested": 0, "computed": 0}

        # Ensure video_features row exists.
        ids = [r[0] for r in pending]
        placeholders = ",".join(["(?)"] * len(ids))
        con.execute(
            f"""
            INSERT INTO video_features (video_id)
            SELECT v.id FROM (VALUES {placeholders}) AS v(id)
            WHERE v.id NOT IN (SELECT video_id FROM video_features)
            """,
            ids,
        )

        computed = 0
        for vid, title in pending:
            try:
                score = float(textstat.fernandez_huerta(title or ""))
            except Exception:  # noqa: BLE001
                # textstat throws on weird inputs (empty, single char, etc.)
                score = 0.0
            con.execute(
                "UPDATE video_features SET flesch_reading_ease = ?, computed_at = now() "
                "WHERE video_id = ?",
                [score, vid],
            )
            computed += 1

    logger.info("readability: %d computed", computed)
    return {"requested": len(pending), "computed": computed}
