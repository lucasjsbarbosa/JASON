# JASON — YouTube Growth Engine

> *"They call him JSON. He parses your YouTube data and won't stop until your CTR is dead."*

## 0. Contexto

**JASON** é um sistema interno de growth analytics e geração de títulos para o canal de YouTube em PT-BR **@babygiulybaby** (reviews e análises de filmes de terror). O nome é trocadilho com `JSON` (formato de dados que o sistema consome via APIs) e Jason Voorhees, que combina com o nicho.

O objetivo é sair do achismo e usar dados + ML para decidir título, thumbnail e tema dos vídeos.

**Identidade do projeto** (para README, logs, dashboard):
- Nome: `JASON`
- Pacote Python: `jason` (em `src/jason/`)
- CLI: `jason --help`
- Tom: técnico mas com piscadas pro tema de terror. Mensagens de erro podem ter personalidade ("Jason couldn't find that channel. He's still hunting."). Sem exagero — comentários de código permanecem profissionais.

**Filosofia do projeto:**
- O jogo do YouTube em 2026 é **packaging** (título + thumbnail) e **outlier analysis**, não SEO/keywords. ~70% das views vêm da homepage, não da busca.
- A métrica que importa é **outlier multiplier** (`views_do_video / mediana_views_recentes_do_canal`), não views absolutos.
- O Test & Compare nativo do YouTube já roda A/B test de título e thumbnail (até 3 variantes, por watch-time share). Nosso sistema **alimenta** o Test & Compare com candidatos de alta qualidade — não substitui ele.

**Contexto do canal:**

- `NICHO_DO_CANAL`: **reviews e análises de filmes de terror, séries do gênero, curiosidades e bastidores de produções de horror**. Conteúdo em PT-BR. O nicho tem subdivisões importantes que o sistema deve aprender a distinguir: (a) review de lançamento, (b) análise/explicação de filmes antigos ou obscuros, (c) listas e rankings ("Top 10 piores...", "filmes mais perturbadores"), (d) curiosidades e bastidores, (e) crimes reais que inspiraram filmes (overlap com true crime). Cada subdivisão tem padrões de título e thumbnail próprios.
- `TAMANHO_ATUAL`: ~3.500 inscritos. Canal pequeno-médio. Implicação: a janela de impressões própria é estreita, então o A/B test nativo do YouTube vai demorar 5-7 dias para fechar e às vezes vai dar inconclusivo. **A maior parte do sinal vai vir dos canais vizinhos**, não dos vídeos próprios. Priorize ingestão larga de outliers do nicho.
- `CHANNEL_ID_PROPRIO`: UCjLen2Tbkj91nLnlD6nmnZQ — `@babygiulybaby` é o handle, não o ID. Ver seção "Conversão de handles para IDs" abaixo.
- `CANAIS_VIZINHOS`: lista inicial fornecida abaixo. Estratégia: misturar canais grandes do nicho (alvo aspiracional, padrões de packaging vencedor) com canais médios (comparação mais justa de outlier multiplier).

**Lista inicial de canais vizinhos** (em ordem de prioridade — começar pelos médios, expandir para os grandes depois):

Handles confirmados de canais brasileiros do nicho de terror/análise/curiosidades sombrias:

```
# Médios — comparação direta para outlier analysis
@HoradoTerror              # Hora do Terror — terror, horror, suspense no cinema
@RefugioCult               # Refúgio Cult — cinema sombrio e bizarro
@CapraPeckinpah            # Capra Peckinpah — cinema cult/terror
@Carbosa                   # Carbosa — terror
@ClassicosdoTerror         # Clássicos do Terror
@CineAntiqua               # Cine Antiqua — cinema antigo, horror clássico
@EddyKaos                  # Eddy Kaos
@BabyMonster               # Baby Monster — terror
@BKOff                     # BK Off
@LeratéAmanhecer           # Ler Até Amanhecer (Joici Rodrigues) — terror + crimes

# Grandes — referência de packaging vencedor (não usar como baseline de comparação direta)
@JuMCassini                # Ju Cassini — 3.2M, bizarro/terror/crimes
@MarcosCamposOficial       # Marcos Campos (ex-O Insólito) — true crime + terror
@JaquelineGuerreiro        # Jaqueline Guerreiro — crimes + sobrenatural
@IconografiaDaHistoria     # Joel Paviotti — análises profundas

# A completar pela própria namorada (tarefa antes da Fase 1):
# - 5-10 canais que ela já assiste no nicho
# - 5-10 canais que aparecem em "Canais relacionados" na sidebar dos canais acima
# Meta: 25-30 canais no total, com pelo menos 15 na faixa 1k-50k inscritos
```

