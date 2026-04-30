"""Tests for jason.generation — RAG retrieval + title synthesis (Anthropic mocked)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from jason.config import get_settings
from jason.generation.rag import _cosine, search_outliers
from jason.generation.titles import (
    _build_static_prefix,
    _parse_titles,
    _summarize_transcript,
    generate_titles,
    persist_suggestions,
)

CHANNEL_A = "UCgenA00000000000000000z"


def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db = tmp_path / "warehouse.duckdb"
    monkeypatch.setenv("DUCKDB_PATH", str(db))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    get_settings.cache_clear()
    db.parent.mkdir(parents=True, exist_ok=True)
    for sql_file in (
        "001_init.sql", "004_video_features.sql", "005_embeddings.sql",
        "006_topics.sql", "007_suggestions.sql",
    ):
        with duckdb.connect(str(db)) as con:
            con.execute(Path(f"migrations/{sql_file}").read_text(encoding="utf-8"))
    return db


def _seed_video_with_embedding(
    db: Path, *, video_id: str, channel_id: str, title: str,
    embedding: list[float], percentile: float | None = None,
    multiplier: float | None = None, views: int = 1000,
) -> None:
    pad = embedding + [0.0] * (768 - len(embedding))
    with duckdb.connect(str(db)) as con:
        con.execute("INSERT OR IGNORE INTO channels (id, title) VALUES (?, ?)", [channel_id, "C"])
        con.execute(
            "INSERT INTO videos (id, channel_id, title, published_at, is_short) "
            "VALUES (?, ?, ?, ?, ?)",
            [video_id, channel_id, title, "2026-04-01T00:00:00Z", False],
        )
        con.execute(
            "INSERT INTO video_features (video_id, title_embedding) VALUES (?, ?)",
            [video_id, pad],
        )
        con.execute(
            "INSERT INTO video_stats_snapshots "
            "(video_id, captured_at, days_since_publish, views) VALUES (?, ?, ?, ?)",
            [video_id, "2026-04-30T00:00:00Z", 29, views],
        )
        if percentile is not None or multiplier is not None:
            con.execute(
                "INSERT INTO outliers (video_id, multiplier, percentile_in_channel) "
                "VALUES (?, ?, ?)",
                [video_id, multiplier or 1.0, percentile],
            )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_cosine_orthogonal_and_aligned() -> None:
    a = [1.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    c = [0.0, 1.0, 0.0]
    assert _cosine(a, b) == 1.0
    assert _cosine(a, c) == 0.0


def test_summarize_transcript_truncates() -> None:
    text = " ".join(["palavra"] * 500)
    out = _summarize_transcript(text, max_words=100)
    assert "[...]" in out
    assert len(out.split()) <= 110  # 100 + the [...] tail


def test_summarize_transcript_passthrough() -> None:
    text = "curto sem corte"
    assert _summarize_transcript(text, max_words=100) == text


def test_parse_titles_extracts_json() -> None:
    response = """Aqui estão os candidatos:
    {"titles": ["Título 1", "Título 2", "Título 3"]}
    Espero que ajudem!"""
    titles = _parse_titles(response)
    assert titles == ["Título 1", "Título 2", "Título 3"]


def test_parse_titles_rejects_bad_shape() -> None:
    with pytest.raises(ValueError):
        _parse_titles("nada de JSON aqui")


def test_build_static_prefix_includes_channel_examples() -> None:
    prefix = _build_static_prefix(
        ["Título canal 1", "Título canal 2"],
        [{"title": "OUTLIER 1", "channel_title": "Canal X", "percentile": 95.0, "multiplier": 5.0}],
    )
    assert "Título canal 1" in prefix
    assert "OUTLIER 1" in prefix
    assert "p95" in prefix


# ---------------------------------------------------------------------------
# search_outliers (RAG)
# ---------------------------------------------------------------------------


def test_search_outliers_with_percentile_pool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _setup(monkeypatch, tmp_path)
    # 3 outliers with percentile >= 90
    _seed_video_with_embedding(db, video_id="vid_o001", channel_id=CHANNEL_A,
                                title="Hereditário Final Explicado",
                                embedding=[1.0, 0.0, 0.0], percentile=95.0, multiplier=4.0)
    _seed_video_with_embedding(db, video_id="vid_o002", channel_id=CHANNEL_A,
                                title="Sobrenatural review",
                                embedding=[0.0, 1.0, 0.0], percentile=92.0, multiplier=3.5)
    _seed_video_with_embedding(db, video_id="vid_o003", channel_id=CHANNEL_A,
                                title="Top 10 perturbadores",
                                embedding=[0.0, 0.0, 1.0], percentile=90.0, multiplier=3.0)
    # one non-outlier should not appear
    _seed_video_with_embedding(db, video_id="vid_meh01", channel_id=CHANNEL_A,
                                title="random",
                                embedding=[0.5, 0.5, 0.0])

    fake_embed = lambda q: [1.0, 0.0, 0.0] + [0.0] * 765  # noqa: E731
    results = search_outliers("query about Hereditário",
                              db_path=db, top_k=2, embedder=fake_embed)
    assert len(results) == 2
    assert results[0]["video_id"] == "vid_o001"  # closest cosine
    assert all(r["video_id"] != "vid_meh01" for r in results)


def test_search_outliers_falls_back_to_views(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When no percentiles are populated (early stage), fall back to top-views."""
    db = _setup(monkeypatch, tmp_path)
    _seed_video_with_embedding(db, video_id="vid_v001", channel_id=CHANNEL_A,
                                title="Low views", embedding=[1.0, 0.0, 0.0], views=100)
    _seed_video_with_embedding(db, video_id="vid_v002", channel_id=CHANNEL_A,
                                title="High views", embedding=[1.0, 0.0, 0.0], views=99999)

    fake_embed = lambda q: [1.0, 0.0, 0.0] + [0.0] * 765  # noqa: E731
    results = search_outliers("query", db_path=db, top_k=10, embedder=fake_embed)
    assert len(results) == 2  # both made it into the fallback pool


