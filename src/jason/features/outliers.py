"""Outlier detection — `views_at_28d` interpolation, multiplier, intra-channel percentile.

Per CLAUDE.md v1.1, this is the heart of the age-bias correction:
    multiplier = views_at_28d / median(views_at_28d of last 30 prior eligible videos)

A video is "eligible" when its `video_stats_snapshots` history brackets the
target age (one snapshot at-or-before target_days, one at-or-after). Until
`jason snapshot run` has been firing for ~28 days, most videos won't qualify —
the function returns `None` and the row simply doesn't enter `outliers`.
That's correct: without bracketing snapshots there is no signal, only noise.

Per CLAUDE.md v1.2 fallback: if a video has fewer than `min_baseline` (10)
prior eligible videos in the same channel, multiplier is NULL — the channel's
baseline is too thin to be confident.
"""

from __future__ import annotations

import logging
import statistics
from pathlib import Path
from typing import Any

import duckdb

from jason.config import get_settings

logger = logging.getLogger(__name__)


def _trimmed_median(values: list[int], *, trim_frac: float = 0.1) -> float:
    """Median ignoring the top and bottom `trim_frac` of the sorted sequence.

    Robust to a single viral hit poisoning the rolling baseline. With <10
    values the trim degrades to plain median (k=int(n*0.1) is 0).
    """
    if not values:
        raise statistics.StatisticsError("no data points")
    n = len(values)
    k = int(n * trim_frac)
    sorted_vals = sorted(values)
    middle = sorted_vals[k : n - k] if k > 0 else sorted_vals
    return statistics.median(middle)


def views_at_age(
    con: duckdb.DuckDBPyConnection,
    video_id: str,
    target_days: int = 28,
) -> int | None:
    """Linearly interpolate views at age=target_days from surrounding snapshots.

    Returns None when:
        * No snapshots exist for this video.
        * All snapshots are strictly < target_days (video too young to evaluate).
        * All snapshots are strictly > target_days (we started tracking after
          the window — no early data point to bracket against).

    Returns the snapshot's `views` directly when one lands exactly at
    `days_since_publish == target_days`.
    """
    rows = con.execute(
        "SELECT days_since_publish, views FROM video_stats_snapshots "
        "WHERE video_id = ? ORDER BY days_since_publish",
        [video_id],
    ).fetchall()
    if not rows:
        return None

    before = [r for r in rows if r[0] <= target_days]
    after = [r for r in rows if r[0] >= target_days]
    if not before or not after:
        return None

    a_age, a_views = before[-1]
    b_age, b_views = after[0]

    if a_age == b_age:
        return int(a_views) if a_views is not None else None
    if a_views is None or b_views is None:
        return None

    frac = (target_days - a_age) / (b_age - a_age)
    return int(round(a_views + frac * (b_views - a_views)))


def compute_multiplier(
    channel_id: str,
    *,
    db_path: Path | None = None,
    target_days: int = 28,
    baseline_n: int = 30,
    min_baseline: int = 10,
) -> dict[str, Any]:
    """Compute and persist the outlier multiplier for every eligible long-form
    video in `channel_id`.

    multiplier = views_at_target_days / median(last `baseline_n` eligible
                                                videos' views_at_target_days)

    Skipped (no row written to `outliers`):
        * Shorts (`is_short = true`).
        * Videos without bracketing snapshots (views_at_age returns None).
        * Videos with fewer than `min_baseline` prior eligible videos.

    Returns a dict of counts for the run.
    """
    settings = get_settings()
    db = db_path or settings.duckdb_path

    with duckdb.connect(str(db)) as con:
        videos = con.execute(
            "SELECT id, published_at FROM videos "
            "WHERE channel_id = ? AND is_short = false "
            "ORDER BY published_at",
            [channel_id],
        ).fetchall()

        eligible: list[tuple[str, Any, int]] = []
        for vid, pub in videos:
            v = views_at_age(con, vid, target_days)
            if v is not None and v > 0:
                eligible.append((vid, pub, v))

        computed = 0
        skipped_baseline = 0
        for i, (vid, _pub, views) in enumerate(eligible):
            baseline = [e[2] for e in eligible[max(0, i - baseline_n):i]]
            if len(baseline) < min_baseline:
                skipped_baseline += 1
                continue
            median = statistics.median(baseline)
            if median <= 0:
                continue
            mult = views / median
            con.execute(
                """
                INSERT INTO outliers (video_id, multiplier, computed_at)
                VALUES (?, ?, now())
                ON CONFLICT (video_id) DO UPDATE SET
                    multiplier = EXCLUDED.multiplier,
                    computed_at = now()
                """,
                [vid, mult],
            )
            computed += 1

    return {
        "channel_id": channel_id,
        "total_videos": len(videos),
        "eligible": len(eligible),
        "computed": computed,
        "skipped_no_baseline": skipped_baseline,
        "skipped_no_age_data": len(videos) - len(eligible),
    }