### Conversão de handles para IDs (faça antes da Fase 1)

A YouTube Data API só aceita channel IDs no formato `UC...` (24 chars). Handles `@xxx` não funcionam diretamente em todos os endpoints. Três formas de converter:

1. **Manual (uma vez por canal)**: abre `youtube.com/@HANDLE`, vai em "Sobre" → "Compartilhar canal" → "Copiar ID do canal". Boa para a lista inicial.
2. **Via API**: `channels.list?forHandle=@HANDLE&part=id`. Custa 1 unidade. **Use isso no projeto** — criar um utilitário `src/yt_growth/ingestion/handle_resolver.py` na Fase 1 que pega uma lista de handles e devolve IDs, com cache em DuckDB pra não gastar quota repetida.
3. **View source da página do canal**: o ID aparece no HTML em `"channelId":"UC..."`. Funciona mas é frágil.

Para o `CHANNEL_ID_PROPRIO` (@babygiulybaby), use o método 1 agora e cole o `UC...` no `.env` como `OWN_CHANNEL_ID`.

---

## 1. Objetivo do sistema

Um pipeline que faz quatro coisas, nessa ordem:

1. **Coleta** todos os vídeos dos canais vizinhos + do canal próprio via YouTube Data API.
2. **Detecta outliers** no nicho — vídeos com multiplier ≥ 3x — e extrai padrões.
3. **Prevê** o multiplier esperado de um título candidato (regressão treinada nos dados acima).
4. **Gera** 10 títulos para um próximo vídeo (a partir da transcrição + tópico), ranqueia pelo modelo preditivo, devolve top 3 para mandar pro Test & Compare.

Tudo acessível por um dashboard local + CLI.

---

## 2. Stack

- **Linguagem**: Python 3.11+
- **Gerenciador**: `uv` (mais rápido que pip/poetry, padrão moderno)
- **Banco**: DuckDB (zero setup, ótimo para análise; migra pra Postgres se virar produção)
- **APIs externas**:
  - YouTube Data API v3 (chave de API, grátis até 10k unidades/dia)
  - YouTube Analytics API (OAuth2, só pro canal próprio — métricas privadas como CTR e AVD)
  - Anthropic API (Claude Sonnet 4.5 ou superior, para geração de títulos)
  - Whisper local (`faster-whisper`) para transcrição — evita custo de API
- **ML**:
  - `sentence-transformers` com modelo `paraphrase-multilingual-mpnet-base-v2` (funciona bem em PT-BR)
  - `lightgbm` para o regressor
  - `bertopic` para topic modeling
  - `open_clip_torch` para embeddings de thumbnail
- **Servidor**: FastAPI (API interna) + Streamlit (dashboard rápido). Sem Next.js inicialmente — overkill.
- **Testes**: `pytest`. Cobertura mínima nos módulos de coleta e features.
- **Lint/format**: `ruff` (substitui black + isort + flake8).

---

## 3. Estrutura de pastas

```
jason/
├── CLAUDE.md                   # este arquivo
├── pyproject.toml              # uv + dependências
├── .env.example                # variáveis de ambiente (chaves de API)
├── README.md                   # quickstart pro usuário humano
├── data/
│   ├── raw/                    # respostas cruas das APIs (jsonl)
│   ├── thumbnails/             # imagens baixadas
│   ├── transcripts/            # whisper output (.txt + .json com timestamps)
│   └── warehouse.duckdb        # banco analítico
├── src/jason/
│   ├── __init__.py
│   ├── config.py               # carrega .env, settings centralizadas
│   ├── ingestion/
│   │   ├── youtube_data.py     # cliente YT Data API v3
│   │   ├── youtube_analytics.py # cliente YT Analytics API (OAuth)
│   │   ├── handle_resolver.py  # @handle -> UC... com cache
│   │   ├── thumbnails.py       # download
│   │   └── transcripts.py      # faster-whisper wrapper
│   ├── features/
│   │   ├── outliers.py         # cálculo de multiplier, detecção
│   │   ├── title_features.py   # length, números, emojis, sentimento, etc.
│   │   ├── embeddings.py       # sentence-transformers + CLIP
│   │   └── topics.py           # BERTopic em duas camadas
│   ├── models/
│   │   ├── train.py            # treina LightGBM
│   │   ├── predict.py          # carrega modelo, prediz multiplier
│   │   └── artifacts/          # modelos treinados (.lgb)
│   ├── generation/
│   │   ├── rag.py              # busca top-N títulos outliers similares
│   │   └── titles.py           # chama Anthropic API com prompt estruturado
│   ├── api/
│   │   └── main.py             # FastAPI app
│   ├── dashboard/
│   │   └── app.py              # Streamlit
│   └── cli.py                  # entrypoint (typer)
├── tests/
└── notebooks/                  # exploração ad-hoc
```

