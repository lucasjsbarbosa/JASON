-- migration 012: title_to_theme_dist
--
-- Cosine similarity entre title_embedding e centroide dos outliers (p>=90)
-- do MESMO theme_id. Mede "quao prototipico do subgenero vencedor este
-- titulo esta". Sinal ortogonal a caps_ratio / has_explained: captura
-- semantica vs estrutura.
--
-- Range: [-1, +1] tipicamente, mas como embeddings sao L2-normalized e
-- centroide e re-normalized, fica em [0, 1] na pratica.
-- Default 0.0 para videos sem theme_id ou sem outliers suficientes (<5)
-- para formar centroide confiavel.

ALTER TABLE video_features ADD COLUMN IF NOT EXISTS title_to_theme_dist DOUBLE;
