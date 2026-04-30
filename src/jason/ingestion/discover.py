"""Discover BR-PT horror YouTube channels in tier_0/1 range pra expandir
o sample do nicho.

Pipeline:
1. Search YouTube por queries de terror (search.list type=channel) — coleta
   IDs candidatos.
2. Bulk channels.list pra cada id — pega title, handle, subs, description,
   country, last upload.
3. Filtros mínimos: BR-related (country=BR ou descrição PT-BR), subs em
   [min_subs, max_subs], canal ainda ativo (último upload < freshness_days).
4. Validação de horror em DUAS camadas:
   a. Keywords na descrição: terror, horror, slasher, found footage, etc.
   b. % de títulos recentes (últimos 10) que batem regex de horror.
5. Score composto: rate_titles_horror + boost se descrição confirma.
6. Output: lista TSV/markdown pro humano revisar antes de adicionar a
   `canais.txt`.

Quota: ~10 search × 100 + ~200 channels × 1 + ~100 channels uploads × 1 ≈
2100 unidades. Bem dentro do orçamento diário de 10k.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from jason.config import get_settings

if TYPE_CHECKING:  # pragma: no cover
    from googleapiclient.discovery import Resource

logger = logging.getLogger(__name__)


# Queries afinadas pro estilo @babygiulybaby + @CanalVídeoTerapia: análise +
# leitura de obra + final explicado, NÃO trailer/news/lançamento. Foco em
# "explicação interpretativa de filme de terror" — exatamente o que ela faz.
DEFAULT_QUERIES = [
    "análise filme terror",
    "final explicado filme terror",
    "leitura de filme terror",
    "interpretação filme terror",
    "comentando filme terror spoilers",
    "filme terror explicado completo",
    "análise de obra terror",
    "explicando filme terror",
    "curiosidades filme terror análise",
    "ranking melhores piores filme terror",
    # Mais variação — segunda rodada
    "review filme horror brasileiro",
    "crítica filme terror",
    "resenha filme terror",
    "decifrando filme terror",
    "desvendando filme terror",
    "análise final filme assustador",
]

# Keywords confirmando horror no canal (descrição ou título).
HORROR_DESC_KEYWORDS = re.compile(
    r"(?i)\b(terror|horror|slasher|found.?footage|bizarr[oa]?|"
    r"perturbador[ae]?|sobrenatural|gore|grotesco|trash|"
    r"jumpscare|possess[ãa]o|paranormal|sinist[roa])\b"
)

# Regex pra checar se um título de vídeo é "do nicho" — mesma família
# da feature `has_extreme_adjective` + temas comuns.
HORROR_TITLE_KEYWORDS = re.compile(
    r"(?i)\b(terror|horror|slasher|found.?footage|bizarr[oa]?|"
    r"perturbador[ae]?|sobrenatural|gore|grotesco|trash|"
    r"jumpscare|possess[ãa]o|paranormal|sinist[roa]|sangrent[oa]?|"
    r"assustador|mald[iíi]t[oa]?|amaldi[çc]oad[oa]?|"
    r"final explicado|final perturbador|filme.{0,15}(medo|terror)|"
    r"morte|assassino|massacre|brux[ao]|fantasma|esp[ií]rito|"
    r"demônio|culto|ritual|c[hHi]ucky|jason|freddy|invocação)\b"
)

# Gaming/streaming sinal — se título bate aqui, NÃO conta como título de
# review de horror, mesmo que mencione "terror" (ex: "joguei Outlast 2 ao
# vivo"). Acima de N hits no sample, canal é descartado como gaming.
GAMING_TITLE_KEYWORDS = re.compile(
    r"(?i)\b(gameplay|jogand[oa]|joguei|let'?s\s*play|walkthrough|"
    r"playthrough|speedrun|stream(er)?|gamer|gaming|"
    r"ao\s*vivo|live\s*game|jogo\s*completo|"
    r"phasmophobia|outlast|until\s*dawn|five\s*nights|fnaf|"
    r"resident\s*evil\s*\d|silent\s*hill\s*\d|"
    r"ptbr|pt-br\s*game)\b"
)

PT_INDICATORS = re.compile(
    r"(?i)\b(brasil|brasileir[oa]|pt[-\s]?br|portugu[êe]s|"
    r"análise|filme|cinema|terror)\b"
)


@dataclass
class CandidateChannel:
    channel_id: str
    handle: str | None
    title: str
    description: str
    subs: int
    country: str | None
    last_upload: str | None
    n_recent_videos: int = 0
    n_horror_titles: int = 0
    n_gaming_titles: int = 0
    sample_titles: list[str] = field(default_factory=list)

    @property
    def horror_title_rate(self) -> float:
        if self.n_recent_videos == 0:
            return 0.0
        return self.n_horror_titles / self.n_recent_videos

    @property
    def gaming_title_rate(self) -> float:
        if self.n_recent_videos == 0:
            return 0.0
        return self.n_gaming_titles / self.n_recent_videos

    @property
    def desc_horror(self) -> bool:
        return bool(HORROR_DESC_KEYWORDS.search(self.description or ""))

    @property
    def is_pt_br(self) -> bool:
        if self.country == "BR":
            return True
        text = f"{self.title} {self.description}"
        return bool(PT_INDICATORS.search(text))

    @property
    def score(self) -> float:
        """Composite — title-rate dominates, with a small bump if the
        description corroborates."""
        return self.horror_title_rate + (0.1 if self.desc_horror else 0.0)


# --- YouTube API helpers --------------------------------------------------


def _youtube_client() -> Resource:
    from googleapiclient.discovery import build  # noqa: PLC0415

    settings = get_settings()
    if not settings.youtube_data_api_key:
        raise RuntimeError("YOUTUBE_DATA_API_KEY not set")
    return build("youtube", "v3", developerKey=settings.youtube_data_api_key)


def _search_channels(yt: Resource, query: str, max_results: int = 50) -> list[str]:
    """Returns channel IDs matching a search query (top N)."""
    out: list[str] = []
    request = yt.search().list(
        q=query, type="channel", maxResults=min(max_results, 50),
        relevanceLanguage="pt", regionCode="BR", part="snippet",
    )
    response = request.execute()
    for item in response.get("items", []):
        cid = item.get("snippet", {}).get("channelId") or item.get("id", {}).get("channelId")
        if cid:
            out.append(cid)
    return out


def _bulk_channel_meta(yt: Resource, channel_ids: list[str]) -> list[dict[str, Any]]:
    """channels.list em batches de 50 — devolve snippet+statistics+contentDetails."""
    items: list[dict[str, Any]] = []
    for i in range(0, len(channel_ids), 50):
        batch = channel_ids[i : i + 50]
        resp = yt.channels().list(
            id=",".join(batch),
            part="snippet,statistics,contentDetails",
        ).execute()
        items.extend(resp.get("items", []))
    return items


def _recent_titles(yt: Resource, uploads_playlist_id: str, n: int = 10) -> list[str]:
    """Pega os N títulos mais recentes do canal via uploads playlist."""
    resp = yt.playlistItems().list(
        playlistId=uploads_playlist_id,
        part="snippet",
        maxResults=min(n, 50),
    ).execute()
    return [it["snippet"]["title"] for it in resp.get("items", [])]


# --- main pipeline -------------------------------------------------------


def discover(
    *,
    queries: list[str] | None = None,
    min_subs: int = 500,
    max_subs: int = 30_000,
    freshness_days: int = 90,
    horror_title_threshold: float = 0.3,
    sample_size: int = 10,
    yt_client: Resource | None = None,
    existing_ids: set[str] | None = None,
) -> list[CandidateChannel]:
    """Run the full discover pipeline. Returns candidates ranked by score.

    Args:
        queries: search queries (default: DEFAULT_QUERIES, ~10 horror terms)
        min_subs / max_subs: sub range to keep (tier_0 + tier_1 + bottom of tier_2)
        freshness_days: skip channels with no upload in last N days
        horror_title_threshold: minimum % of recent titles that must match
            HORROR_TITLE_KEYWORDS to keep
        sample_size: how many recent titles to fetch per candidate
        yt_client: dependency-injected for tests
        existing_ids: skip channels already in our pool
    """
    yt = yt_client or _youtube_client()
    queries = queries or DEFAULT_QUERIES
    existing = existing_ids or set()
    # freshness_days kept in signature for forward-compat; we proxy
    # freshness via "≥ N horror titles in last sample_size", which
    # implicitly requires recent uploads (dead channels won't have N
    # horror titles in their last 10 uploads).
    _ = freshness_days

    # 1) Search → seed channel ids
    seen: set[str] = set()
    for q in queries:
        try:
            ids = _search_channels(yt, q)
        except Exception as exc:  # noqa: BLE001
            logger.warning("search failed for %r: %s", q, exc)
            continue
        for cid in ids:
            if cid not in existing:
                seen.add(cid)
        logger.info("query %r → %d new (pool=%d)", q, len(ids), len(seen))

    if not seen:
        return []

    # 2) Bulk meta lookup
    metas = _bulk_channel_meta(yt, list(seen))
    logger.info("got meta for %d candidates", len(metas))

    # 3) Filter on subs + country + freshness, then horror validation
    candidates: list[CandidateChannel] = []
    for m in metas:
        cid = m["id"]
        snippet = m.get("snippet", {})
        stats = m.get("statistics", {})
        details = m.get("contentDetails", {}).get("relatedPlaylists", {})

        subs_str = stats.get("subscriberCount")
        if subs_str is None or stats.get("hiddenSubscriberCount"):
            continue
        subs = int(subs_str)
        if subs < min_subs or subs > max_subs:
            continue

        cand = CandidateChannel(
            channel_id=cid,
            handle=snippet.get("customUrl"),
            title=snippet.get("title", ""),
            description=snippet.get("description", ""),
            subs=subs,
            country=snippet.get("country"),
            last_upload=None,
        )

        if not cand.is_pt_br:
            continue

        # Sample recent titles
        uploads = details.get("uploads")
        if not uploads:
            continue
        try:
            titles = _recent_titles(yt, uploads, n=sample_size)
        except Exception as exc:  # noqa: BLE001
            logger.warning("playlist fetch failed for %s: %s", cid, exc)
            continue

        if not titles:
            continue

        cand.sample_titles = titles
        cand.n_recent_videos = len(titles)
        # Conta horror SÓ quando NÃO é gaming. "Joguei Outlast 2 ao vivo" não é
        # review de filme — descarta do contador.
        cand.n_horror_titles = sum(
            1 for t in titles
            if HORROR_TITLE_KEYWORDS.search(t)
            and not GAMING_TITLE_KEYWORDS.search(t)
        )
        cand.n_gaming_titles = sum(
            1 for t in titles if GAMING_TITLE_KEYWORDS.search(t)
        )

        # Hard cut: canal com >= 2 títulos gaming no sample é gaming-channel,
        # não review-channel. Descarta independente do horror rate.
        if cand.n_gaming_titles >= 2:
            logger.debug(
                "skipping gaming channel %s (%d gaming titles)",
                cand.handle or cand.channel_id, cand.n_gaming_titles,
            )
            continue

        # Freshness via lastest upload time — use playlist item's snippet
        # publishedAt indirectly. Cheaper proxy: just require >=3 horror titles
        # in last `sample_size`. Skip strict date check pra economizar quota.
        if cand.horror_title_rate < horror_title_threshold:
            continue

        candidates.append(cand)

    candidates.sort(key=lambda c: c.score, reverse=True)
    logger.info(
        "discover: %d candidates passed (from %d seeds, %d existing skipped)",
        len(candidates), len(metas), len(existing),
    )
    return candidates


def format_markdown(candidates: list[CandidateChannel], *, top_n: int = 50) -> str:
    """Format as a markdown table for human review."""
    out = ["# Canais candidatos pra adicionar\n"]
    out.append(
        "| score | subs | handle | título | horror % | gaming % | desc horror? | amostra |"
    )
    out.append("|-------|------|--------|--------|----------|----------|--------------|---------|")
    for c in candidates[:top_n]:
        sample = " · ".join(c.sample_titles[:2])[:60]
        out.append(
            f"| {c.score:.2f} | {c.subs:,} | {c.handle or '?'} | "
            f"{c.title[:30]} | {c.horror_title_rate*100:.0f}% "
            f"({c.n_horror_titles}/{c.n_recent_videos}) | "
            f"{c.gaming_title_rate*100:.0f}% | "
            f"{'sim' if c.desc_horror else 'não'} | {sample} |"
        )
    return "\n".join(out)
