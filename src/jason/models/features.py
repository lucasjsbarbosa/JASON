"""Assemble the feature matrix the LightGBM regressor consumes.

Reads the live state of the DB and returns a pandas DataFrame keyed by
video_id. Long-form only — Shorts have a different distribution per
CLAUDE.md and are filtered out. Optionally filters to videos that already
have a multiplier (training mode) or returns all (scoring mode).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from jason.config import get_settings
from jason.models.buckets import bucket_of

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

# Title-feature columns we hand directly to LightGBM (boolean → 0/1, numeric as-is).
TITLE_FEATURE_COLS = (
    "char_len", "word_count", "avg_word_length", "caps_ratio",
    "has_number", "has_emoji", "has_question_mark", "has_caps_word",
    "has_first_person",
    "has_explained_keyword", "has_ranking_keyword",
    "has_curiosity_keyword", "has_extreme_adjective",
    "definite_ref_count", "forward_ref_count", "superlative_density",
    "sentiment_score", "arousal_score", "flesch_reading_ease",
)

THUMB_FEATURE_COLS = (
    "thumb_brightness", "thumb_contrast", "thumb_colorfulness",
    "thumb_face_largest_pct",
)

# Categorical features (LightGBM handles natively as `category` dtype).
CATEGORICAL_COLS = ("subs_bucket", "theme_id", "franchise_id", "published_dow")

# Final feature list the model trains/predicts on (k-means cluster columns
# get added at training time and persisted with the artifact).
SCALAR_FEATURE_COLS = (
    *TITLE_FEATURE_COLS,
    *THUMB_FEATURE_COLS,
    "duration_s", "published_hour", "days_to_nearest_horror_release",
    "is_halloween_week", "is_friday_13_week",
)


def _annotate_calendar(df: pd.DataFrame) -> pd.DataFrame:
    """Add published_hour, published_dow, is_halloween_week, is_friday_13_week."""
    import pandas as pd  # noqa: PLC0415

    pub = pd.to_datetime(df["published_at"], utc=True)
    df["published_hour"] = pub.dt.hour
    df["published_dow"] = pub.dt.dayofweek

    is_late_oct = (pub.dt.month == 10) & (pub.dt.day >= 25)
    is_early_nov = (pub.dt.month == 11) & (pub.dt.day <= 1)
    df["is_halloween_week"] = (is_late_oct | is_early_nov).astype(int)

    df["is_friday_13_week"] = ((pub.dt.dayofweek == 4) & (pub.dt.day == 13)).astype(int)
    return df


def _annotate_horror_distance(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> pd.DataFrame:
    """For each video, compute |days| to the nearest horror release."""
    import numpy as np  # noqa: PLC0415
    import pandas as pd  # noqa: PLC0415

    horror = con.execute("SELECT release_date FROM horror_releases").df()
    if horror.empty:
        df["days_to_nearest_horror_release"] = -1
        return df

    rel = pd.to_datetime(horror["release_date"]).values.astype("datetime64[D]")
    pub = pd.to_datetime(df["published_at"]).values.astype("datetime64[D]")

    rel_sorted = np.sort(rel)
    # For each pub, binary-search the closest release on either side
    idx = np.searchsorted(rel_sorted, pub)
    candidates_left = rel_sorted[np.clip(idx - 1, 0, len(rel_sorted) - 1)]
    candidates_right = rel_sorted[np.clip(idx, 0, len(rel_sorted) - 1)]
    diff_left = np.abs((pub - candidates_left).astype(int))
    diff_right = np.abs((pub - candidates_right).astype(int))
    df["days_to_nearest_horror_release"] = np.minimum(diff_left, diff_right)
    return df


def build_feature_matrix(
    *,
    db_path: Path | None = None,
    only_with_multiplier: bool = True,
    channel_id: str | None = None,
) -> pd.DataFrame:
    """Pull every long-form video with its full feature row.

    Args:
        only_with_multiplier: keep only videos with `outliers.multiplier IS NOT NULL`.
            Use True for training, False for scoring/inference.
        channel_id: optional UC... filter.

    Returns:
        pandas DataFrame indexed by video_id with all SCALAR_FEATURE_COLS,
        CATEGORICAL_COLS, optional `multiplier` target, plus raw embeddings
        in `title_embedding` / `thumb_embedding` columns (None when missing).
    """
    settings = get_settings()
    db = db_path or settings.duckdb_path

    sql = """
        SELECT v.id, v.channel_id, v.published_at, v.duration_s,
               c.subs,
               f.char_len, f.word_count, f.caps_ratio,
               COALESCE(f.avg_word_length, 0.0)         AS avg_word_length,
               COALESCE(f.definite_ref_count, 0)        AS definite_ref_count,
               COALESCE(f.forward_ref_count, 0)         AS forward_ref_count,
               COALESCE(f.superlative_density, 0.0)     AS superlative_density,
               COALESCE(f.arousal_score, 0.5)           AS arousal_score,
               COALESCE(f.flesch_reading_ease, 50.0)    AS flesch_reading_ease,
               COALESCE(f.thumb_brightness, 128.0)      AS thumb_brightness,
               COALESCE(f.thumb_contrast, 50.0)         AS thumb_contrast,
               COALESCE(f.thumb_colorfulness, 30.0)     AS thumb_colorfulness,
               COALESCE(f.thumb_face_largest_pct, 0.0)  AS thumb_face_largest_pct,
               CAST(f.has_number AS INTEGER)            AS has_number,
               CAST(f.has_emoji AS INTEGER)             AS has_emoji,
               CAST(f.has_question_mark AS INTEGER)     AS has_question_mark,
               CAST(f.has_caps_word AS INTEGER)         AS has_caps_word,
               CAST(f.has_first_person AS INTEGER)      AS has_first_person,
               CAST(f.has_explained_keyword AS INTEGER) AS has_explained_keyword,
               CAST(f.has_ranking_keyword AS INTEGER)   AS has_ranking_keyword,
               CAST(f.has_curiosity_keyword AS INTEGER) AS has_curiosity_keyword,
               CAST(f.has_extreme_adjective AS INTEGER) AS has_extreme_adjective,
               COALESCE(f.sentiment_score, 0.0)         AS sentiment_score,
               COALESCE(f.theme_id, -1)     AS theme_id,
               COALESCE(f.franchise_id, -1) AS franchise_id,
               f.title_embedding,
               f.thumb_embedding,
               o.multiplier
        FROM videos v
        JOIN channels c ON c.id = v.channel_id
        JOIN video_features f ON f.video_id = v.id
        LEFT JOIN outliers o ON o.video_id = v.id
        WHERE v.is_short = false
    """
    params: list[Any] = []
    if only_with_multiplier:
        sql += " AND o.multiplier IS NOT NULL"
    if channel_id:
        sql += " AND v.channel_id = ?"
        params.append(channel_id)

    with duckdb.connect(str(db), read_only=True) as con:
        df = con.execute(sql, params).df()
        df["subs_bucket"] = df["subs"].apply(bucket_of).astype(int)
        df = _annotate_calendar(df)
        df = _annotate_horror_distance(con, df)

    df = df.set_index("id")
    return df


def assemble_score_row(
    *,
    title: str,
    channel_id: str,
    published_at: datetime,
    duration_s: int,
    theme_id: int = -1,
    franchise_id: int = -1,
    title_embedding: list[float] | None = None,
    thumb_embedding: list[float] | None = None,
    db_path: Path | None = None,
) -> pd.DataFrame:
    """Build a single-row feature DataFrame for scoring a hypothetical title.

    Used by `predict.score_title` to wrap one candidate into the same shape
    `build_feature_matrix` produces.
    """
    import pandas as pd  # noqa: PLC0415

    from jason.features.title_features import extract_features  # noqa: PLC0415

    settings = get_settings()
    db = db_path or settings.duckdb_path

    with duckdb.connect(str(db), read_only=True) as con:
        subs_row = con.execute("SELECT subs FROM channels WHERE id = ?", [channel_id]).fetchone()
    subs = subs_row[0] if subs_row else 0

    feats = extract_features(title)
    row: dict[str, Any] = {
        "channel_id": channel_id,
        "published_at": published_at,
        "duration_s": duration_s,
        "subs": subs,
        **{c: feats[c] for c in TITLE_FEATURE_COLS if c in feats},
        # Defaults for features that need heavy compute (transformer / image
        # processing). Production scoring of a candidate doesn't run these
        # on-the-fly; the model receives mid-distribution defaults.
        "sentiment_score": feats.get("sentiment_score", 0.0),
        "arousal_score": feats.get("arousal_score", 0.5),
        "flesch_reading_ease": feats.get("flesch_reading_ease", 50.0),
        "thumb_brightness": 128.0,
        "thumb_contrast": 50.0,
        "thumb_colorfulness": 30.0,
        "thumb_face_largest_pct": 0.0,
        "theme_id": theme_id,
        "franchise_id": franchise_id,
        "title_embedding": title_embedding,
        "thumb_embedding": thumb_embedding,
    }
    df = pd.DataFrame([row])
    df["subs_bucket"] = df["subs"].apply(bucket_of).astype(int)
    df = _annotate_calendar(df)
    with duckdb.connect(str(db), read_only=True) as con:
        df = _annotate_horror_distance(con, df)
    return df
