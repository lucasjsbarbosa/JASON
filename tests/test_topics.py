"""Tests for jason.features.topics — uses a fake BERTopic, no torch needed."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from jason.config import get_settings
from jason.features.topics import (
    _build_mask_patterns,
    _mask_proper_names,
    _strip_accents,
    fit_franchises,
    fit_themes,
)

CHANNEL_A = "UCtopicA000000000000000z"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_strip_accents_basic() -> None:
    assert _strip_accents("Hereditário") == "hereditario"
    assert _strip_accents("INVOCAÇÃO") == "invocacao"
    assert _strip_accents("PERTURBADORA") == "perturbadora"


def test_mask_proper_names_evergreen() -> None:
    """Evergreen names (Jason, Hereditário, Sobrenatural) get masked even
    without TMDb data."""
    pats = _build_mask_patterns([])
    assert _mask_proper_names("12 Máscaras de JASON Voorhees", pats) == "12 mascaras de [FILME]"
    assert _mask_proper_names("Hereditário FINAL EXPLICADO", pats) == "[FILME] final explicado"


def test_mask_proper_names_from_releases() -> None:
    """Movie titles from horror_releases get added to the mask vocabulary."""
    pats = _build_mask_patterns(["Pranto do Mal", "M3GAN 2.0"])
    masked = _mask_proper_names("Pranto do Mal foi PERTURBADOR!", pats)
    assert "[FILME]" in masked
    assert "perturbador" in masked


def test_mask_collapses_runs() -> None:
    """Runs of [FILME] [FILME] become a single [FILME]."""
    pats = _build_mask_patterns(["Sobrenatural", "Annabelle"])
    masked = _mask_proper_names("Sobrenatural Annabelle EXPLICADO", pats)
    assert masked.count("[FILME]") == 1
    assert "explicado" in masked


def test_mask_skips_short_names() -> None:
    """Names < 4 chars are too noisy and get dropped from the vocabulary."""
    pats = _build_mask_patterns(["X", "It", "Saw"])
    # Saw IS in the evergreen list (4 chars: 'saw' is 3 — skip it; but 'jogos mortais' covers it)
    # Verify "It" alone doesn't make every "i" or "it" disappear.
    masked = _mask_proper_names("It is a horror film", pats)
    assert masked == "it is a horror film"  # no mask applied (It is too short)


# ---------------------------------------------------------------------------
# fit_themes / fit_franchises with mocked BERTopic
# ---------------------------------------------------------------------------


class FakeBERTopic:
    """Returns deterministic topic ids based on text length parity."""

    def __init__(self, topic_assignments: list[int], names: dict[int, str]):
        self.topic_assignments = topic_assignments
        self.names = names
        self.received_documents: list[str] | None = None

    def fit_transform(self, documents: list[str]) -> tuple[list[int], list[float]]:
        self.received_documents = documents
        # Repeat or trim assignments to match document count.
        topics = (self.topic_assignments * ((len(documents) // len(self.topic_assignments)) + 1))[:len(documents)]
        return topics, [0.0] * len(documents)

    def get_topic_info(self) -> dict[int, str]:
        return self.names


def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db = tmp_path / "warehouse.duckdb"
    monkeypatch.setenv("DUCKDB_PATH", str(db))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    db.parent.mkdir(parents=True, exist_ok=True)
    for sql_file in (
        "001_init.sql", "003_horror_releases.sql",
        "004_video_features.sql", "005_embeddings.sql", "006_topics.sql",
    ):
        with duckdb.connect(str(db)) as con:
            con.execute(Path(f"migrations/{sql_file}").read_text(encoding="utf-8"))
    return db


def _seed(db: Path, rows: list[tuple[str, str, str]], *, is_short: bool = False) -> None:
    """rows: (channel_id, video_id, title)."""
    with duckdb.connect(str(db)) as con:
        for ch in {r[0] for r in rows}:
            con.execute("INSERT OR IGNORE INTO channels (id, title) VALUES (?, ?)", [ch, "C"])
        for ch, vid, title in rows:
            con.execute(
                "INSERT INTO videos (id, channel_id, title, published_at, is_short) "
                "VALUES (?, ?, ?, ?, ?)",
                [vid, ch, title, "2026-04-01T00:00:00Z", is_short],
            )


def test_fit_themes_writes_assignments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _setup(monkeypatch, tmp_path)
    _seed(
        db,
        [
            (CHANNEL_A, "vid_th0001", "JASON Voorhees PERTURBADOR"),
            (CHANNEL_A, "vid_th0002", "Final EXPLICADO de Hereditário"),
        ],
    )
    fake = FakeBERTopic(topic_assignments=[0, 1], names={0: "slasher_perturbador", 1: "explained_horror"})

    r = fit_themes(model_factory=lambda: fake)
    assert r == {"requested": 2, "fit": 2, "topics": 2}

    # The fake should have received masked titles, not raw.
    assert fake.received_documents is not None
    assert "[FILME]" in fake.received_documents[0]
    assert "[FILME]" in fake.received_documents[1]

    with duckdb.connect(str(db)) as con:
        rows = con.execute(
            "SELECT video_id, theme_id, theme_label FROM video_features ORDER BY video_id"
        ).fetchall()
    assert rows == [
        ("vid_th0001", 0, "slasher_perturbador"),
        ("vid_th0002", 1, "explained_horror"),
    ]


def test_fit_franchises_passes_raw_titles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Franchise layer should NOT mask names — they're the signal we want."""
    db = _setup(monkeypatch, tmp_path)
    _seed(
        db,
        [
            (CHANNEL_A, "vid_fr0001", "Hereditário Explicado"),
            (CHANNEL_A, "vid_fr0002", "Sobrenatural review"),
        ],
    )
    fake = FakeBERTopic(topic_assignments=[5, 7], names={5: "hereditario", 7: "sobrenatural"})

    r = fit_franchises(model_factory=lambda: fake)
    assert r["fit"] == 2

    assert fake.received_documents is not None
    assert "Hereditário" in fake.received_documents[0]   # raw, not masked
    assert "Sobrenatural" in fake.received_documents[1]

    with duckdb.connect(str(db)) as con:
        rows = con.execute(
            "SELECT video_id, franchise_id, franchise_label FROM video_features ORDER BY video_id"
        ).fetchall()
    assert rows == [
        ("vid_fr0001", 5, "hereditario"),
        ("vid_fr0002", 7, "sobrenatural"),
    ]


