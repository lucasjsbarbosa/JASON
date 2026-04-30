-- migration 010: paper-backed extensions to title features.
--
-- Phase 1 do plano: title features puramente regex/lexical, sem novas
-- dependencies. Pos research mostrou que esses 4 features tem fundamentação
-- empírica (Banerjee & Urminsky 2024 readability+emoção, Chakraborty et al.
-- 2016 clickbait morphology, Loewenstein 1994 curiosity gap).
--
-- arousal_score e flesch (fernandez-huerta) virão em phases seguintes.

ALTER TABLE video_features ADD COLUMN IF NOT EXISTS avg_word_length    DOUBLE;
ALTER TABLE video_features ADD COLUMN IF NOT EXISTS definite_ref_count INTEGER;
ALTER TABLE video_features ADD COLUMN IF NOT EXISTS forward_ref_count  INTEGER;
ALTER TABLE video_features ADD COLUMN IF NOT EXISTS superlative_density DOUBLE;