def compute_multiplier_live(
    channel_id: str,
    *,
    db_path: Path | None = None,
    min_age_days: int = 60,
    baseline_n: int = 30,
    min_baseline: int = 10,
) -> dict[str, Any]:
    """Compute multiplier from the latest available snapshot.

    Trade-off vs `compute_multiplier`: this uses each video's most recent
    `views` directly instead of the 28-day cohort. Cheaper to run (no
    snapshot history needed) but biased toward older videos which had more
    time to accumulate views. We mitigate by:

      * Filtering to videos with `days_since_publish >= min_age_days` (default
        60) so the bias mostly stabilizes.
      * Comparing intra-channel against the immediately preceding 30 siblings
        — the bias is approximately constant within that local window.
      * **Trimmed median** (drop top/bottom 10%) so a single viral hit in
        the rolling baseline doesn't deflate every multiplier that follows
        it (or inflate the hit itself vs unusually weak prior siblings).

    Useful as a bootstrap before `compute_multiplier`'s 28-day cohort signal
    becomes available; switch back to the cohort method once snapshot history
    is mature.

    Skipped (no row written):
        * Shorts.
        * Videos younger than `min_age_days`.
        * Videos with no snapshot or zero views.
        * Videos with fewer than `min_baseline` prior eligible siblings.
    """
    settings = get_settings()
    db = db_path or settings.duckdb_path

    with duckdb.connect(str(db)) as con:
        total_videos = con.execute(
            "SELECT count(*) FROM videos WHERE channel_id = ? AND is_short = false",
            [channel_id],
        ).fetchone()[0]

        rows = con.execute(
            """
            WITH latest AS (
                SELECT video_id, MAX(captured_at) AS captured_at
                FROM video_stats_snapshots
                GROUP BY video_id
            )
            SELECT v.id, v.published_at, s.views
            FROM videos v
            JOIN latest l ON l.video_id = v.id
            JOIN video_stats_snapshots s
              ON s.video_id = l.video_id AND s.captured_at = l.captured_at
            WHERE v.channel_id = ?
              AND v.is_short = false
              AND DATE_DIFF('day', v.published_at, now()) >= ?
              AND s.views IS NOT NULL AND s.views > 0
            ORDER BY v.published_at
            """,
            [channel_id, min_age_days],
        ).fetchall()

        eligible = [(vid, pub, int(views)) for vid, pub, views in rows]

        computed = 0
        skipped_baseline = 0
        for i, (vid, _pub, views) in enumerate(eligible):
            baseline = [e[2] for e in eligible[max(0, i - baseline_n):i]]
            if len(baseline) < min_baseline:
                skipped_baseline += 1
                continue
            median = _trimmed_median(baseline, trim_frac=0.1)
            if median <= 0:
                continue
            mult = views / median
            con.execute(
                """
                INSERT INTO outliers (video_id, multiplier, computed_at)
                VALUES (?, ?, now())
                ON CONFLICT (video_id) DO UPDATE SET
                    multiplier = EXCLUDED.multiplier,
                    computed_at = now()
                """,
                [vid, mult],
            )
            computed += 1

    return {
        "channel_id": channel_id,
        "total_videos": total_videos,
        "eligible": len(eligible),
        "computed": computed,
        "skipped_no_baseline": skipped_baseline,
        "skipped_too_young_or_no_snapshot": total_videos - len(eligible),
    }


def compute_percentile(
    channel_id: str,
    *,
    db_path: Path | None = None,
    window_days: int = 90,
) -> dict[str, Any]:
    """For every video with a multiplier in `channel_id`, compute its percentile
    within a ±`window_days` rolling window of intra-channel multipliers.

    Outlier "official" definition (per CLAUDE.md): percentile_in_channel >= 90.
    """
    settings = get_settings()
    db = db_path or settings.duckdb_path

    with duckdb.connect(str(db)) as con:
        rows = con.execute(
            """
            SELECT o.video_id, o.multiplier, v.published_at
            FROM outliers o
            JOIN videos v ON v.id = o.video_id
            WHERE v.channel_id = ?
            ORDER BY v.published_at
            """,
            [channel_id],
        ).fetchall()

        computed = 0
        for vid, mult, pub in rows:
            window = con.execute(
                f"""
                SELECT o.multiplier
                FROM outliers o
                JOIN videos v ON v.id = o.video_id
                WHERE v.channel_id = ?
                  AND v.published_at BETWEEN ? - INTERVAL '{window_days} days'
                                         AND ? + INTERVAL '{window_days} days'
                """,
                [channel_id, pub, pub],
            ).fetchall()
            if not window:
                continue

            sorted_mults = sorted(m[0] for m in window)
            below = sum(1 for m in sorted_mults if m < mult)
            equal = sum(1 for m in sorted_mults if m == mult)
            percentile = (below + equal / 2) / len(sorted_mults) * 100

            con.execute(
                "UPDATE outliers SET percentile_in_channel = ? WHERE video_id = ?",
                [percentile, vid],
            )
            computed += 1

    return {"channel_id": channel_id, "computed": computed}
