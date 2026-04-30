-- migration 011: arousal + flesch + thumb aesthetics.
--
-- Phase 2 do plano de features paper-backed:
--
-- arousal_score    : intensidade emocional (Berger & Milkman 2012). Polaridade
--                    (sentiment_score) sozinha e fraca; arousal carrega o
--                    signal real de viralidade. Range [0, 1].
-- flesch_reading_ease : Fernandez-Huerta adaptation pra PT-BR via textstat.
--                    Banerjee 2024 mostra interacao positiva readability x
--                    emocao. Range [0, 100], maior = mais facil.
-- thumb_brightness : media de luminancia (rank #1 em Visual Attributes paper).
-- thumb_contrast   : std de luminancia (rank #2 paper).
-- thumb_colorfulness : Hasler-Susstrunk 2003. Rank #3.
-- thumb_face_largest_pct : area da maior face / area do frame. Reaction-face
--                    e padrao vencedor no nicho.

ALTER TABLE video_features ADD COLUMN IF NOT EXISTS arousal_score          DOUBLE;
ALTER TABLE video_features ADD COLUMN IF NOT EXISTS flesch_reading_ease    DOUBLE;
ALTER TABLE video_features ADD COLUMN IF NOT EXISTS thumb_brightness       DOUBLE;
ALTER TABLE video_features ADD COLUMN IF NOT EXISTS thumb_contrast         DOUBLE;
ALTER TABLE video_features ADD COLUMN IF NOT EXISTS thumb_colorfulness     DOUBLE;
ALTER TABLE video_features ADD COLUMN IF NOT EXISTS thumb_face_largest_pct DOUBLE;
