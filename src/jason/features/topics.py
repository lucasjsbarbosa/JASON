"""Two-layer topic modeling.

Layer A (theme): titles with proper names masked to `[FILME]` so the model
clusters by *theme* (possession, slasher, found footage, ranking, "explained"
format, etc.) rather than by which movie a title mentions. The mask source is
`horror_releases` (TMDb-fed) plus a hardcoded shortlist of evergreen horror
franchises that pre-date the TMDb window.

Layer B (franchise): raw titles → BERTopic surfaces clusters around the
franchises that go viral (Invocação do Mal, Sobrenatural, Hereditário, etc.).

Both layers persist `topic_id` + `topic_label` on `video_features`; topic_id
== -1 is BERTopic's "outlier" / unassigned bucket.

The `BERTopic` class is dependency-injected as `model_factory()` so the test
suite doesn't pull in `bertopic` (which transitively requires umap, hdbscan,
torch, etc.). The default factory lazy-imports it.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import duckdb

from jason.config import get_settings

logger = logging.getLogger(__name__)


class _BERTopicLike(Protocol):
    """Subset of the BERTopic surface we depend on."""
    def fit_transform(self, documents: list[str]) -> tuple[list[int], Any]: ...
    def get_topic_info(self) -> Any: ...


ModelFactory = Callable[[], _BERTopicLike]


# Evergreen horror franchises / character names that don't show up in TMDb's
# 18-month release window but appear constantly in title packaging. Used by
# the proper-name mask. Lowercased for case-insensitive substring matching
# after accent stripping.
_EVERGREEN_PROPER_NAMES: tuple[str, ...] = (
    # slasher icons
    "jason", "voorhees", "freddy", "krueger", "michael myers", "leatherface",
    "ghostface", "chucky", "pennywise", "pinhead",
    # franchise titles
    "halloween", "sexta-feira 13", "panico", "scream", "hereditario",
    "sobrenatural", "invocacao do mal", "annabelle", "exorcista", "iluminado",
    "shining", "alien", "predador", "midsommar", "babadook", "saw", "jogos mortais",
    "atividade paranormal", "the ring", "o chamado", "grito", "ju-on",
    "drag me to hell", "evil dead", "morte do demonio", "candyman", "carrie",
    # recent
    "talk to me", "smile", "the substance", "longlegs", "barbarian", "x",
    "pearl", "maxxxine", "weapons", "m3gan",
)


def _strip_accents(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in nfd if not unicodedata.combining(c))


def _build_mask_patterns(extra_titles: list[str]) -> list[re.Pattern[str]]:
    """Compile regexes that match each known proper name as a whole word.

    `extra_titles` is `horror_releases.title` from the DB — TMDb-fed,
    accent-folded, deduped at call site.
    """
    seen: set[str] = set()
    patterns: list[re.Pattern[str]] = []
    raw_names: list[str] = list(_EVERGREEN_PROPER_NAMES) + extra_titles
    # Sort longer-first so "Sexta-feira 13" matches before "Sexta" if "Sexta"
    # ever appears alone in the corpus.
    raw_names.sort(key=len, reverse=True)
    for name in raw_names:
        norm = _strip_accents(name).strip()
        if not norm or norm in seen or len(norm) < 4:
            continue
        seen.add(norm)
        patterns.append(re.compile(rf"\b{re.escape(norm)}\b", re.IGNORECASE))
    return patterns


def _mask_proper_names(title: str, patterns: list[re.Pattern[str]]) -> str:
    """Replace each proper-name match in `title` with `[FILME]`."""
    folded = _strip_accents(title)
    for pat in patterns:
        folded = pat.sub("[FILME]", folded)
    # Collapse runs of `[FILME]` placeholders (avoid "[FILME] [FILME] [FILME]").
    # Match the inner repeats only so leading/trailing whitespace is preserved.
    folded = re.sub(r"\[FILME\](\s+\[FILME\])+", "[FILME]", folded)
    return folded


# --- Default model factory -------------------------------------------------


def _default_model_factory() -> _BERTopicLike:
    """Lazy import. Calibrated for ~5k–25k titles, PT-BR."""
    from bertopic import BERTopic  # noqa: PLC0415
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    embedder = SentenceTransformer("paraphrase-multilingual-mpnet-base-v2")
    return BERTopic(
        embedding_model=embedder,
        language="multilingual",
        min_topic_size=20,           # >= 20 titles per topic, else dropped to -1
        verbose=False,
    )


# --- Persistence helpers ---------------------------------------------------


def _ensure_features_row(con: duckdb.DuckDBPyConnection, video_ids: list[str]) -> None:
    if not video_ids:
        return
    placeholders = ",".join(["(?)"] * len(video_ids))
    con.execute(
        f"""
        INSERT INTO video_features (video_id)
        SELECT v.id FROM (VALUES {placeholders}) AS v(id)
        WHERE v.id NOT IN (SELECT video_id FROM video_features)
        """,
        video_ids,
    )


def _label_for(topic_id: int, topic_info: Any) -> str | None:
    """Pull a 'Name' column from BERTopic.get_topic_info() for `topic_id`.

    BERTopic returns a pandas DataFrame with columns Topic, Count, Name.
    We coerce defensively because the test fakes return a plain dict.
    """
    if topic_id == -1:
        return None
    try:
        if hasattr(topic_info, "set_index"):
            return topic_info.set_index("Topic").loc[topic_id, "Name"]
        return topic_info.get(topic_id)  # dict-shaped fake
    except (KeyError, IndexError):
        return None


def _persist(
    con: duckdb.DuckDBPyConnection,
    video_ids: list[str],
    topics: list[int],
    topic_info: Any,
    *,
    layer: str,
) -> None:
    """Write topic assignments. `layer` is 'theme' or 'franchise'."""
    id_col = f"{layer}_id"
    label_col = f"{layer}_label"
    _ensure_features_row(con, video_ids)
    for vid, tid in zip(video_ids, topics, strict=True):
        label = _label_for(tid, topic_info)
        con.execute(
            f"UPDATE video_features SET {id_col} = ?, {label_col} = ?, computed_at = now() "
            "WHERE video_id = ?",
            [int(tid), label, vid],
        )


# --- Public functions ------------------------------------------------------


def fit_themes(
    *,
    db_path: Path | None = None,
    model_factory: ModelFactory | None = None,
) -> dict[str, int]:
    """Fit BERTopic on title-with-proper-names-masked → persists theme_id."""
    settings = get_settings()
    db = db_path or settings.duckdb_path

    with duckdb.connect(str(db)) as con:
        videos = con.execute(
            "SELECT id, title FROM videos WHERE is_short = false ORDER BY id"
        ).fetchall()
        if not videos:
            return {"requested": 0, "fit": 0, "topics": 0}

        # Build mask vocabulary from horror_releases (deduped) + evergreen list.
        release_titles = [
            r[0] for r in con.execute("SELECT DISTINCT title FROM horror_releases").fetchall()
        ]
        patterns = _build_mask_patterns(release_titles)

        ids = [v[0] for v in videos]
        masked = [_mask_proper_names(v[1] or "", patterns) for v in videos]

        model = (model_factory or _default_model_factory)()
        topics, _probs = model.fit_transform(masked)
        info = model.get_topic_info()

        _persist(con, ids, list(topics), info, layer="theme")

    n_topics = len({t for t in topics if t != -1})
    logger.info("themes: %d videos clustered into %d non-noise topics", len(videos), n_topics)
    return {"requested": len(videos), "fit": len(videos), "topics": n_topics}


def fit_franchises(
    *,
    db_path: Path | None = None,
    model_factory: ModelFactory | None = None,
) -> dict[str, int]:
    """Fit BERTopic on raw titles → persists franchise_id."""
    settings = get_settings()
    db = db_path or settings.duckdb_path

    with duckdb.connect(str(db)) as con:
        videos = con.execute(
            "SELECT id, title FROM videos WHERE is_short = false ORDER BY id"
        ).fetchall()
        if not videos:
            return {"requested": 0, "fit": 0, "topics": 0}

        ids = [v[0] for v in videos]
        titles = [v[1] or "" for v in videos]

        model = (model_factory or _default_model_factory)()
        topics, _probs = model.fit_transform(titles)
        info = model.get_topic_info()

        _persist(con, ids, list(topics), info, layer="franchise")

    n_topics = len({t for t in topics if t != -1})
    logger.info("franchises: %d videos clustered into %d non-noise topics", len(videos), n_topics)
    return {"requested": len(videos), "fit": len(videos), "topics": n_topics}
