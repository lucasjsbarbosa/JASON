-- migration 003: TMDb horror release calendar.
-- Feeds the `days_to_nearest_horror_release` feature in Fase 3.
-- Per CLAUDE.md, the strongest seasonal driver in this niche is theatrical /
-- streaming releases of horror titles — much stronger than fixed dates like
-- Halloween or Friday-the-13th (which we keep as separate boolean features).

CREATE TABLE IF NOT EXISTS horror_releases (
    tmdb_id      INTEGER PRIMARY KEY,
    title        VARCHAR NOT NULL,
    release_date DATE NOT NULL,
    release_type VARCHAR,                 -- discover-filter applied (e.g. '3|4' = theatrical|digital)
    country      VARCHAR,                 -- region filter from the TMDb call (e.g. 'BR')
    ingested_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_horror_releases_date
    ON horror_releases(release_date);
