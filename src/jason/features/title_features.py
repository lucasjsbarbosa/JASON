"""Title-level features for the multiplier regressor (Fase 3 input).

These run cheap and locally — no external models, no API calls. Per CLAUDE.md
the niche-specific flags (`has_explained_keyword`, etc.) are deliberately
included here because horror-PT-BR titles overload them as packaging signals
("EXPLICADO", "Top 10 piores...", "Você NÃO sabia que..."). Filtering them out
as boilerplate would erase the actual signal of the niche.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

import duckdb

from jason.config import get_settings

logger = logging.getLogger(__name__)

# --- Regex bank --------------------------------------------------------------

_NUMBER_RE = re.compile(r"\d")

# Most common emoji blocks. Not exhaustive (Unicode adds new ones each year),
# but covers ~99% of what shows up in YouTube titles.
_EMOJI_RE = re.compile(
    "["
    "\U0001f600-\U0001f64f"   # emoticons
    "\U0001f300-\U0001f5ff"   # symbols & pictographs
    "\U0001f680-\U0001f6ff"   # transport & map
    "\U0001f700-\U0001f77f"   # alchemical
    "\U0001f900-\U0001f9ff"   # supplemental symbols & pictographs
    "\U0001fa00-\U0001fa6f"   # chess symbols, drawings
    "\U0001fa70-\U0001faff"
    "\U00002600-\U000026ff"   # misc symbols
    "\U00002700-\U000027bf"   # dingbats
    "]"
)

# Caps word: a token with 3+ consecutive uppercase letters (Latin + accented).
# Matches "EXPLICADO", "JASON", "PERTURBADORA". Avoids 2-letter trivial caps.
_CAPS_WORD_RE = re.compile(r"[A-ZÀ-Ý]{3,}")

# First-person pronouns/possessives in PT-BR. \b doesn't quite work for accented
# chars in some Python regex engines — use lookarounds on word boundaries.
_FIRST_PERSON_RE = re.compile(
    r"(?:^|(?<=\W))(eu|meu|meus|minha|minhas|nós|nosso|nossa|nossos|nossas)(?=\W|$)",
    re.IGNORECASE,
)

# Niche keywords. Match against an accent-stripped + lowercased version of the
# title so "EXPLICADA", "explicado", and "Explicação" all hit.
_EXPLAINED_RE = re.compile(
    r"\b(explicad[oa]s?|final[\s-]explicad[oa]|entenda|explicacao|explicacoes)\b"
)
_RANKING_RE = re.compile(
    r"\b(top[\s-]?\d*|melhores|piores|ranking)\b"
)
_CURIOSITY_RE = re.compile(
    r"(voce nao sabia|ninguem fala|verdade por tras|por que|porque ninguem|nunca te contaram)"
)
_EXTREME_ADJ_RE = re.compile(
    r"\b("
    r"perturbador[ae]?s?|"
    r"insano[ae]?s?|"
    r"absurdo[ae]?s?|"
    r"chocante[s]?|"
    r"aterrorizante[s]?|"
    r"brutal|"
    r"psicopata[s]?|"
    r"horripilante[s]?|"
    r"macabro[ae]?s?|"
    r"sinistro[ae]?s?"
    r")\b"
)

# Definite referring expressions (Loewenstein curiosity gap signature).
# "este filme", "essa cena", "aquele momento" — sinaliza referência sem
# antecedente claro, premia o clique.
_DEFINITE_REF_RE = re.compile(
    r"\b(este|esse|aquele|aquela|essa|esta|isto|isso|aquilo|esses|essas|aqueles|aquelas)\b",
    re.IGNORECASE,
)

# Forward-referencing pronouns (cataphora). PT-BR tem pronoun-drop, então
# isso é mais ruidoso que em inglês — mas pronome explícito antes do
# antecedente ainda é sinal de clickbait. Match em pronomes 3a pessoa.
_FORWARD_REF_RE = re.compile(
    r"\b(ele|ela|eles|elas)\b",
    re.IGNORECASE,
)

# Superlatives + intensifiers: "MAIS X", "MELHOR/PIOR", "demais", "muito".
# Densidade alta dessas palavras é um marcador de clickbait/curiosity gap
# por Banerjee & Urminsky.
_SUPERLATIVE_RE = re.compile(
    r"\b(mais|menos|demais|muito|maior|menor|melhor|pior|extremamente|"
    r"absurdamente|incrivelmente|completamente|totalmente)\b",
    re.IGNORECASE,
)


def _strip_accents(text: str) -> str:
    """Lowercased + NFD-decomposed + stripped of combining marks. PT-friendly."""
    nfd = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in nfd if not unicodedata.combining(c))


# --- Feature extraction ------------------------------------------------------


def extract_features(title: str) -> dict[str, Any]:
    """Compute all title-level features for a single string.

    Returns a dict matching the columns of `video_features` (minus video_id,
    sentiment_score, computed_at). Pure function — no IO.
    """
    title = title or ""
    char_len = len(title)
    normalized = _strip_accents(title)
    upper_count = sum(1 for c in title if c.isupper())

    # Word-level metrics (paper-backed: clickbait detection +25pp accuracy
    # going from binary to gradient features).
    words = title.split()
    word_count = len(words)
    word_lengths = [len(w) for w in words] if words else [0]
    avg_word_length = sum(word_lengths) / len(word_lengths)

    # Curiosity-gap signatures (Loewenstein 1994; Chakraborty et al. 2016).
    definite_refs = len(_DEFINITE_REF_RE.findall(title))
    forward_refs = len(_FORWARD_REF_RE.findall(title))
    superlatives = len(_SUPERLATIVE_RE.findall(title))

    # Density: per word so longer titles don't auto-win.
    superlative_density = (superlatives / word_count) if word_count else 0.0

    return {
        "char_len": char_len,
        "word_count": word_count,
        "avg_word_length": avg_word_length,
        "has_number": bool(_NUMBER_RE.search(title)),
        "has_emoji": bool(_EMOJI_RE.search(title)),
        "has_question_mark": "?" in title,
        "has_caps_word": bool(_CAPS_WORD_RE.search(title)),
        "caps_ratio": (upper_count / char_len) if char_len else 0.0,
        "has_first_person": bool(_FIRST_PERSON_RE.search(title)),
        "has_explained_keyword": bool(_EXPLAINED_RE.search(normalized)),
        "has_ranking_keyword": bool(_RANKING_RE.search(normalized)),
        "has_curiosity_keyword": bool(_CURIOSITY_RE.search(normalized)),
        "has_extreme_adjective": bool(_EXTREME_ADJ_RE.search(normalized)),
        "definite_ref_count": definite_refs,
        "forward_ref_count": forward_refs,
        "superlative_density": superlative_density,
    }


# --- Batch + persistence -----------------------------------------------------


_FEATURE_COLUMNS = (
    "char_len", "word_count", "avg_word_length",
    "has_number", "has_emoji", "has_question_mark",
    "has_caps_word", "caps_ratio", "has_first_person",
    "has_explained_keyword", "has_ranking_keyword",
    "has_curiosity_keyword", "has_extreme_adjective",
    "definite_ref_count", "forward_ref_count", "superlative_density",
)


def _read_pending(
    con: duckdb.DuckDBPyConnection, *, channel_id: str | None, force: bool
) -> list[tuple[str, str]]:
    """Return (video_id, title) pairs needing feature computation."""
    sql_parts = ["SELECT v.id, v.title FROM videos v"]
    params: list[Any] = []
    if not force:
        sql_parts.append("LEFT JOIN video_features f ON f.video_id = v.id")
        sql_parts.append("WHERE f.video_id IS NULL")
    else:
        sql_parts.append("WHERE 1=1")
    if channel_id:
        sql_parts.append("AND v.channel_id = ?")
        params.append(channel_id)
    return con.execute(" ".join(sql_parts), params).fetchall()


def compute_title_features(
    *,
    db_path: Path | None = None,
    channel_id: str | None = None,
    force: bool = False,
) -> dict[str, int]:
    """Compute and persist title features for every (or one channel's) video.

    Args:
        db_path: optional DuckDB override.
        channel_id: optional UC... filter.
        force: re-compute features even for videos that already have a row.

    Returns:
        dict with `requested`, `computed` counts.
    """
    settings = get_settings()
    db = db_path or settings.duckdb_path

    with duckdb.connect(str(db)) as con:
        pending = _read_pending(con, channel_id=channel_id, force=force)
        if not pending:
            return {"requested": 0, "computed": 0}

        cols = ", ".join(("video_id", *_FEATURE_COLUMNS))
        placeholders = ", ".join(["?"] * (len(_FEATURE_COLUMNS) + 1))
        update_cols = ", ".join(f"{c} = EXCLUDED.{c}" for c in _FEATURE_COLUMNS)

        for vid, title in pending:
            feats = extract_features(title)
            con.execute(
                f"""
                INSERT INTO video_features ({cols})
                VALUES ({placeholders})
                ON CONFLICT (video_id) DO UPDATE SET
                    {update_cols},
                    computed_at = now()
                """,
                [vid, *(feats[c] for c in _FEATURE_COLUMNS)],
            )

    logger.info("title features computed for %d videos", len(pending))
    return {"requested": len(pending), "computed": len(pending)}
