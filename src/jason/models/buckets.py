"""Subscriber-tier bucketing.

Per CLAUDE.md v1.2, `subs_bucket` is derived on-the-fly from `channels.subs`
and is NOT cached as a column. The reason: subscriber count drifts upward
over time (3.5k → 10k changes the tier), so a cached bucket goes stale and
contaminates downstream features.
"""

from __future__ import annotations


def bucket_of(subs: int | None) -> int:
    """Log-bin a raw subscriber count to a tier index 0..4.

    Tiers correspond to:
        0: 0-1k     (micro)
        1: 1k-10k   (small, e.g. @babygiulybaby at 3.48k)
        2: 10k-100k (medium, e.g. @CineAntiqua at 153k → actually tier 3)
        3: 100k-1M  (large)
        4: 1M+      (mega)
    """
    if subs is None or subs < 1_000:
        return 0
    if subs < 10_000:
        return 1
    if subs < 100_000:
        return 2
    if subs < 1_000_000:
        return 3
    return 4
