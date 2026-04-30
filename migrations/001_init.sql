-- migration 001: initial schema. apply via `jason db init`.
-- Aligned with CLAUDE.md v1.1+:
--   * `videos` carries no metrics (anti-age-bias); metrics live in video_stats_snapshots
--   * is_short flag separates Shorts from long-form for downstream model filtering
--   * title_tests.result is enum-like (winner/loser/inconclusive), with confidence_pct
--   * outliers carries both absolute multiplier and intra-channel percentile
--
-- FK note: DuckDB's current ART-index implementation rejects ON CONFLICT
-- DO UPDATE on a row that is referenced by another table's FK (it treats the
-- upsert as DELETE+INSERT internally). Snapshot ingestion + channel/video
-- upserts are core flows here, so we omit FKs and rely on application-side
-- ordering inside ingest_channel().

CREATE TABLE IF NOT EXISTS channels (
    id          VARCHAR PRIMARY KEY,    -- UC... (24 chars)
    handle      VARCHAR,                -- @babygiulybaby (sem @ é tolerável)
    title       VARCHAR,
    subs        INTEGER,                -- mantido como número absoluto; subs_bucket é derivado on-the-fly (ver bucket_of)
    niche_tag   VARCHAR,                -- ex: 'horror_review', 'horror_reaction'
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS videos (
    id            VARCHAR PRIMARY KEY,  -- youtube video id (11 chars)
    channel_id    VARCHAR NOT NULL,     -- logical FK to channels(id); not enforced (DuckDB ART limitation)
    title         VARCHAR NOT NULL,
    description   VARCHAR,
    published_at  TIMESTAMP NOT NULL,
    duration_s    INTEGER,
    is_short      BOOLEAN NOT NULL DEFAULT FALSE,
    thumbnail_url VARCHAR,
    ingested_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_videos_channel_published
    ON videos(channel_id, published_at);

CREATE INDEX IF NOT EXISTS idx_videos_is_short
    ON videos(is_short);

-- Snapshots históricos de métricas. Chave (video_id, captured_at) permite
-- múltiplas linhas por vídeo ao longo do tempo. views_at_28d (Fase 2) é
-- interpolado linearmente entre os dois snapshots mais próximos.
CREATE TABLE IF NOT EXISTS video_stats_snapshots (
    video_id            VARCHAR NOT NULL,                -- logical FK to videos(id); not enforced
    captured_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    days_since_publish  INTEGER NOT NULL,
    views               BIGINT,
    likes               BIGINT,
    comments            BIGINT,
    PRIMARY KEY (video_id, captured_at)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_video_age
    ON video_stats_snapshots(video_id, days_since_publish);

CREATE TABLE IF NOT EXISTS title_tests (
    video_id          VARCHAR NOT NULL,                -- logical FK to videos(id); not enforced
    variant_id        INTEGER NOT NULL,                -- 1..3 (Test & Compare é até 3 variantes)
    title             VARCHAR NOT NULL,
    thumbnail_path    VARCHAR,
    watch_time_share  DOUBLE,
    -- Para teste com significância: 1 linha 'winner' + N-1 'loser'.
    -- Para teste sem significância: TODAS as N linhas 'inconclusive'.
    result            VARCHAR CHECK (result IN ('winner', 'loser', 'inconclusive')),
    confidence_pct    DOUBLE,
    recorded_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (video_id, variant_id)
);

CREATE TABLE IF NOT EXISTS outliers (
    video_id              VARCHAR PRIMARY KEY,         -- logical FK to videos(id); not enforced
    multiplier            DOUBLE NOT NULL,             -- views_at_28d / mediana(views_at_28d últimos 30 vídeos)
    percentile_in_channel DOUBLE,                      -- percentil intra-canal em janela de 90 dias (oficial: >=90 = outlier)
    computed_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
