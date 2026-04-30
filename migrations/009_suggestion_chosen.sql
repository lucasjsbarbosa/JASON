-- migration 009: capturar qual candidato a usuária escolheu publicar.
--
-- Por quê: title_tests do Test & Compare nativo do YouTube exige 5-7 dias
-- por teste; sinal de "qual candidato você escolheu publicar" é capturável
-- imediatamente e diz se o modelo concorda com o humano.
--
-- chosen_at marca a row como escolhida; rank vem do próprio rank_position
-- da row. Aceita escolha de QUALQUER posição (não só top-3) — o sinal mais
-- valioso é "humano discordou do modelo" (escolheu rank #5 em vez de #1).

ALTER TABLE suggestions ADD COLUMN IF NOT EXISTS chosen_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_suggestions_chosen ON suggestions(chosen_at);