---

## 4. Fases de implementação

Implementar **uma fase por vez**. Não pular pra próxima sem testes da anterior passando. Cada fase deve terminar com um commit limpo e um exemplo rodando.

### Fase 0 — Setup (1 sessão)

- [ ] `uv init` + dependências base
- [ ] `.env.example` com todas as chaves necessárias documentadas
- [ ] `config.py` usando `pydantic-settings`
- [ ] `cli.py` com `typer`, comando placeholder `jason --help` funcional
- [ ] Schema inicial do DuckDB em `migrations/001_init.sql`:
  - `channels` (id, handle, title, subs, niche_tag) — `subs_bucket` é **derivado on-the-fly** de `subs` via helper `bucket_of(subs)` (log-bin: `tier_0` 0-1k, `tier_1` 1k-10k, `tier_2` 10k-100k, `tier_3` 100k-1M, `tier_4` 1M+). Não armazenar como coluna — `subs` cresce com o tempo e bucket cristalizado fica stale (canal de 3.5k vira `tier_2` em meses).
  - `videos` (id, channel_id, title, description, published_at, duration_s, **is_short**, thumbnail_url) — **sem métricas aqui**. Métricas vivem em snapshot.
  - `video_stats_snapshots` (video_id, captured_at, days_since_publish, views, likes, comments) — **chave (video_id, captured_at)**. Toda métrica histórica passa por aqui. Job da Fase 1 popula. Multiplier da Fase 2 usa `views_at_28d` (interpolado se não tiver snapshot exato).
  - `title_tests` (video_id, variant_id, title, thumbnail_path, watch_time_share, **result**, **confidence_pct**) — `result` enum: `winner`, `loser`, `inconclusive`. **Semântica**: pra teste concluído com significância, exatamente 1 linha tem `winner` e as outras N-1 têm `loser`. Pra teste sem significância (Test & Compare deu inconclusive), **todas** as N linhas têm `inconclusive`.
  - `outliers` (video_id, multiplier, percentile_in_channel, computed_at) — guardar tanto multiplier absoluto quanto percentil intra-canal.
  - **`migrations/003_horror_releases.sql` vem na Fase 1**, não na Fase 0: tabela `horror_releases` (tmdb_id, title, release_date, release_type, country, ingested_at). Necessária pra `days_to_nearest_horror_release` da Fase 3, mas só é populada quando o ingest TMDb existir.
- [ ] `pytest` rodando vazio sem erro

### Fase 1 — Ingestão (2-3 sessões)

