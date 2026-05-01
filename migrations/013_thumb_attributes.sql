-- migration 013: VLM-annotated thumb attributes (hard-edge schema)
--
-- Visual features measuradas no thumb_aesthetics.py sao continuos low-level
-- (brightness, contrast). Faltam atributos de packaging que so um VLM enxerga:
-- "tem texto?", "rosto reativo?", "estetica found-footage vs slasher?".
--
-- Schema 6-attribute (hard-edge: cada uma e binaria ou enum curto pra reduzir
-- variancia entre runs):
--
--   has_text_overlay    : BOOLEAN   - texto grande sobreposto (titulo/explicado)
--   face_emotion        : VARCHAR   - reactive|neutral|absent
--   composition_style   : VARCHAR   - reaction|cinematic|collage|screenshot|other
--   color_palette       : VARCHAR   - high_saturation|desaturated|monochrome|red_dominant
--   has_subject_arrow   : BOOLEAN   - seta/circulo apontando pra algo
--   subgenre_signal     : VARCHAR   - found_footage|slasher|gore|paranormal|crime|other
--
-- Custo: ~$15 pra 21k thumbnails via Claude Sonnet 4.5 vision (input ~120k
-- tokens/100 imgs em batch). Annotator roda em batches, salva incremental.

CREATE TABLE IF NOT EXISTS thumb_attributes (
    video_id            VARCHAR PRIMARY KEY,
    has_text_overlay    BOOLEAN,
    face_emotion        VARCHAR,
    composition_style   VARCHAR,
    color_palette       VARCHAR,
    has_subject_arrow   BOOLEAN,
    subgenre_signal     VARCHAR,
    annotated_at        TIMESTAMP,
    model_version       VARCHAR
);

CREATE INDEX IF NOT EXISTS idx_thumb_attrs_face ON thumb_attributes (face_emotion);
CREATE INDEX IF NOT EXISTS idx_thumb_attrs_composition ON thumb_attributes (composition_style);
CREATE INDEX IF NOT EXISTS idx_thumb_attrs_subgenre ON thumb_attributes (subgenre_signal);
