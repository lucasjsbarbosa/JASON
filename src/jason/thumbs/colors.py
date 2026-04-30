"""Dominant-color extraction across a cohort of thumbnails.

Given N thumbnail images, downsample each to a small fixed size, stack all
pixels, run KMeans(k) and return the cluster centroids sorted by cluster
share. Used by the dashboard to show "this theme's outliers tend to use
these 3 colors" — practical reference when editing your own thumb.

PIL + sklearn live in `[dependency-groups.ml]`; the import is lazy so this
module can be imported in tests without those deps installed.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def dominant_colors_from_paths(
    paths: list[Path],
    *,
    k: int = 3,
    per_image_pixels: int = 64,
) -> list[tuple[int, int, int]]:
    """Compute k dominant RGB colors across `paths`.

    Each thumbnail is resized to (per_image_pixels x per_image_pixels) so
    pixel-stack stays bounded (default ~4k pixels per image; 25 images ≈
    100k pixels). KMeans on that runs in <1 sec.

    Returns a list of (R, G, B) tuples sorted by cluster size desc.
    Returns an empty list if no usable images.
    """
    import numpy as np  # noqa: PLC0415
    from PIL import Image, UnidentifiedImageError  # noqa: PLC0415
    from sklearn.cluster import KMeans  # noqa: PLC0415

    pixels: list[np.ndarray] = []
    for p in paths:
        try:
            img = Image.open(p).convert("RGB").resize(
                (per_image_pixels, per_image_pixels)
            )
        except (FileNotFoundError, UnidentifiedImageError, OSError) as exc:
            logger.debug("colors: skipping %s (%s)", p, exc)
            continue
        pixels.append(np.array(img).reshape(-1, 3))

    if not pixels:
        return []

    stacked = np.vstack(pixels)
    effective_k = min(k, max(2, len(stacked) // 1000)) if k > 1 else 1
    km = KMeans(n_clusters=effective_k, n_init=4, random_state=42)
    labels = km.fit_predict(stacked)

    counts = np.bincount(labels, minlength=effective_k)
    order = np.argsort(-counts)
    centroids = km.cluster_centers_[order].astype(int)
    return [(int(r), int(g), int(b)) for r, g, b in centroids]


def hex_from_rgb(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)
