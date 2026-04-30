-- migration 007: title suggestions log.
-- Each `jason suggest` run persists its candidates here so we can later
-- match them against actual results from the YouTube Test & Compare A/B
-- (Fase 6 feedback loop) and weight winning patterns higher in retraining.

CREATE TABLE IF NOT EXISTS suggestions (
    id              INTEGER PRIMARY KEY,             -- DuckDB ROWID-style; see seq below
    channel_id      VARCHAR NOT NULL,                -- target channel (canal próprio)
    candidate_title VARCHAR NOT NULL,
    rank_position   INTEGER NOT NULL,                -- 1..N within the suggest call
    predicted_multiplier DOUBLE,                     -- model score from Fase 3
    transcript_hash VARCHAR,                         -- sha256 of the input transcript (link sugestões à fonte)
    rag_outlier_ids VARCHAR[],                       -- IDs dos outliers usados como referência no prompt
    suggested_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    actual_video_id VARCHAR                          -- preenchido quando o video é publicado (Fase 6)
);

CREATE SEQUENCE IF NOT EXISTS suggestions_id_seq START 1;

CREATE INDEX IF NOT EXISTS idx_suggestions_channel ON suggestions(channel_id);
CREATE INDEX IF NOT EXISTS idx_suggestions_actual  ON suggestions(actual_video_id);
