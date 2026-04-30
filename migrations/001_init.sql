-- migration 001: initial schema. apply via `jason db init`.

CREATE TABLE IF NOT EXISTS channels (
    id          VARCHAR PRIMARY KEY,    -- UC... (24 chars)
    handle      VARCHAR,                -- @babygiulybaby (sem @ é tolerável)
    title       VARCHAR,
    subs        INTEGER,
    niche_tag   VARCHAR,                -- ex: 'horror_review', 'horror_reaction'
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS videos (
    id            VARCHAR PRIMARY KEY,  -- youtube video id (11 chars)
    channel_id    VARCHAR NOT NULL REFERENCES channels(id),
    title         VARCHAR NOT NULL,
    description   VARCHAR,
    published_at  TIMESTAMP NOT NULL,
    duration_s    INTEGER,
    views         BIGINT,
    likes         BIGINT,
    comments      BIGINT,
    thumbnail_url VARCHAR,
    ingested_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_videos_channel_published
    ON videos(channel_id, published_at);

CREATE TABLE IF NOT EXISTS title_tests (
    video_id          VARCHAR NOT NULL REFERENCES videos(id),
    variant_id        INTEGER NOT NULL,         -- 1..3 (Test & Compare é até 3 variantes)
    title             VARCHAR NOT NULL,
    thumbnail_path    VARCHAR,
    watch_time_share  DOUBLE,
    is_winner         BOOLEAN,
    recorded_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (video_id, variant_id)
);

CREATE TABLE IF NOT EXISTS outliers (
    video_id    VARCHAR PRIMARY KEY REFERENCES videos(id),
    multiplier  DOUBLE NOT NULL,
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