- [ ] `handle_resolver.py` **PRIMEIRO**: dado um `@handle`, devolve `UC...` via `channels.list?forHandle=`. Cache em DuckDB (tabela `handle_cache`). Tem que existir antes de qualquer ingestão.
- [ ] `youtube_data.py`: cliente que dado um `channel_id`, busca todos os vídeos públicos via `playlistItems` do uploads playlist (paginar com `pageToken`). Respeitar quota: `part=snippet,statistics,contentDetails` numa só chamada. Cache local em jsonl antes de inserir no banco. **Detectar Shorts**: `duration_s <= 60` OU `#shorts` no título/descrição → flag `is_short=true`.
- [ ] **Job de snapshot diário** (`stats_snapshot.py`): roda `videos.list?part=statistics` em batch de 50 IDs por chamada para todos os vídeos rastreados, escreve linha nova em `video_stats_snapshots` com `captured_at=now`, `days_since_publish=now-published_at`. Esse é o coração da correção do viés de idade — sem ele, todo o ML downstream tá comprometido. Idealmente roda diário; mínimo aceitável é semanal.
- [ ] CLI: `jason ingest channels --ids <id1,id2,...>` — popula `channels` e `videos` + primeiro snapshot.
- [ ] CLI: `jason ingest neighbors --file canais.txt` — versão batch (aceita handles, resolve internamente).
- [ ] CLI: `jason snapshot run` — invoca o job de snapshot manualmente.
- [ ] `thumbnails.py`: download da maxres thumbnail, salva em `data/thumbnails/{video_id}.jpg`. Skip se já existe.
- [ ] `transcripts.py`: `faster-whisper` modelo `large-v3` em GPU se disponível, fallback `medium` em CPU. Só transcrever vídeos do canal próprio + top-50 outliers do nicho. Salvar em `data/transcripts/{video_id}.json`.
- [ ] `youtube_analytics.py`: OAuth flow (interação manual primeira vez — documentar no README). Pull diário de CTR, AVD, retention curve do canal próprio.
- [ ] **`migrations/003_horror_releases.sql` + ingest TMDb release calendar**: cria tabela `horror_releases` (tmdb_id, title, release_date, release_type, country, ingested_at). CLI `jason ingest tmdb-releases --window-past 365 --window-future 180` puxa releases de horror dos últimos 12 meses + próximos 6 meses (filtrado por `with_genres=27` Horror, `with_release_type=3,4` theatrical/digital). Pré-requisito da feature `days_to_nearest_horror_release` da Fase 3.
- [ ] **Teste de aceitação**: rodar para um canal vizinho conhecido e validar que o número de vídeos no banco bate com o YouTube. Rodar snapshot 2x em dias diferentes e validar que existem 2 linhas por vídeo em `video_stats_snapshots` com `views` crescentes.

### Fase 2 — Feature engineering (1-2 sessões)

- [ ] `outliers.py`:
  - **Função `views_at_age(video_id, target_days=28)`**: dado um vídeo e uma idade-alvo (ex: 28 dias), retorna `views` interpolados linearmente entre os dois snapshots mais próximos em `video_stats_snapshots`. Vídeos com idade < target_days são **excluídos** do cálculo de outlier (não há sinal estabilizado ainda).
  - **Função `compute_multiplier(channel_id)`**: para cada vídeo elegível do canal, `multiplier = views_at_28d / mediana(views_at_28d dos 30 vídeos imediatamente anteriores do mesmo canal)`. Salva em `outliers.multiplier`. **Fallback**: se houver menos de **10 vídeos anteriores elegíveis** (ex: canal jovem ou janela de snapshots ainda não madura), `multiplier = NULL` e o vídeo **não** entra em `outliers` — sem baseline confiável o sinal é ruído.
  - **Função `compute_percentile(channel_id, window_days=90)`**: para cada vídeo do canal, calcula seu percentil de multiplier dentro da janela. Salva em `outliers.percentile_in_channel`. Outlier "oficial" = percentil ≥ 90 dentro do canal — não threshold absoluto. Mantemos o multiplier numérico como feature, mas a flag categórica é por percentil.
- [ ] `title_features.py`: extrai por título: `char_len`, `word_count`, `has_number`, `has_emoji`, `has_question_mark`, `has_caps_word`, `caps_ratio` (% de caracteres em maiúscula), `sentiment_score` (`pysentimiento` PT), `has_first_person` (eu/meu/minha), e específicas do nicho: `has_explained_keyword` (regex: explicado|final explicado|entenda|explicação), `has_ranking_keyword` (top|melhores|piores|ranking), `has_curiosity_keyword` (você não sabia|ninguém fala|verdade por trás|por que), `has_extreme_adjective` (perturbador|insano|absurdo|chocante|aterrorizante).
- [ ] `embeddings.py`:
  - Títulos: `paraphrase-multilingual-mpnet-base-v2`, salva `title_embedding` (768 dim).
  - Thumbnails: OpenCLIP `ViT-B-32`, salva `thumb_embedding` (512 dim).