def test_fit_excludes_shorts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _setup(monkeypatch, tmp_path)
    _seed(db, [(CHANNEL_A, "vid_long01", "long form analysis")])
    _seed(db, [(CHANNEL_A, "vid_short01", "quick #shorts thing")], is_short=True)

    fake = FakeBERTopic(topic_assignments=[0], names={0: "x"})
    r = fit_themes(model_factory=lambda: fake)
    assert r["fit"] == 1

    with duckdb.connect(str(db)) as con:
        ids = [r[0] for r in con.execute(
            "SELECT video_id FROM video_features WHERE theme_id IS NOT NULL"
        ).fetchall()]
    assert ids == ["vid_long01"]


def test_outlier_topic_label_is_null(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """BERTopic uses -1 for noise/outlier; we persist as topic_id=-1, label=NULL."""
    db = _setup(monkeypatch, tmp_path)
    _seed(db, [(CHANNEL_A, "vid_noise01", "weird title")])
    fake = FakeBERTopic(topic_assignments=[-1], names={0: "topic_zero"})

    fit_themes(model_factory=lambda: fake)
    with duckdb.connect(str(db)) as con:
        row = con.execute(
            "SELECT theme_id, theme_label FROM video_features WHERE video_id = ?",
            ["vid_noise01"],
        ).fetchone()
    assert row == (-1, None)
