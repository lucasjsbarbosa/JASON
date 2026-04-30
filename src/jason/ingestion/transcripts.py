"""faster-whisper wrapper for video transcription.

Per CLAUDE.md, transcription is gated to the user's own channel + the top-50
niche outliers — running large-v3 over hundreds of long-form horror videos is
expensive even on GPU. This module is a thin wrapper: it expects an audio file
already on disk (use yt-dlp or similar to fetch). The model is injected for
testability so the test suite doesn't need `faster-whisper` installed.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import duckdb

from jason.config import get_settings

if TYPE_CHECKING:  # pragma: no cover
    from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = (".m4a", ".mp3", ".wav", ".webm", ".opus", ".flac", ".ogg", ".mp4")


class _TranscribeResult(Protocol):
    """Subset of faster-whisper's return shape we depend on (for typing only)."""
    language: str
    duration: float


class _Segment(Protocol):
    start: float
    end: float
    text: str


def _load_model(model_size: str, device: str) -> WhisperModel:
    """Lazy import + instantiation. Keeps faster-whisper out of the import path
    for users who only run ingest commands."""
    from faster_whisper import WhisperModel  # noqa: PLC0415

    compute_type = "float16" if device == "cuda" else "int8"
    return WhisperModel(model_size, device=device, compute_type=compute_type)


def transcribe_audio(
    audio_path: Path,
    video_id: str,
    *,
    output_dir: Path | None = None,
    model: Any | None = None,
    model_size: str | None = None,
    device: str | None = None,
    language: str = "pt",
) -> Path:
    """Transcribe a single audio file to `data/transcripts/{video_id}.json`.

    Args:
        audio_path: existing audio file. We don't download from YouTube here —
            the caller is responsible (yt-dlp, etc.).
        video_id: 11-char YouTube ID; used as the output filename.
        output_dir: optional override (defaults to `<DATA_DIR>/transcripts`).
        model: optional pre-built model (for tests / model reuse across calls).
            When None, builds a `WhisperModel` from settings.
        model_size: override settings.whisper_model.
        device: override settings.whisper_device ('auto'/'cuda'/'cpu').
        language: ISO code passed to whisper. PT is the canal próprio default.

    Returns:
        Path to the written JSON file.
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"audio file not found: {audio_path}")

    settings = get_settings()
    out_dir = output_dir or (settings.data_dir / "transcripts")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{video_id}.json"

    if model is None:
        size = model_size or settings.whisper_model
        dev = device or settings.whisper_device
        if dev == "auto":
            try:
                import torch  # noqa: PLC0415
                dev = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                dev = "cpu"
        logger.info("loading whisper model: size=%s device=%s", size, dev)
        model = _load_model(size, dev)

    segments_iter, info = model.transcribe(str(audio_path), language=language)

    segments = [
        {"start": float(s.start), "end": float(s.end), "text": s.text}
        for s in segments_iter
    ]
    payload: dict[str, Any] = {
        "video_id": video_id,
        "language": getattr(info, "language", language),
        "duration": float(getattr(info, "duration", 0.0)),
        "text": "".join(s["text"] for s in segments).strip(),
        "segments": segments,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("transcribed %s -> %s (%d segments)", video_id, target, len(segments))
    return target


def _resolve_audio_for(video_id: str, audio_dir: Path) -> Path | None:
    """Find `{video_id}.<ext>` in audio_dir for any supported extension."""
    for ext in AUDIO_EXTENSIONS:
        candidate = audio_dir / f"{video_id}{ext}"
        if candidate.exists():
            return candidate
    return None


def transcribe_pending(
    audio_dir: Path,
    *,
    db_path: Path | None = None,
    output_dir: Path | None = None,
    channel_id: str | None = None,
    model: Any | None = None,
) -> dict[str, Any]:
    """Walk known videos and transcribe ones that have audio on disk + no JSON yet.

    Pre-built `model` is recommended when batching — loading large-v3 every call
    is slow.
    """
    settings = get_settings()
    db = db_path or settings.duckdb_path
    out_dir = output_dir or (settings.data_dir / "transcripts")
    out_dir.mkdir(parents=True, exist_ok=True)

    with duckdb.connect(str(db)) as con:
        if channel_id:
            rows = con.execute(
                "SELECT id FROM videos WHERE channel_id = ?", [channel_id]
            ).fetchall()
        else:
            rows = con.execute("SELECT id FROM videos").fetchall()

    counts = {"requested": len(rows), "transcribed": 0, "skipped": 0, "no_audio": 0}
    for (vid,) in rows:
        if (out_dir / f"{vid}.json").exists():
            counts["skipped"] += 1
            continue
        audio = _resolve_audio_for(vid, audio_dir)
        if audio is None:
            counts["no_audio"] += 1
            continue
        transcribe_audio(audio, vid, output_dir=out_dir, model=model)
        counts["transcribed"] += 1
    return counts
