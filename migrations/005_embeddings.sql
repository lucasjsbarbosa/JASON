-- migration 005: title + thumbnail embedding columns on video_features.
-- Fixed-size arrays let DuckDB's vector-search extensions index these later
-- (e.g. for the RAG retrieval in Fase 4 — top-N similar outliers).

-- Title embeddings: 768 dims from sentence-transformers
--   paraphrase-multilingual-mpnet-base-v2 (PT-BR friendly)
ALTER TABLE video_features ADD COLUMN IF NOT EXISTS title_embedding FLOAT[768];

-- Thumbnail embeddings: 512 dims from OpenCLIP ViT-B-32
ALTER TABLE video_features ADD COLUMN IF NOT EXISTS thumb_embedding FLOAT[512];
