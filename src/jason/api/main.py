"""FastAPI backend pra a nova UI Next.js.

Substitui a aba Streamlit gradualmente. O DuckDB roda sempre `read_only=True`
nos handlers que só leem; writes (A/B feedback) usam conexão dedicada por
request. CORS aberto pra `localhost:3000` (Next.js dev).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from jason.config import get_settings
from jason.dashboard.humanize import (
    humanize_multiplier,
    humanize_percentile,
    humanize_topic_label,
)

app = FastAPI(
    title="JASON API",
    version="0.1.0",
    description="YouTube outlier intelligence backend.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _read_db() -> duckdb.DuckDBPyConnection:
    s = get_settings()
    return duckdb.connect(str(s.duckdb_path), read_only=True)


def _write_db() -> duckdb.DuckDBPyConnection:
    s = get_settings()
    return duckdb.connect(str(s.duckdb_path))


# --- response schemas ----------------------------------------------------


class HealthResponse(BaseModel):
    status: str = "ok"
    db_path: str
    own_channel_id: str


class OutlierVideo(BaseModel):
    id: str
    title: str
    channel: str
    percentile: float | None
    multiplier: float | None
    views: int | None
    thumbnail_url: str | None
    theme_label: str | None = None
    franchise_label: str | None = None
    multiplier_human: str | None = None
    percentile_human: str | None = None


class OwnMetrics(BaseModel):
    long_videos: int
    last_upload: datetime | None
    top_multiplier: float | None
    soft_outliers: int
    top_multiplier_human: str | None


class PackagingGapRow(BaseModel):
    feature: str
    own_pct: float
    niche_pct: float
    diff_pp: float


class ThemeCoverage(BaseModel):
    theme: str
    own_n: int
    own_avg_mult: float | None
    own_top_mult: float | None
    niche_n: int | None
    niche_avg_mult: float | None
    niche_top_mult: float | None


class ScoreRequest(BaseModel):
    title: str
    channel_id: str | None = None
    duration_min: float = Field(default=40.0, ge=1.0, le=180.0)


class ScoreContribution(BaseModel):
    feature: str
    label: str
    value: str
    contribution: float
    direction: str
    verb: str
    color: str


class ScoreResponse(BaseModel):
    multiplier: float
    log_multiplier: float
    multiplier_human: str
    contributions: list[ScoreContribution]


class SuggestRequest(BaseModel):
    transcript: str
    channel_id: str | None = None
    theme: str | None = None
    num_candidates: int = Field(default=10, ge=3, le=20)
    duration_min: float = Field(default=40.0, ge=1.0, le=180.0)


class SuggestCandidate(BaseModel):
    title: str
    multiplier: float | None = None
    multiplier_human: str | None = None
    contributions: list[ScoreContribution] = Field(default_factory=list)


class SuggestResponse(BaseModel):
    candidates: list[SuggestCandidate]
    rag_outlier_count: int
    model_trained: bool


# --- endpoints -----------------------------------------------------------


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    s = get_settings()
    return HealthResponse(
        db_path=str(s.duckdb_path),
        own_channel_id=s.own_channel_id,
    )


@app.get("/api/outliers", response_model=list[OutlierVideo])
def list_outliers(
    channel_id: str | None = None,
    limit: int = 30,
    min_percentile: float = 0.0,
) -> list[OutlierVideo]:
    sql = """
        SELECT v.id, v.title, c.title AS channel,
               o.percentile_in_channel,
               o.multiplier,
               latest.views,
               v.thumbnail_url,
               f.theme_label, f.franchise_label
        FROM videos v
        JOIN channels c ON c.id = v.channel_id
        LEFT JOIN video_features f ON f.video_id = v.id
        LEFT JOIN outliers o ON o.video_id = v.id
        LEFT JOIN (
            SELECT video_id, MAX(views) AS views
            FROM video_stats_snapshots GROUP BY video_id
        ) latest ON latest.video_id = v.id
        WHERE v.is_short = false
    """
    params: list[Any] = []
    if channel_id:
        sql += " AND v.channel_id = ?"
        params.append(channel_id)
    if min_percentile > 0:
        sql += " AND COALESCE(o.percentile_in_channel, 0) >= ?"
        params.append(min_percentile)
    sql += " ORDER BY o.percentile_in_channel DESC NULLS LAST, o.multiplier DESC NULLS LAST, latest.views DESC NULLS LAST LIMIT ?"
    params.append(limit)

    with _read_db() as con:
        rows = con.execute(sql, params).fetchall()

    out = []
    for r in rows:
        mult = float(r[4]) if r[4] is not None else None
        pct = float(r[3]) if r[3] is not None else None
        out.append(OutlierVideo(
            id=r[0],
            title=r[1],
            channel=r[2],
            percentile=pct,
            multiplier=mult,
            views=int(r[5]) if r[5] is not None else None,
            thumbnail_url=r[6],
            theme_label=humanize_topic_label(r[7]),
            franchise_label=humanize_topic_label(r[8]),
            multiplier_human=humanize_multiplier(mult) if mult else None,
            percentile_human=humanize_percentile(pct) if pct else None,
        ))
    return out


@app.get("/api/own/metrics", response_model=OwnMetrics)
def own_metrics() -> OwnMetrics:
    settings = get_settings()
    own = settings.own_channel_id
    with _read_db() as con:
        row = con.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM videos WHERE channel_id = ? AND is_short = false),
              (SELECT MAX(published_at) FROM videos WHERE channel_id = ?),
              (SELECT MAX(o.multiplier) FROM outliers o
                 JOIN videos v ON v.id = o.video_id WHERE v.channel_id = ?),
              (SELECT COUNT(*) FROM outliers o
                 JOIN videos v ON v.id = o.video_id
                WHERE v.channel_id = ? AND o.multiplier >= 1.5)
            """,
            [own, own, own, own],
        ).fetchone()
    long_videos, last_upload, top_mult, soft = row
    return OwnMetrics(
        long_videos=int(long_videos or 0),
        last_upload=last_upload,
        top_multiplier=float(top_mult) if top_mult is not None else None,
        soft_outliers=int(soft or 0),
        top_multiplier_human=humanize_multiplier(float(top_mult)) if top_mult else None,
    )


