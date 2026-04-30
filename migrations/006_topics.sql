-- migration 006: BERTopic two-layer assignments per video.
-- Layer A (theme): titles with proper-name masking → captures *themes*
--   (possessão, slasher, found footage, etc.). Subgenre proxy.
-- Layer B (franchise): raw titles → captures *franchises* that go viral
--   (Invocação do Mal, Sobrenatural, Hereditário, etc.).
--
-- Outlier topic id is -1 in BERTopic; we keep it to mean "noise / unassigned".

ALTER TABLE video_features ADD COLUMN IF NOT EXISTS theme_id      INTEGER;
ALTER TABLE video_features ADD COLUMN IF NOT EXISTS theme_label   VARCHAR;
ALTER TABLE video_features ADD COLUMN IF NOT EXISTS franchise_id  INTEGER;
ALTER TABLE video_features ADD COLUMN IF NOT EXISTS franchise_label VARCHAR;

CREATE INDEX IF NOT EXISTS idx_features_theme     ON video_features(theme_id);
CREATE INDEX IF NOT EXISTS idx_features_franchise ON video_features(franchise_id);
