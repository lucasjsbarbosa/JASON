"""Tests for jason.features.embeddings — uses fake encoders, no torch needed."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from jason.config import get_settings
from jason.features.embeddings import (
    THUMB_EMBED_DIM,
    TITLE_EMBED_DIM,
    embed_thumbnails,
    embed_titles,
)

CHANNEL_A = "UCembA00000000000000000z"
CHANNEL_B = "UCembB00000000000000000z"


def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    db = tmp_path / "warehouse.duckdb"
    monkeypatch.setenv("DUCKDB_PATH", str(db))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    db.parent.mkdir(parents=True, exist_ok=True)
    for sql_file in ("001_init.sql", "004_video_features.sql", "005_embeddings.sql"):
        with duckdb.connect(str(db)) as con:
            con.execute(Path(f"migrations/{sql_file}").read_text(encoding="utf-8"))
    thumbs_dir = tmp_path / "thumbnails"
    thumbs_dir.mkdir()
    return db, thumbs_dir


def _seed(db: Path, rows: list[tuple[str, str, str]]) -> None:
    """rows: (channel_id, video_id, title)."""
    with duckdb.connect(str(db)) as con:
        for ch in {r[0] for r in rows}:
            con.execute("INSERT INTO channels (id, title) VALUES (?, ?)", [ch, "C"])
        for ch, vid, title in rows:
            con.execute(
                "INSERT INTO videos (id, channel_id, title, published_at) VALUES (?, ?, ?, ?)",
                [vid, ch, title, "2026-04-01T00:00:00Z"],
            )


def _fake_title_encoder(texts: list[str]) -> list[list[float]]:
    """Deterministic 768-dim vectors based on string length."""
    return [[float(len(t)) / 100.0] * TITLE_EMBED_DIM for t in texts]


def _fake_thumb_encoder(paths: list[Path]) -> list[list[float]]:
    """Deterministic 512-dim vectors based on file size."""
    return [[float(p.stat().st_size) / 1000.0] * THUMB_EMBED_DIM for p in paths]


# ---------------------------------------------------------------------------
# Title embeddings
# ---------------------------------------------------------------------------


def test_embed_titles_writes_vectors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, _ = _setup(monkeypatch, tmp_path)
    _seed(
        db,
        [
            (CHANNEL_A, "vid_emb0001", "Hereditário EXPLICADO"),
            (CHANNEL_A, "vid_emb0002", "Top 10 perturbadores"),
        ],
    )

    r = embed_titles(encode_fn=_fake_title_encoder)
    assert r == {"requested": 2, "encoded": 2}

    with duckdb.connect(str(db)) as con:
        rows = con.execute(
            "SELECT video_id, len(title_embedding) FROM video_features ORDER BY video_id"
        ).fetchall()
    assert rows == [("vid_emb0001", TITLE_EMBED_DIM), ("vid_emb0002", TITLE_EMBED_DIM)]


def test_embed_titles_skips_already_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, _ = _setup(monkeypatch, tmp_path)
    _seed(db, [(CHANNEL_A, "vid_skip0001", "Título")])
    embed_titles(encode_fn=_fake_title_encoder)
    r2 = embed_titles(encode_fn=_fake_title_encoder)
    assert r2 == {"requested": 0, "encoded": 0}


def test_embed_titles_force_recomputes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, _ = _setup(monkeypatch, tmp_path)
    _seed(db, [(CHANNEL_A, "vid_force0001", "X")])
    embed_titles(encode_fn=_fake_title_encoder)
    r2 = embed_titles(encode_fn=_fake_title_encoder, force=True)
    assert r2 == {"requested": 1, "encoded": 1}


def test_embed_titles_channel_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, _ = _setup(monkeypatch, tmp_path)
    _seed(
        db,
        [
            (CHANNEL_A, "vid_chA00001", "AAA"),
            (CHANNEL_B, "vid_chB00001", "BBB"),
        ],
    )
    r = embed_titles(encode_fn=_fake_title_encoder, channel_id=CHANNEL_A)
    assert r == {"requested": 1, "encoded": 1}
    with duckdb.connect(str(db)) as con:
        ids = [r[0] for r in con.execute(
            "SELECT video_id FROM video_features WHERE title_embedding IS NOT NULL"
        ).fetchall()]
    assert ids == ["vid_chA00001"]


def test_embed_titles_rejects_wrong_dim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Encoder returning the wrong dimension should raise — guards against silent
    schema/model drift."""
    db, _ = _setup(monkeypatch, tmp_path)
    _seed(db, [(CHANNEL_A, "vid_dim00001", "X")])

    def bad_encoder(texts: list[str]) -> list[list[float]]:
        return [[1.0] * 100 for _ in texts]  # wrong dim

    with pytest.raises(ValueError, match="title encoder returned 100-dim"):
        embed_titles(encode_fn=bad_encoder)