@app.get("/api/own/top-videos", response_model=list[OutlierVideo])
def own_top_videos(limit: int = 10) -> list[OutlierVideo]:
    settings = get_settings()
    return list_outliers(channel_id=settings.own_channel_id, limit=limit)


@app.post("/api/score", response_model=ScoreResponse)
def score(req: ScoreRequest) -> ScoreResponse:
    from jason.dashboard.humanize import humanize_contribution
    from jason.models.predict import score_title_with_explanation

    settings = get_settings()
    channel_id = req.channel_id or settings.own_channel_id
    duration_s = int(req.duration_min * 60)

    try:
        r = score_title_with_explanation(
            req.title, channel_id, duration_s=duration_s, top_k=8,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Modelo não treinado ainda: {exc}",
        ) from exc

    contributions = []
    for c in r["contributions"]:
        h = humanize_contribution(c)
        contributions.append(ScoreContribution(
            feature=c["feature"],
            label=h["label"],
            value=h["value"],
            contribution=float(c["contribution"]),
            direction=c["direction"],
            verb=h["verb"],
            color=h["color"],
        ))
    return ScoreResponse(
        multiplier=float(r["multiplier"]),
        log_multiplier=float(r["log_multiplier"]),
        multiplier_human=humanize_multiplier(float(r["multiplier"])),
        contributions=contributions,
    )


@app.get("/api/own/packaging-gap", response_model=list[PackagingGapRow])
def packaging_gap() -> list[PackagingGapRow]:
    settings = get_settings()
    own = settings.own_channel_id
    rate_features = [
        ("has_caps_word",         "Título tem palavra em CAPS"),
        ("has_number",            "Título tem número"),
        ("has_question_mark",     "Título tem ?"),
        ("has_emoji",             "Título tem emoji"),
        ("has_first_person",      "Título usa 1ª pessoa"),
        ("has_explained_keyword", "Título tem EXPLICADO/ENTENDA"),
        ("has_ranking_keyword",   "Título é ranking"),
        ("has_curiosity_keyword", "Título tem curiosity gap"),
        ("has_extreme_adjective", "Título tem adjetivo extremo"),
    ]

    with _read_db() as con:
        out = []
        for col, label in rate_features:
            own_v = con.execute(
                f"""
                SELECT AVG(CAST(f.{col} AS INT)) FROM videos v
                JOIN video_features f ON f.video_id = v.id
                WHERE v.channel_id = ? AND v.is_short = false
                """,
                [own],
            ).fetchone()[0]
            niche_v = con.execute(
                f"""
                SELECT AVG(CAST(f.{col} AS INT)) FROM videos v
                JOIN video_features f ON f.video_id = v.id
                JOIN outliers o ON o.video_id = v.id
                WHERE v.is_short = false AND o.percentile_in_channel >= 90
                  AND v.channel_id != ?
                """,
                [own],
            ).fetchone()[0]
            own_pct = float(own_v or 0) * 100
            niche_pct = float(niche_v or 0) * 100
            out.append(PackagingGapRow(
                feature=label,
                own_pct=round(own_pct, 1),
                niche_pct=round(niche_pct, 1),
                diff_pp=round(own_pct - niche_pct, 1),
            ))
    return out