- [ ] `topics.py`: BERTopic em **duas camadas**:
  - Camada A (temas): roda sobre títulos com nomes próprios mascarados (NER + matching contra base de filmes — pode ser TMDb aqui ou simplesmente lista manual de franquias populares de terror). Captura *temas* (possessão, slasher, found footage).
  - Camada B (franquias): roda sobre títulos crus. Captura *franquias virais* (Invocação do Mal, Sobrenatural, Hereditário).
  - Cada vídeo recebe `theme_id` e `franchise_id`. Os dois entram como features no modelo da Fase 3. **`theme_id` da Camada A funciona como proxy de subgênero** — não precisa do TMDb pra isso.
- [ ] CLI: `jason features compute --all`
- [ ] **Teste**: query `SELECT theme_label, AVG(multiplier), COUNT(*) FROM videos JOIN outliers USING(video_id) JOIN themes USING(theme_id) GROUP BY 1 HAVING COUNT(*) >= 5 ORDER BY 2 DESC LIMIT 10` deve retornar temas com multiplier sensato e separar slasher de found footage de possessão.

### Fase 3 — Modelo preditivo (1 sessão)

- [ ] `train.py`: LightGBM regressor com target = `log1p(multiplier)`. **Filtrar Shorts** do treino — `WHERE is_short = false`. Se houver volume razoável de Shorts (>500), treinar modelo separado depois.
- [ ] **Features**:
  - Tudo de `title_features` (incluindo as flags específicas do nicho).
  - Cluster do `title_embedding` (k-means k=20).
  - Cluster do `thumb_embedding` (k-means k=20).
  - `theme_id` (Camada A do BERTopic — proxy de subgênero).
  - `franchise_id` (Camada B — pega o pico de viralidade de franquias hot).
  - `duration_s`, `published_hour`, `published_dow`.
  - **`subs_bucket`** do canal — derivado on-the-fly de `channels.subs` via `bucket_of()`, não armazenado. Corrige o problema de aprender só padrão de canal grande.
  - **`days_to_nearest_horror_release`**: distância em dias do release de filme/série de terror grande mais próximo. Precisa de ingest do TMDb release calendar (filtrado por `genres=Horror` + `with_release_type=3,4` para estréia em cinema/streaming) — adicionar no fim da Fase 1. Halloween e Sexta-13 ficam como features booleanas separadas (`is_halloween_week`, `is_friday_13_week`), bonus.
- [ ] **Split temporal**: ordenar por `published_at`, 80% mais antigos → train, 20% mais recentes → val. Não aleatório.
- [ ] **Métricas**:
  - Spearman correlation no val (saúde geral).
  - **Pairwise ranking accuracy intra-`subs_bucket`**: pares de vídeos do mesmo bucket de tamanho de canal — dos pares onde o modelo prediz qual é o melhor, quantos % acerta? Esse é o número que importa, porque ranquear título de canal de 3.5k pelos padrões de canal de 3M é exatamente o erro a evitar.
- [ ] Gravar feature importance, salvar modelo em `models/artifacts/multiplier_v1.lgb`.
- [ ] `predict.py`: função `score_title(title, channel_id, thumbnail_path=None) -> float`. Internamente lê `channels.subs` e computa `subs_bucket = bucket_of(subs)` na hora pra usar como feature.
- [ ] CLI: `jason model train` e `jason model score --title "..." --channel ...`.
- [ ] **Importante**: o modelo NÃO precisa prever views absolutos bem (variância gigante). Precisa **ranquear** candidatos dentro de uma escala parecida com a do canal alvo. A métrica intra-bucket é o que valida isso.

### Fase 4 — Geração de títulos (1 sessão)

- [ ] `rag.py`: dado um tópico ou transcrição, calcula embedding, faz busca por similaridade nos top-200 vídeos do nicho com `percentile_in_channel >= 90` (ou seja, outliers reais), retorna os 20 mais similares.
- [ ] `titles.py`: prompt para Claude estruturado em **partes estáticas + variável** para usar prompt caching:
  - **Estático (com `cache_control: {"type": "ephemeral"}`)**:
    1. System: instrução de papel, regras de geração (estilo do canal, PT-BR, diversidade de estrutura).
    2. Contexto do canal: tom, nicho, exemplos de títulos vencedores próprios da @babygiulybaby.
    3. 20 títulos outliers do nicho como referência de estrutura (atualizados semanalmente, mas estáveis dentro de uma sessão).
  - **Variável (sem cache)**:
    4. Resumo de 200 palavras da transcrição do vídeo novo + tema/franquia detectada.
  - Esse split corta ~80% do custo a partir da segunda chamada e melhora latência. Documentação Anthropic: `https://docs.claude.com/en/docs/build-with-claude/prompt-caching`.
