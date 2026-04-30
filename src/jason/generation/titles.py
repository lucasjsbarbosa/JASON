"""Generate candidate titles via Claude with prompt caching.

Per CLAUDE.md Fase 4 the prompt is split into a stable prefix (system role,
channel tone, 20 outlier reference titles) marked with `cache_control:
ephemeral` and a per-call variable suffix (transcript summary, theme).

The cache hit on the prefix cuts ~80% of the input cost and improves
latency from the second call onward in the same 5-minute window.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from jason.config import get_settings
from jason.generation.rag import search_outliers

if TYPE_CHECKING:  # pragma: no cover
    from anthropic import Anthropic

logger = logging.getLogger(__name__)

DEFAULT_NUM_CANDIDATES = 10


SYSTEM_PROMPT = """\
Você é o JASON: gerador de títulos para o canal @babygiulybaby (YouTube PT-BR,
~3.5k inscritos, nicho de **reviews e análises de filmes de terror**).

Seu trabalho: dado o conteúdo de um vídeo novo (transcrição/resumo + tema),
gerar candidatos a título que tenham alta probabilidade de virar outlier no
nicho — ou seja, títulos cuja estrutura de packaging se assemelhe à dos
títulos vencedores que vou anexar como referência.

Regras de geração:
1. Sempre em português brasileiro, tom natural do canal (técnico mas com
   personalidade do gênero — piscadas pra Jason, Sexta-feira 13, etc.).
2. Diversidade de estrutura — gere candidatos com formatos DIFERENTES (ex:
   um com pergunta, um com "FINAL EXPLICADO", um com ranking/número, um
   com adjetivo extremo, um com curiosity gap, um com nome próprio em CAPS).
3. NÃO copie um título existente; reuse a *estrutura*, não o texto.
4. NÃO faça clickbait raso ("você não vai acreditar...") sem substância.
5. Limite: 70 caracteres por título (limite efetivo do YouTube).
6. NÃO inclua referências a "Claude", "JASON" o sistema, ou meta-comentário —
   só os títulos limpos.

