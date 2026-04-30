-- migration 004: features computed per video.
-- Separated from `videos` so it can be dropped/rebuilt without touching ingest data.
-- Title-level features ship in this migration; embeddings + topics will land later
-- in the same table as additional columns.

CREATE TABLE IF NOT EXISTS video_features (
    video_id              VARCHAR PRIMARY KEY,

    -- generic title shape
    char_len              INTEGER,
    word_count            INTEGER,
    has_number            BOOLEAN,
    has_emoji             BOOLEAN,
    has_question_mark     BOOLEAN,
    has_caps_word         BOOLEAN,        -- any token with 3+ consecutive uppercase letters
    caps_ratio            DOUBLE,         -- uppercase chars / total chars
    has_first_person      BOOLEAN,        -- eu/meu/minha/nós/nosso/nossa

    -- niche-specific (per CLAUDE.md Fase 2)
    has_explained_keyword BOOLEAN,        -- explicad@/final explicad@/entenda/explicação
    has_ranking_keyword   BOOLEAN,        -- top/melhores/piores/ranking
    has_curiosity_keyword BOOLEAN,        -- você não sabia/ninguém fala/verdade por trás/por que
    has_extreme_adjective BOOLEAN,        -- perturbador/insano/absurdo/chocante/aterrorizante/brutal

    -- sentiment (left NULL until pysentimiento is wired up — heavier dep)
    sentiment_score       DOUBLE,

    computed_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