- [ ] Pipeline completo: `jason suggest --transcript caminho.txt` → 10 títulos gerados → ranqueados pelo modelo da Fase 3 (passando o `channel_id` próprio para o `subs_bucket` correto) → top 3 retornados com score + percentil estimado dentro do `subs_bucket`.
- [ ] Persistir cada sugestão em tabela `suggestions` para fechar o loop depois.

### Fase 4.5 — Seleção de thumbnails (1 sessão)

Thumbnail é o maior driver de CTR no YouTube — maior que título. JASON não vai gerar thumbnails do zero (caro, qualidade inconsistente), mas vai **sugerir frames candidatos do próprio vídeo** alinhados com padrões vencedores do nicho.

- [ ] `frame_extractor.py`: dado o vídeo (precisa do arquivo local ou URL para `yt-dlp` baixar versão de baixa resolução), usa `ffmpeg` para extrair candidatos:
  - Frames a cada 5% da duração (20 candidatos base).
  - Filtros: descartar frames muito escuros (média de luminância < threshold) e muito borrados (variância de Laplaciano baixa).
- [ ] `frame_scorer.py`:
  - **Score de saliência**: `face-detection` via `mediapipe` ou `retinaface`. Frames com 1-2 rostos grandes e centralizados ganham boost (padrão de packaging vencedor no nicho de terror — reaction face funciona muito).
  - **Score de similaridade com outliers do nicho**: embedding CLIP do frame vs cluster centroid das thumbnails de vídeos com `percentile_in_channel >= 90` no mesmo `theme_id`. Maior similaridade = mais alinhado com o que viraliza nesse subgênero.
  - **Score combinado**: `0.4 * face_score + 0.6 * outlier_similarity` (ajustar pesos depois).
- [ ] `text_overlay_advisor.py`: sugere padrão de overlay de texto baseado nas thumbnails outliers do mesmo `theme_id`. Output é declarativo, não imagem renderizada — exemplo: `{"text_present": true, "text_position": "top_left", "text_color": "yellow", "max_words": 3, "examples": ["EXPLICADO", "FINAL", "PERTURBADOR"]}`. A pessoa edita no Photoshop/Canva. Não tentar gerar a thumb finalizada — escopo vira muito maior.
- [ ] CLI: `jason thumbs suggest --video-path <path>` → top 3 frames + arquivo JSON com sugestão de overlay. Salvar em `data/thumb_suggestions/{video_id}/`.
- [ ] **Importante**: não tentar usar modelos generativos (DALL-E, SD) na v1. Frame real do vídeo + sugestão de overlay é 80% do valor com 20% da complexidade.

### Fase 5 — Dashboard (1 sessão)

Streamlit com 5 abas:

1. **Outliers do nicho** — tabela ranqueada por `percentile_in_channel` dos últimos 30 dias, filtro por canal e por `theme_id`, link pro vídeo no YT, thumbnail inline. Esse é o "feed do que o algoritmo está empurrando".
2. **Performance própria** — gráfico de CTR, AVD, retention dos vídeos dela ao longo do tempo (puxa do Analytics API). Sobreposição: linha do tempo de releases de filme/série de terror grandes (TMDb) — fica fácil ver picos de visualização correlacionados com lançamentos.
3. **Title scorer** — input livre: cola um título, retorna score do modelo + percentil estimado dentro do `subs_bucket` do canal.
4. **Sugerir título** — upload de transcrição (ou cola texto), retorna top 3 títulos com explicação.
5. **Sugerir thumbnail** — upload do vídeo (ou path local), retorna top 3 frames candidatos + sugestão de overlay de texto.

### Fase 6 — Loop de feedback (1 sessão)

- [ ] Tabela `title_tests` populada manualmente após cada teste do Test & Compare nativo do YouTube (formulário no Streamlit pra inserir resultado).
- [ ] Job de retreino: `jason model retrain` que reroda toda a pipeline incluindo os novos resultados de A/B test como sinal forte (peso maior na loss).
- [ ] Agendar via cron ou GitHub Actions semanal: ingestão incremental + retreino + relatório por email com top outliers da semana.