@app.get("/api/own/themes", response_model=list[ThemeCoverage])
def themes_coverage() -> list[ThemeCoverage]:
    settings = get_settings()
    own = settings.own_channel_id
    with _read_db() as con:
        rows = con.execute(
            """
            WITH own_themes AS (
                SELECT f.theme_label, COUNT(*) AS own_n,
                       AVG(o.multiplier) AS own_avg, MAX(o.multiplier) AS own_top
                FROM videos v
                JOIN video_features f ON f.video_id = v.id
                LEFT JOIN outliers o ON o.video_id = v.id
                WHERE v.channel_id = ? AND v.is_short = false AND f.theme_label IS NOT NULL
                GROUP BY 1
            ),
            niche_themes AS (
                SELECT f.theme_label, COUNT(*) AS niche_n,
                       AVG(o.multiplier) AS niche_avg, MAX(o.multiplier) AS niche_top
                FROM videos v
                JOIN video_features f ON f.video_id = v.id
                LEFT JOIN outliers o ON o.video_id = v.id
                WHERE v.channel_id != ? AND v.is_short = false AND f.theme_label IS NOT NULL
                GROUP BY 1
            )
            SELECT o.theme_label, o.own_n, o.own_avg, o.own_top,
                   n.niche_n, n.niche_avg, n.niche_top
            FROM own_themes o
            LEFT JOIN niche_themes n USING (theme_label)
            ORDER BY o.own_avg DESC NULLS LAST
            LIMIT 50
            """,
            [own, own],
        ).fetchall()
    out = []
    for r in rows:
        clean = humanize_topic_label(r[0]) or r[0]
        out.append(ThemeCoverage(
            theme=clean,
            own_n=int(r[1]),
            own_avg_mult=float(r[2]) if r[2] is not None else None,
            own_top_mult=float(r[3]) if r[3] is not None else None,
            niche_n=int(r[4]) if r[4] is not None else None,
            niche_avg_mult=float(r[5]) if r[5] is not None else None,
            niche_top_mult=float(r[6]) if r[6] is not None else None,
        ))
    return out


@app.post("/api/suggest", response_model=SuggestResponse)
def suggest(req: SuggestRequest) -> SuggestResponse:
    """Gera N candidatos via Claude (RAG sobre outliers do nicho), ranqueia
    pelo modelo se treinado, devolve com explicação humanizada."""
    from jason.dashboard.humanize import humanize_contribution
    from jason.generation.titles import generate_titles
    from jason.models.predict import score_title_with_explanation

    settings = get_settings()
    channel_id = req.channel_id or settings.own_channel_id
    duration_s = int(req.duration_min * 60)

    if not req.transcript.strip():
        raise HTTPException(status_code=400, detail="Transcrição vazia.")

    try:
        gen = generate_titles(
            req.transcript,
            channel_id=channel_id,
            theme=req.theme or None,
            num_candidates=req.num_candidates,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Erro chamando Claude: {exc}",
        ) from exc

    candidates: list[SuggestCandidate] = []
    model_trained = True
    for t in gen["titles"]:
        try:
            s = score_title_with_explanation(
                t, channel_id, duration_s=duration_s, top_k=4,
            )
        except FileNotFoundError:
            model_trained = False
            candidates.append(SuggestCandidate(title=t))
            continue

        mult = float(s["multiplier"])
        contribs: list[ScoreContribution] = []
        for c in s["contributions"]:
            h = humanize_contribution(c)
            contribs.append(ScoreContribution(
                feature=c["feature"],
                label=h["label"],
                value=h["value"],
                contribution=float(c["contribution"]),
                direction=c["direction"],
                verb=h["verb"],
                color=h["color"],
            ))
        candidates.append(SuggestCandidate(
            title=t,
            multiplier=mult,
            multiplier_human=humanize_multiplier(mult),
            contributions=contribs,
        ))

    if model_trained:
        candidates.sort(key=lambda c: -(c.multiplier or 0))

    return SuggestResponse(
        candidates=candidates,
        rag_outlier_count=len(gen.get("outlier_ids", []) or []),
        model_trained=model_trained,
    )


def _data_dir() -> Path:
    return get_settings().data_dir
