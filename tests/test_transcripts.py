"""Tests for jason.ingestion.transcripts.

The faster-whisper library is heavy (~150MB) and not in the dev group, so
the model is dependency-injected as a fake. Behaviour we care about:
the JSON shape, idempotency, channel filter, missing-audio handling.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from jason.config import get_settings
from jason.ingestion.transcripts import transcribe_audio, transcribe_pending

CHANNEL_A = "UCtransA000000000000000z"
CHANNEL_B = "UCtransB000000000000000z"


class FakeWhisperModel:
    """Stand-in for faster_whisper.WhisperModel.transcribe()."""

    def __init__(self, segments: list[tuple[float, float, str]], language: str = "pt"):
        self._segments = segments
        self._language = language

    def transcribe(self, audio_path: str, language: str = "pt"):  # noqa: ARG002
        segs = (SimpleNamespace(start=s, end=e, text=t) for s, e, t in self._segments)
        info = SimpleNamespace(language=self._language, duration=self._segments[-1][1] if self._segments else 0.0)
        return segs, info


def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path, Path]:
    db = tmp_path / "warehouse.duckdb"
    monkeypatch.setenv("DUCKDB_PATH", str(db))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    db.parent.mkdir(parents=True, exist_ok=True)
    schema = Path("migrations/001_init.sql").read_text(encoding="utf-8")
    with duckdb.connect(str(db)) as con:
        con.execute(schema)

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    transcripts_dir = tmp_path / "transcripts"
    return db, audio_dir, transcripts_dir


def _seed(db: Path, rows: list[tuple[str, str]]) -> None:
    """rows: list of (channel_id, video_id)."""
    with duckdb.connect(str(db)) as con:
        for ch in {r[0] for r in rows}:
            con.execute("INSERT INTO channels (id, title) VALUES (?, ?)", [ch, "T"])
        for ch, vid in rows:
            con.execute(
                "INSERT INTO videos (id, channel_id, title, published_at) VALUES (?, ?, ?, ?)",
                [vid, ch, f"t-{vid}", "2026-04-01T00:00:00Z"],
            )


# ---------------------------------------------------------------------------
# transcribe_audio (single)
# ---------------------------------------------------------------------------


def test_transcribe_audio_writes_expected_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, audio_dir, transcripts_dir = _setup(monkeypatch, tmp_path)
    audio = audio_dir / "vid_aaaa01.m4a"
    audio.write_bytes(b"fake audio bytes")

    fake = FakeWhisperModel(
        [
            (0.0, 2.5, " Olá, sejam bem-vindos."),
            (2.5, 5.0, " Hoje vamos analisar Hereditário."),
        ]
    )

    target = transcribe_audio(audio, "vid_aaaa01", output_dir=transcripts_dir, model=fake)

    assert target == transcripts_dir / "vid_aaaa01.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["video_id"] == "vid_aaaa01"
    assert payload["language"] == "pt"
    assert payload["duration"] == 5.0
    assert payload["text"] == "Olá, sejam bem-vindos. Hoje vamos analisar Hereditário."
    assert len(payload["segments"]) == 2
    assert payload["segments"][0] == {"start": 0.0, "end": 2.5, "text": " Olá, sejam bem-vindos."}


def test_transcribe_audio_missing_file_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, transcripts_dir = _setup(monkeypatch, tmp_path)
    fake = FakeWhisperModel([(0.0, 1.0, "x")])
    with pytest.raises(FileNotFoundError):
        transcribe_audio(
            tmp_path / "nope.m4a", "vid_x", output_dir=transcripts_dir, model=fake
        )


# ---------------------------------------------------------------------------
# transcribe_pending (batch)
# ---------------------------------------------------------------------------


def test_transcribe_pending_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, audio_dir, transcripts_dir = _setup(monkeypatch, tmp_path)
    _seed(db, [(CHANNEL_A, "vid_pend0001"), (CHANNEL_A, "vid_pend0002")])
    (audio_dir / "vid_pend0001.m4a").write_bytes(b"a")
    (audio_dir / "vid_pend0002.mp3").write_bytes(b"b")

    fake = FakeWhisperModel([(0.0, 1.0, " teste.")])

    result = transcribe_pending(
        audio_dir, output_dir=transcripts_dir, model=fake
    )
    assert result == {"requested": 2, "transcribed": 2, "skipped": 0, "no_audio": 0}
    assert (transcripts_dir / "vid_pend0001.json").exists()
    assert (transcripts_dir / "vid_pend0002.json").exists()


def test_transcribe_pending_skips_already_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, audio_dir, transcripts_dir = _setup(monkeypatch, tmp_path)
    _seed(db, [(CHANNEL_A, "vid_skip0001")])
    (audio_dir / "vid_skip0001.m4a").write_bytes(b"a")
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    (transcripts_dir / "vid_skip0001.json").write_text('{"video_id":"vid_skip0001"}', encoding="utf-8")

    fake = FakeWhisperModel([(0.0, 1.0, "y")])
    result = transcribe_pending(audio_dir, output_dir=transcripts_dir, model=fake)
    assert result == {"requested": 1, "transcribed": 0, "skipped": 1, "no_audio": 0}


def test_transcribe_pending_counts_no_audio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, audio_dir, transcripts_dir = _setup(monkeypatch, tmp_path)
    _seed(db, [(CHANNEL_A, "vid_noaudio01"), (CHANNEL_A, "vid_audio001")])
    (audio_dir / "vid_audio001.wav").write_bytes(b"a")

    fake = FakeWhisperModel([(0.0, 1.0, "z")])
    result = transcribe_pending(audio_dir, output_dir=transcripts_dir, model=fake)
    assert result == {"requested": 2, "transcribed": 1, "skipped": 0, "no_audio": 1}


def test_transcribe_pending_channel_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, audio_dir, transcripts_dir = _setup(monkeypatch, tmp_path)
    _seed(db, [(CHANNEL_A, "vid_chA00001"), (CHANNEL_B, "vid_chB00001")])
    (audio_dir / "vid_chA00001.m4a").write_bytes(b"a")
    (audio_dir / "vid_chB00001.m4a").write_bytes(b"b")

    fake = FakeWhisperModel([(0.0, 1.0, "q")])
    result = transcribe_pending(
        audio_dir, output_dir=transcripts_dir, model=fake, channel_id=CHANNEL_A
    )
    assert result["requested"] == 1
    assert result["transcribed"] == 1
    assert (transcripts_dir / "vid_chA00001.json").exists()
    assert not (transcripts_dir / "vid_chB00001.json").exists()