---

## 5. Detalhes técnicos importantes

**Quotas da YouTube Data API:**
A quota padrão é 10.000 unidades/dia. `videos.list` custa 1 unidade, `search.list` custa 100. **Nunca use `search`** quando puder usar `playlistItems` (pega o "uploads playlist" do canal e pagina — custa 1 unidade por chamada de até 50 vídeos). Para 30 canais com média de 200 vídeos, dá ~120 chamadas = 120 unidades. Tranquilo.

**OAuth do Analytics API:**
A primeira execução vai abrir browser para consentimento. Salvar token em `~/.config/jason/token.json` e refresh automático depois. Documentar isso no README com screenshots.

**Custos esperados (mensais):**
- YouTube APIs: $0 (dentro da quota grátis)
- Anthropic API: ~$1-5 (geração de título usa poucos tokens)
- Whisper local: $0 (roda em CPU/GPU própria)
- Hosting: $0 inicialmente (rodar local). Se quiser deploy, $5/mês numa VPS Hetzner basta.

**PT-BR specifics:**
- O modelo de embeddings `paraphrase-multilingual-mpnet-base-v2` lida bem com PT, mas se rolar tempo, testar `BERTimbau-large` em pares de validação.
- `pysentimiento` tem modelo PT especificamente.
- Stopwords PT-BR via `nltk.corpus.stopwords.words('portuguese')`, mas para títulos de YT não filtrar muito — palavras curtas ("eu", "meu") são features importantes.

**Especificidades do nicho de terror (importante):**
- **Títulos do nicho costumam usar CAPS, números altos e adjetivos extremos**: "O FILME MAIS PERTURBADOR JÁ FEITO", "10 CENAS QUE FORAM CORTADAS DE...", "POR QUE NINGUÉM FALA DESSE FILME". Isso vai dominar as features de `caps_ratio` e `has_extreme_adjective`. **Não filtrar isso como ruído** — é o sinal real do nicho.
- **Nomes de filmes confundem topic modeling**: por isso a Fase 2 usa BERTopic em duas camadas — Camada A com nomes mascarados (captura *temas*: possessão, slasher, found footage), Camada B sem mascarar (captura *franquias virais*: Invocação do Mal, Hereditário). O `theme_id` da Camada A funciona como **proxy de subgênero** — não precisa de TMDb pra isso. TMDb fica reservado pra outra coisa: release calendar.
- **Lançamentos de cinema/streaming são o maior driver sazonal** — muito mais forte que datas fixas. Por isso a feature `days_to_nearest_horror_release` (vinda do TMDb release calendar, filtrado por gênero Horror + tipo de release theatrical/digital) é a feature sazonal de maior peso. Halloween e Sexta-13 ficam como features booleanas separadas, secundárias.
- **Subgênero precisão fina**: se em algum momento o `theme_id` do BERTopic não estiver granular o suficiente (ex: agrupar slasher e found footage juntos), aí sim vale anotar manualmente uma taxonomia de ~15 subgêneros e classificar via embedding do título+descrição. Mas adiar — começa com BERTopic e mede.
- **Spoilers e formato afetam packaging**: features `has_explained_keyword`, `has_ranking_keyword`, `has_curiosity_keyword` (definidas na Fase 2) capturam isso.
- **Avoid copyright traps**: o canal lida com clipes de filmes — JASON NÃO deve sugerir reproduzir trechos de roteiros, letras de músicas de trilhas, ou texto extenso de sinopses oficiais. Restringir geração a títulos e descrições originais.

**Sobre clickbait vs. quality:**
O modelo treinado em multiplier pode aprender padrões clickbait. Mitigação: o YouTube Test & Compare decide por **watch-time share**, não cliques. Então mesmo que a gente sugira títulos clickbait, o A/B real penaliza eles. O loop de feedback corrige naturalmente.

---

## 6. Critérios de qualidade

- [ ] Toda função pública tem docstring + type hints.
- [ ] Nenhum segredo hardcoded — tudo via `.env` + `config.py`.
- [ ] Cobertura de teste mínima: ingestão (mock das APIs), cálculo de outlier, scoring do modelo.
- [ ] Logs estruturados (`structlog`) com nível configurável.
- [ ] CLI tem `--dry-run` em comandos que escrevem no banco.
- [ ] README com quickstart de 5 minutos: clone, `uv sync`, `cp .env.example .env`, preencher chaves, rodar comando exemplo.
- [ ] Commits atômicos, mensagens em português ou inglês mas consistente.

