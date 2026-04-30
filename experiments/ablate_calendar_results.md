# Ablation: feature group contributions

> Run em 2026-04-30 com pool expandido (41 canais, 16098 multipliers, 1594 outliers oficiais p≥90).
> Otimização: Optuna `best_params.json` + 5 seeds + stratified split.

## Suspeita levantada (review externo)

> Top-4 feature importances (gain): `days_to_nearest_horror_release`, `caps_ratio`,
> `duration_s`, `char_len`. Três delas são quase channel/calendar level, não craft
> de título. **O modelo pode estar aprendendo "canal X publica próximo de release
> e usa títulos longos" mais que "este título é bom"**.

## Resultados

| Variante | Features dropadas | n_train / n_val | Spearman | Pairwise |
|---|---|---|---|---|
| Baseline | (nenhuma) | 12879 / 3219 | 0.3238 | **0.6200** |
| No calendar | days_to_nearest_horror_release, published_hour, published_dow, is_halloween_week, is_friday_13_week | 12879 / 3219 | 0.2972 | 0.6095 |
| No calendar + no duration | (5 calendar) + duration_s | 12879 / 3219 | 0.2326 | 0.5839 |

## Deltas

| Transição | Δ pairwise | Carregado por |
|---|---|---|
| Baseline → No calendar | **−1.0pp** | 5 calendar features |
| No calendar → No calendar+no duration | **−2.6pp** | duration_s sozinho |
| Pairwise sem calendar+duration vs random (0.50) | **+8.4pp** | tudo que sobrou (título features + clusters + subs_bucket) |

## Conclusão

**Suspeita do "when-to-upload model" parcialmente refutada.** Calendar features (5 colunas: distância de release, hora, dia da semana, halloween, sexta-13) carregam **apenas 1pp** de signal. Não é o que está dominando.

Pelo contrário:

- **Título + clusters + subs_bucket carregam ~8.4pp acima do random** (≈ 70% do signal do modelo).
- **Duration sozinho carrega 2.6pp** (≈ 22%) — feature controlada pelo criador, não é "when".
- **Calendar carrega 1pp** (≈ 8%) — sinal real mas pequeno.

## Implicação prática

**Investir em mais features de título compensa** (não é noise). O modelo está
genuinamente aprendendo padrões de craft de título, não só calendário.

Próximos candidatos de feature de título (não testados, mas faz sentido investir):

- `sentiment_score` via `pysentimiento` (PT-BR). Já declarado em CLAUDE.md, ainda não computado.
- Distância semântica do título ao centroide do `theme_id` detectado (medida de "quão prototípico do subgênero").
- "Posição do vídeo na franquia/canal" (1º vídeo de uma série vs 5º).
- N-grama de palavras presentes em outliers do mesmo tema.

## Distribuição do pool (sanity check de tier_1 esparso)

A preocupação era que `tier_1` (faixa da @babygiulybaby) tivesse sample insuficiente
pro pairwise intra-bucket ser confiável. Pós-expansão dos 16 canais novos:

| Bucket | n vídeos no pool com multiplier |
|---|---|
| tier_0 (<1k) | 199 |
| tier_1 (1k–10k) | 1502 |
| tier_2 (10k–100k) | 3529 |
| tier_3 (100k–1M) | 4878 |
| tier_4 (1M+) | 5990 |

Tier_1 com 1502 vídeos no pool. Pairs intra-bucket são abundantes; o pairwise=0.620
agregado **é honesto** pra esse bucket também. A preocupação levantada está mitigada.

## Persistência

- Artefatos por variante: `src/jason/models/artifacts/ablation_<variant>/`
- JSON completo: `experiments/ablate_calendar_results.json`
- Modelo de produção (`multiplier_v1`) **não** foi alterado por essa rodada.