def test_embed_titles_batches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify batching: 100 videos with batch_size=10 → encoder called 10 times."""
    db, _ = _setup(monkeypatch, tmp_path)
    _seed(
        db,
        [(CHANNEL_A, f"vid_b{i:06d}", f"title-{i}") for i in range(100)],
    )

    call_count = 0
    batch_sizes = []

    def counting_encoder(texts: list[str]) -> list[list[float]]:
        nonlocal call_count
        call_count += 1
        batch_sizes.append(len(texts))
        return _fake_title_encoder(texts)

    embed_titles(encode_fn=counting_encoder, batch_size=10)
    assert call_count == 10
    assert all(b == 10 for b in batch_sizes)


# ---------------------------------------------------------------------------
# Thumbnail embeddings
# ---------------------------------------------------------------------------


def test_embed_thumbnails_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, thumbs_dir = _setup(monkeypatch, tmp_path)
    _seed(
        db,
        [
            (CHANNEL_A, "vid_thumb0001", "T1"),
            (CHANNEL_A, "vid_thumb0002", "T2"),
        ],
    )
    (thumbs_dir / "vid_thumb0001.jpg").write_bytes(b"x" * 1000)
    (thumbs_dir / "vid_thumb0002.jpg").write_bytes(b"y" * 2500)

    r = embed_thumbnails(encode_fn=_fake_thumb_encoder)
    assert r["encoded"] == 2

    with duckdb.connect(str(db)) as con:
        rows = con.execute(
            "SELECT video_id, len(thumb_embedding) FROM video_features ORDER BY video_id"
        ).fetchall()
    assert rows == [("vid_thumb0001", THUMB_EMBED_DIM), ("vid_thumb0002", THUMB_EMBED_DIM)]


def test_embed_thumbnails_skips_missing_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Videos without an on-disk thumbnail are silently dropped from `pending`."""
    db, thumbs_dir = _setup(monkeypatch, tmp_path)
    _seed(
        db,
        [
            (CHANNEL_A, "vid_thno0001", "no thumb"),
            (CHANNEL_A, "vid_thyes0001", "has thumb"),
        ],
    )
    (thumbs_dir / "vid_thyes0001.jpg").write_bytes(b"data")

    r = embed_thumbnails(encode_fn=_fake_thumb_encoder)
    assert r["encoded"] == 1


def test_embed_thumbnails_rejects_wrong_dim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, thumbs_dir = _setup(monkeypatch, tmp_path)
    _seed(db, [(CHANNEL_A, "vid_thd0001", "T")])
    (thumbs_dir / "vid_thd0001.jpg").write_bytes(b"x")

    def bad_encoder(paths: list[Path]) -> list[list[float]]:
        return [[1.0] * 256 for _ in paths]

    with pytest.raises(ValueError, match="thumb encoder returned 256-dim"):
        embed_thumbnails(encode_fn=bad_encoder)


def test_embed_thumbnails_skips_invalid_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A single bad file in a batch must not kill the run — it gets skipped, the
    rest goes through, and the count comes back in skipped_invalid."""
    db, thumbs_dir = _setup(monkeypatch, tmp_path)
    _seed(
        db,
        [
            (CHANNEL_A, "vid_thbad0001", "bad"),
            (CHANNEL_A, "vid_thgood001", "good"),
            (CHANNEL_A, "vid_thgood002", "good2"),
        ],
    )
    (thumbs_dir / "vid_thbad0001.jpg").write_bytes(b"")  # 0-byte
    (thumbs_dir / "vid_thgood001.jpg").write_bytes(b"x" * 1000)
    (thumbs_dir / "vid_thgood002.jpg").write_bytes(b"y" * 2000)

    def encoder(paths: list[Path]) -> list[list[float]]:
        # Mimic PIL behavior: choke on 0-byte files.
        for p in paths:
            if p.stat().st_size == 0:
                raise OSError(f"cannot identify image file {p}")
        return [[float(p.stat().st_size) / 1000.0] * THUMB_EMBED_DIM for p in paths]

    r = embed_thumbnails(encode_fn=encoder, batch_size=3)
    assert r["encoded"] == 2
    assert r["skipped_invalid"] == 1

    with duckdb.connect(str(db)) as con:
        ids = sorted(
            r[0] for r in con.execute(
                "SELECT video_id FROM video_features WHERE thumb_embedding IS NOT NULL"
            ).fetchall()
        )
    assert ids == ["vid_thgood001", "vid_thgood002"]