Saída: JSON estrito no formato `{"titles": ["...", "...", ...]}` com
exatamente N candidatos (N será especificado no pedido).
"""


def _build_static_prefix(channel_examples: Sequence[str], outliers: Sequence[dict]) -> str:
    """The cacheable prefix: channel voice examples + outlier references."""
    parts = ["## Tom e exemplos do canal próprio (@babygiulybaby)\n"]
    if channel_examples:
        for t in channel_examples[:10]:
            parts.append(f"- {t}")
    else:
        parts.append("(nenhum vídeo do canal próprio com sinal forte ainda)")
    parts.append("\n## Outliers do nicho — referências de packaging vencedor")
    for o in outliers:
        ch = o.get("channel_title", "?")
        pct = o.get("percentile", 0.0)
        mult = o.get("multiplier", 0.0)
        line = f"- [{ch}]"
        if pct:
            line += f" p{pct:.0f}"
        if mult:
            line += f" {mult:.1f}x"
        line += f" — {o['title']}"
        parts.append(line)
    return "\n".join(parts)


def _build_user_message(transcript_summary: str, theme: str | None, num_titles: int) -> str:
    parts = ["## Vídeo novo\n"]
    if theme:
        parts.append(f"**Tema/franquia detectada:** {theme}\n")
    parts.append("**Resumo da transcrição:**")
    parts.append(transcript_summary)
    parts.append(f"\nGere exatamente {num_titles} candidatos. Saída: JSON `{{\"titles\": [...]}}`.")
    return "\n".join(parts)


def _summarize_transcript(text: str, max_words: int = 200) -> str:
    """Simple word-count truncation. The full pipeline will eventually use
    Claude for a real summary, but for v1 this keeps the prompt deterministic."""
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]) + " [...]"


def _read_channel_examples(con: duckdb.DuckDBPyConnection, channel_id: str, n: int = 10) -> list[str]:
    """Top-N highest-views own-channel titles, as voice examples."""
    rows = con.execute(
        """
        SELECT v.title FROM videos v
        JOIN (SELECT video_id, MAX(views) AS views
              FROM video_stats_snapshots GROUP BY video_id) latest
          ON latest.video_id = v.id
        WHERE v.channel_id = ? AND v.is_short = false
        ORDER BY latest.views DESC
        LIMIT ?
        """,
        [channel_id, n],
    ).fetchall()
    return [r[0] for r in rows]


_JSON_BLOCK_RE = re.compile(r"\{.*?\}", re.DOTALL)


def _parse_titles(response_text: str) -> list[str]:
    """Pull `titles` out of the model's JSON response. Tolerates surrounding
    chatter by grabbing the first {...} block."""
    match = _JSON_BLOCK_RE.search(response_text)
    if not match:
        raise ValueError(f"no JSON block in response: {response_text[:200]}")
    payload = json.loads(match.group(0))
    titles = payload.get("titles")
    if not isinstance(titles, list) or not titles:
        raise ValueError(f"bad payload shape: {payload!r}")
    return [str(t).strip() for t in titles]


def generate_titles(
    transcript: str,
    *,
    channel_id: str,
    theme: str | None = None,
    num_candidates: int = DEFAULT_NUM_CANDIDATES,
    db_path: Path | None = None,
    client: Anthropic | None = None,
    rag_results: list[dict] | None = None,
) -> dict[str, Any]:
    """Synthesize N candidate titles via Claude using cached static prefix.

    Args:
        transcript: free text describing/transcribing the new video.
        channel_id: target channel (UC...) — pulled own-channel voice examples
            from this id.
        theme: optional theme/franchise hint included in the user message.
        num_candidates: how many titles to return.
        client: optional Anthropic client (DI for tests). Defaults to
            `anthropic.Anthropic()` (uses ANTHROPIC_API_KEY from env).
        rag_results: optional pre-fetched outlier references. When None,
            calls `search_outliers(transcript_summary)` to fetch fresh.

    Returns:
        dict with `titles` (list of N strings), `outlier_ids` (the IDs that
        seeded the prompt), `transcript_hash`.
    """
    settings = get_settings()
    db = db_path or settings.duckdb_path

    summary = _summarize_transcript(transcript)
    transcript_hash = hashlib.sha256(transcript.encode("utf-8")).hexdigest()[:16]

    if rag_results is None:
        rag_results = search_outliers(summary, top_k=20)

    with duckdb.connect(str(db), read_only=True) as con:
        own_examples = _read_channel_examples(con, channel_id, n=10)

    static_prefix = _build_static_prefix(own_examples, rag_results)
    user_msg = _build_user_message(summary, theme, num_candidates)

    if client is None:
        from anthropic import Anthropic  # noqa: PLC0415
        client = Anthropic(api_key=settings.anthropic_api_key)

    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=2048,
        system=[
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": static_prefix, "cache_control": {"type": "ephemeral"}},
        ],
        messages=[{"role": "user", "content": user_msg}],
    )

    response_text = "".join(
        block.text for block in response.content if hasattr(block, "text")
    )
    titles = _parse_titles(response_text)

    if len(titles) > num_candidates:
        titles = titles[:num_candidates]
    elif len(titles) < num_candidates:
        logger.warning("model returned %d titles, expected %d", len(titles), num_candidates)

    outlier_ids = [r["video_id"] for r in rag_results]
    return {
        "titles": titles,
        "outlier_ids": outlier_ids,
        "transcript_hash": transcript_hash,
    }


def persist_suggestions(
    *,
    channel_id: str,
    candidates: list[tuple[str, float | None]],
    transcript_hash: str,
    outlier_ids: list[str],
    db_path: Path | None = None,
) -> int:
    """Write a `suggestions` row per candidate. Returns the count inserted."""
    settings = get_settings()
    db = db_path or settings.duckdb_path

    with duckdb.connect(str(db)) as con:
        for rank, (title, mult) in enumerate(candidates, start=1):
            con.execute(
                """
                INSERT INTO suggestions
                    (id, channel_id, candidate_title, rank_position,
                     predicted_multiplier, transcript_hash, rag_outlier_ids)
                VALUES (nextval('suggestions_id_seq'), ?, ?, ?, ?, ?, ?)
                """,
                [channel_id, title, rank, mult, transcript_hash, outlier_ids],
            )
    return len(candidates)