# ---------------------------------------------------------------------------
# generate_titles with mocked Anthropic client
# ---------------------------------------------------------------------------


class FakeAnthropic:
    """Stand-in for the Anthropic client. Captures the messages.create call."""

    def __init__(self, response_titles: list[str]):
        self._titles = response_titles
        self.captured: dict | None = None
        self.messages = self  # so .messages.create() works

    def create(self, **kwargs: object) -> object:
        self.captured = kwargs
        text = '{"titles": ' + str(self._titles).replace("'", '"') + "}"
        return SimpleNamespace(content=[SimpleNamespace(text=text)])


def test_generate_titles_calls_anthropic_with_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _setup(monkeypatch, tmp_path)
    _seed_video_with_embedding(db, video_id="vid_ref01", channel_id=CHANNEL_A,
                                title="Reference outlier", embedding=[1.0]*3,
                                percentile=95.0, multiplier=4.0)
    fake = FakeAnthropic(["Título A", "Título B", "Título C"])

    rag = [{"video_id": "vid_ref01", "title": "Ref", "channel_title": "Canal",
            "percentile": 95.0, "multiplier": 4.0, "similarity": 0.9}]

    result = generate_titles(
        "Resumo da transcrição.", channel_id=CHANNEL_A,
        num_candidates=3, db_path=db, client=fake, rag_results=rag,
    )

    assert result["titles"] == ["Título A", "Título B", "Título C"]
    assert result["outlier_ids"] == ["vid_ref01"]
    assert "transcript_hash" in result

    # Verify the static prefix was sent with cache_control.
    assert fake.captured is not None
    sys_blocks = fake.captured["system"]
    assert any(b.get("cache_control", {}).get("type") == "ephemeral" for b in sys_blocks)


def test_persist_suggestions_writes_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _setup(monkeypatch, tmp_path)
    n = persist_suggestions(
        channel_id=CHANNEL_A,
        candidates=[("Title 1", 3.5), ("Title 2", 2.0), ("Title 3", None)],
        transcript_hash="abc123",
        outlier_ids=["vid_a", "vid_b"],
        db_path=db,
    )
    assert n == 3
    with duckdb.connect(str(db)) as con:
        rows = con.execute(
            "SELECT candidate_title, rank_position, predicted_multiplier "
            "FROM suggestions ORDER BY rank_position"
        ).fetchall()
    assert rows == [("Title 1", 1, 3.5), ("Title 2", 2, 2.0), ("Title 3", 3, None)]