---

## 7. O que NÃO fazer

- Não implementar autenticação multi-usuário. É single-user, local.
- Não fazer scraping de páginas do YouTube. Só APIs oficiais.
- Não treinar LLM próprio. Anthropic API é mais que suficiente.
- Não otimizar prematuramente — DuckDB aguenta milhões de linhas. Migrar pra Postgres só se houver necessidade real.
- Não fazer deploy em cloud na v1. Roda local primeiro.

---

## 8. Primeira tarefa

Começar pela **Fase 0**. Antes de escrever qualquer código:

1. Confirme que entendeu a arquitetura me explicando em 5 linhas, destacando como o nicho de terror muda algumas escolhas (sazonalidade via release calendar, BERTopic em duas camadas, mascaramento de nomes de filmes).
2. Liste exatamente quais variáveis de ambiente eu vou precisar configurar — incluir já uma `TMDB_API_KEY` (chave grátis em `themoviedb.org/settings/api`) porque a Fase 1 vai precisar pro release calendar.
3. Implemente o utilitário `handle_resolver.py` LOGO no início da Fase 1, antes de ingerir vídeos — assim eu consigo passar a lista de handles do CLAUDE.md direto e ele resolve para IDs com cache.
4. Aí sim começar o setup propriamente dito.

---

## 9. Changelog do spec

Mudanças aplicadas após primeira revisão técnica (registrar aqui qualquer mudança estrutural pra contextualizar escolhas):

- **v1.1**: separação de métricas em `video_stats_snapshots` (corrige viés de idade no multiplier — vídeo antigo não pode ser outlier só por ter acumulado mais views). Multiplier passa a ser calculado em `views_at_28d`. Outlier oficial passa a ser percentil ≥ 90 intra-canal, não threshold absoluto.
- **v1.1**: feature `subs_bucket` no canal + métrica de avaliação intra-bucket. Resolve o problema de treinar com mistura de canais 1k e 3M e ranquear por padrão de canal grande.
- **v1.1**: flag `is_short` + filtragem de Shorts no treino do modelo de long-form. Distribuições incompatíveis.
- **v1.1**: adicionada Fase 4.5 (seleção de thumbnails) — frame extraction + scoring por similaridade com outliers do nicho. Thumbnail é o maior driver de CTR e estava ausente da pipeline de output.
- **v1.1**: prompt caching no Claude na Fase 4 (partes estáticas com `cache_control: ephemeral`).
- **v1.1**: TMDb usado para release calendar (sazonalidade), não para subgênero. Subgênero vem do BERTopic Camada A.
- **v1.1**: `title_tests.result` mudou de boolean para enum (`winner`/`loser`/`inconclusive`) + `confidence_pct`.
- **v1.2**: `subs_bucket` deixou de ser coluna armazenada em `channels` — agora computado on-the-fly via `bucket_of(subs)`. Razão: subs cresce (3.5k → 10k é mudança de tier) e bucket cristalizado fica stale, contaminando features futuras.
- **v1.2**: clarificada semântica de `title_tests.result` — pra teste concluído: 1 linha winner + N-1 loser; pra teste inconclusive: TODAS as N linhas com `inconclusive`. Evita ambiguidade na ingestão dos resultados do Test & Compare.
- **v1.2**: `compute_multiplier` agora tem fallback explícito — < 10 vídeos anteriores elegíveis → `multiplier = NULL` e vídeo não entra em `outliers`. Sem baseline confiável o sinal vira ruído (canal jovem, primeiros meses).
- **v1.2**: chamada explícita de `migrations/003_horror_releases.sql` + ingest TMDb adicionada à Fase 1, e referenciada na Fase 0 como dependência futura. Antes ficava implícita só na descrição da Fase 3.
- **v1.3**: `migrations/002_handle_cache.sql` ocupa o slot 002 (handle resolver é a primeira tarefa da Fase 1, então faz sentido cronológico). `horror_releases` renumerada de 002 → 003. `jason db init` foi refatorado pra aplicar todas as migrations em `migrations/` em ordem de nome (ainda aceita `--migration X.sql` pra single file).
