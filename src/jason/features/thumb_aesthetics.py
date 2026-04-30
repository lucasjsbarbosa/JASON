"""Thumbnail aesthetic features (paper-backed): brightness, contrast,
colorfulness, face_largest_pct.

Visual Attributes paper (n=3745 thumbnails, 2023): brightness rank #1
em poder preditivo de views, contrast #2, colorfulness #3. Combinações
high+high (alto brilho + colorida) ou low+low (escura + monocromática)
batem mid+mid. JASON já calculava luminância em frame_extractor.py mas só
pra filtrar; agora persistimos como feature de modelo.

Hasler & Süsstrunk 2003 colorfulness:
  M = sqrt(σ_rg² + σ_yb²) + 0.3 · sqrt(μ_rg² + μ_yb²)
  rg = R - G;  yb = 0.5·(R + G) - B

face_largest_pct: área da maior face detectada (Haar) / área total do
frame. Reaction-face é padrão vencedor no nicho de terror.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from jason.config import get_settings

logger = logging.getLogger(__name__)


_FACE_CASCADE = None


def _get_face_cascade():
    """Load Haar cascade once and cache. Re-instantiating per image was a 100x slowdown."""
    global _FACE_CASCADE
    if _FACE_CASCADE is None:
        import cv2  # noqa: PLC0415
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _FACE_CASCADE = cv2.CascadeClassifier(cascade_path)
    return _FACE_CASCADE


def _compute_aesthetics(image_path: Path) -> dict[str, float] | None:
    """Returns brightness, contrast, colorfulness, face_largest_pct.

    None when the image can't be loaded.
    """
    import cv2  # noqa: PLC0415

    img = cv2.imread(str(image_path))
    if img is None:
        return None
    h, w = img.shape[:2]
    if h == 0 or w == 0:
        return None
    frame_area = float(h * w)

    # cv2 reads BGR. Convert to RGB float for clarity.
    bgr = img.astype("float32")
    b, g, r = bgr[..., 0], bgr[..., 1], bgr[..., 2]

    # Luminance (BT.601, common for video).
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    brightness = float(luminance.mean())              # 0-255
    contrast = float(luminance.std())                 # 0-128 typical

    # Hasler-Süsstrunk colorfulness.
    rg = r - g
    yb = 0.5 * (r + g) - b
    sigma_rg, mu_rg = float(rg.std()), float(rg.mean())
    sigma_yb, mu_yb = float(yb.std()), float(yb.mean())
    colorfulness = (
        (sigma_rg ** 2 + sigma_yb ** 2) ** 0.5
        + 0.3 * (mu_rg ** 2 + mu_yb ** 2) ** 0.5
    )

    # Face detection via Haar cascade (já usado em frame_scorer.py — mesma
    # fonte). Retorna área da maior face / área do frame.
    face_pct = 0.0
    try:
        # Resize to max 320px wide before face detection — Haar MultiScale
        # is O(pixels^2). 320px keeps faces detectable but cuts time ~10x.
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        max_w = 320
        if w > max_w:
            scale = max_w / w
            gray_small = cv2.resize(gray, (max_w, int(h * scale)))
        else:
            scale = 1.0
            gray_small = gray
        face_cascade = _get_face_cascade()
        faces = face_cascade.detectMultiScale(
            gray_small, scaleFactor=1.2, minNeighbors=5, minSize=(30, 30),
        )
        if len(faces) > 0:
            largest = max(faces, key=lambda b: b[2] * b[3])
            # Scale-back the area to the original frame.
            face_area_orig = (largest[2] * largest[3]) / (scale ** 2)
            face_pct = float(face_area_orig) / frame_area
    except Exception as exc:  # noqa: BLE001
        logger.debug("face detection failed for %s: %s", image_path, exc)

    return {
        "thumb_brightness": brightness,
        "thumb_contrast": contrast,
        "thumb_colorfulness": colorfulness,
        "thumb_face_largest_pct": face_pct,
    }


def compute_thumb_aesthetics(
    *,
    db_path: Path | None = None,
    thumbs_dir: Path | None = None,
    channel_id: str | None = None,
    force: bool = False,
    show_progress: bool = False,
) -> dict[str, int]:
    """For each video with a thumbnail on disk, compute and persist 4 features.

    Skips videos without `data/thumbnails/{video_id}.jpg`. Skips bad files
    (logged as `skipped_invalid`).
    """
    settings = get_settings()
    db = db_path or settings.duckdb_path
    tdir = thumbs_dir or (settings.data_dir / "thumbnails")

    with duckdb.connect(str(db)) as con:
        sql = ["SELECT v.id FROM videos v"]
        sql.append("LEFT JOIN video_features f ON f.video_id = v.id")
        if force:
            sql.append("WHERE 1=1")
        else:
            sql.append("WHERE (f.video_id IS NULL OR f.thumb_brightness IS NULL)")
        params: list = []
        if channel_id:
            sql.append("AND v.channel_id = ?")
            params.append(channel_id)
        rows = con.execute(" ".join(sql), params).fetchall()

        # Filter to videos with on-disk thumbnail.
        pending: list[tuple[str, Path]] = []
        for (vid,) in rows:
            p = tdir / f"{vid}.jpg"
            if p.exists():
                pending.append((vid, p))
        if not pending:
            return {"requested": 0, "computed": 0, "skipped_invalid": 0}

        ids = [vid for vid, _ in pending]
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
        skipped = 0
        total = len(pending)
        for i, (vid, path) in enumerate(pending, start=1):
            feats = _compute_aesthetics(path)
            if feats is None:
                skipped += 1
                continue
            con.execute(
                """
                UPDATE video_features SET
                    thumb_brightness = ?,
                    thumb_contrast = ?,
                    thumb_colorfulness = ?,
                    thumb_face_largest_pct = ?,
                    computed_at = now()
                WHERE video_id = ?
                """,
                [
                    feats["thumb_brightness"],
                    feats["thumb_contrast"],
                    feats["thumb_colorfulness"],
                    feats["thumb_face_largest_pct"],
                    vid,
                ],
            )
            computed += 1
            if show_progress and (i % 500 == 0 or i == total):
                logger.info("thumb aesthetics: %d/%d (skipped=%d)", i, total, skipped)

    logger.info("thumb aesthetics: %d computed (%d skipped invalid)", computed, skipped)
    return {"requested": len(pending), "computed": computed, "skipped_invalid": skipped}
