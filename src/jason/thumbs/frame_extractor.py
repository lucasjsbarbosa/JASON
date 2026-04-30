"""Extract candidate thumbnail frames from a local video file via ffmpeg.

Per CLAUDE.md Fase 4.5:
    * 20 candidate frames evenly spaced at 5% increments
    * filter out frames that are too dark (low luminance) or too blurry
      (low Laplacian variance)

`ffmpeg` must be on PATH. We don't bundle it because it's available system-wide
on every dev box and the wheel size of e.g. `imageio-ffmpeg` is large.

Frame quality filtering uses OpenCV; lazy-imported to keep the cv2 dep
optional for users who don't run this module.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_NUM_CANDIDATES = 20
DEFAULT_DARK_THRESHOLD = 30.0  # mean luminance 0..255 below this → drop
DEFAULT_BLUR_THRESHOLD = 30.0  # Laplacian variance below this → drop


def _ffprobe_duration(video_path: Path) -> float:
    """Return video duration in seconds via ffprobe. Raises if not installed."""
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe not on PATH — install ffmpeg (sudo apt install ffmpeg)")
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _extract_at_times(
    video_path: Path, times: list[float], output_dir: Path
) -> list[Path]:
    """Use ffmpeg's `-ss` seek per timestamp; output `frame_NN.jpg`.

    One ffmpeg invocation per frame is slower than a single fps-based pass,
    but precise timestamps and easier to debug.
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not on PATH")

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, t in enumerate(times):
        out = output_dir / f"frame_{i:03d}.jpg"
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-ss", f"{t:.3f}", "-i", str(video_path),
                "-frames:v", "1", "-q:v", "2", str(out),
            ],
            check=True,
        )
        paths.append(out)
    return paths


def _quality_score(frame_path: Path) -> tuple[float, float]:
    """Return (mean_luminance, laplacian_variance) for filtering."""
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    img = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
    if img is None:
        return (0.0, 0.0)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    luminance = float(np.mean(gray))
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    blur = float(laplacian.var())
    return (luminance, blur)


def extract_candidate_frames(
    video_path: Path,
    *,
    output_dir: Path,
    num_candidates: int = DEFAULT_NUM_CANDIDATES,
    dark_threshold: float = DEFAULT_DARK_THRESHOLD,
    blur_threshold: float = DEFAULT_BLUR_THRESHOLD,
) -> list[dict]:
    """Pull `num_candidates` evenly-spaced frames from `video_path` and filter.

    Returns:
        List of dicts {path, time_s, luminance, blur, kept} ordered by time.
        Kept = passed both luminance and blur thresholds.
    """
    if not video_path.exists():
        raise FileNotFoundError(video_path)

    duration = _ffprobe_duration(video_path)
    # Evenly spaced from 5% to 95% — skip the first/last 5% (intros/outros).
    fracs = [0.05 + (0.9 * i / (num_candidates - 1)) for i in range(num_candidates)]
    times = [duration * f for f in fracs]

    paths = _extract_at_times(video_path, times, output_dir)

    out: list[dict] = []
    for t, p in zip(times, paths, strict=True):
        lum, blur = _quality_score(p)
        kept = lum >= dark_threshold and blur >= blur_threshold
        out.append({
            "path": p,
            "time_s": t,
            "luminance": lum,
            "blur": blur,
            "kept": kept,
        })
        if not kept:
            logger.debug("dropping %s (lum=%.1f blur=%.1f)", p.name, lum, blur)
    return out
