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
  - `channels` (id, handle, title, subs, niche_tag)
  - `videos` (id, channel_id, title, description, published_at, duration_s, views, likes, comments, thumbnail_url)
  - `title_tests` (video_id, variant_id, title, thumbnail_path, watch_time_share, is_winner)
  - `outliers` (video_id, multiplier, computed_at)
- [ ] `pytest` rodando vazio sem erro

### Fase 1 — Ingestão (2-3 sessões)

- [ ] `youtube_data.py`: cliente que dado um `channel_id`, busca todos os vídeos públicos (paginar com `pageToken`). Respeitar quota: usar `part=snippet,statistics,contentDetails` numa só chamada. Cache local em jsonl antes de inserir no banco.
- [ ] CLI: `jason ingest channels --ids <id1,id2,...>` — popula `channels` e `videos`.
- [ ] CLI: `jason ingest neighbors --file canais.txt` — versão batch.
- [ ] `thumbnails.py`: download da maxres thumbnail de cada vídeo, salva em `data/thumbnails/{video_id}.jpg`. Skip se já existe.
- [ ] `transcripts.py`: usar `faster-whisper` modelo `large-v3` em GPU se disponível, fallback `medium` em CPU. Só transcrever vídeos do canal próprio + top-50 outliers do nicho (não a base toda — caro). Salvar em `data/transcripts/{video_id}.json`.
- [ ] `youtube_analytics.py`: OAuth flow (vai exigir interação manual primeira vez — deixar isso documentado no README). Pull diário de CTR, AVD, retention curve do canal próprio.
- [ ] **Teste de aceitação**: rodar para um canal vizinho conhecido e validar que o número de vídeos no banco bate com o que aparece no YouTube.

### Fase 2 — Feature engineering (1-2 sessões)

- [ ] `outliers.py`: função `compute_multiplier(channel_id, window_days=90)` — para cada vídeo, calcula `views / mediana_dos_últimos_30_vídeos_anteriores_a_ele`. Salva em `outliers`.
- [ ] `title_features.py`: extrai por título: `char_len`, `word_count`, `has_number`, `has_emoji`, `has_question_mark`, `has_caps_word`, `sentiment_score` (usar `pysentimiento` ou similar para PT-BR), `has_first_person` (eu/meu/minha).
- [ ] `embeddings.py`:
  - Títulos: `paraphrase-multilingual-mpnet-base-v2`, salva em coluna `title_embedding` (array float32, 768 dim).
  - Thumbnails: OpenCLIP `ViT-B-32`, salva em `thumb_embedding` (512 dim).
- [ ] `topics.py`: roda BERTopic sobre todos os títulos do nicho, gera `topic_id` e `topic_label` por vídeo. Persistir o modelo BERTopic em `models/artifacts/`.
- [ ] CLI: `jason features compute --all`
- [ ] **Teste**: query `SELECT topic_label, AVG(multiplier) FROM videos JOIN outliers USING(video_id) GROUP BY 1 ORDER BY 2 DESC LIMIT 10` deve retornar tópicos com média de multiplier sensata (não NaN, não tudo zero).

### Fase 3 — Modelo preditivo (1 sessão)

- [ ] `train.py`: LightGBM regressor com target = `log1p(multiplier)`. Features: tudo de `title_features` + cluster do title_embedding (k-means k=20) + cluster do thumb_embedding + `topic_id` + `duration_s` + `published_hour` + `published_dow`.
- [ ] Split temporal (não aleatório — mais antigo no train, mais recente no val). Métrica: Spearman correlation no val set + ranking accuracy quando comparamos pares de vídeos do mesmo canal.
- [ ] Gravar feature importance, salvar modelo em `models/artifacts/multiplier_v1.lgb`.
- [ ] `predict.py`: função `score_title(title: str, channel_id: str, thumbnail_path: str | None = None) -> float`.
- [ ] CLI: `jason model train` e `jason model score --title "..." --channel ...`.
- [ ] **Importante**: o modelo NÃO precisa prever views absolutos bem (variância gigante). Precisa **ranquear** candidatos. Use ranking metrics no val.

### Fase 4 — Geração de títulos (1 sessão)

- [ ] `rag.py`: dado um tópico ou transcrição, calcula embedding, faz busca por similaridade nos top-200 outliers do nicho (multiplier ≥ 3), retorna os 20 mais similares.
- [ ] `titles.py`: prompt para Claude com:
  - Contexto do canal (tom, nicho, exemplos de títulos vencedores próprios)
  - 20 títulos outliers do nicho como referência de estrutura (não para copiar, para extrair padrões)
  - Resumo de 200 palavras da transcrição do vídeo novo
  - Instrução: gerar 10 títulos em PT-BR, no estilo do canal, com diversidade de estrutura (curiosidade, lista, contraste, primeira pessoa, etc.)
- [ ] Pipeline completo: `jason suggest --transcript caminho.txt` → 10 títulos gerados → ranqueados pelo modelo da Fase 3 → top 3 retornados com score.
- [ ] Persistir cada sugestão em tabela `suggestions` para fechar o loop depois.

### Fase 5 — Dashboard (1 sessão)

Streamlit com 4 abas:

1. **Outliers do nicho** — tabela ranqueada por multiplier dos últimos 30 dias, filtro por canal, link para o vídeo no YT, thumbnail inline. Esse é o "feed do que o algoritmo está empurrando".
2. **Performance própria** — gráfico de CTR, AVD, retention dos vídeos dela ao longo do tempo (puxa do Analytics API).
3. **Title scorer** — input livre: cola um título, retorna score do modelo + percentil no nicho.
4. **Sugerir título** — upload de transcrição (ou cola texto), retorna top 3 títulos com explicação.

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
- **Títulos do nicho costumam usar CAPS, números altos e adjetivos extremos**: "O FILME MAIS PERTURBADOR JÁ FEITO", "10 CENAS QUE FORAM CORTADAS DE...", "POR QUE NINGUÉM FALA DESSE FILME". Isso vai dominar as features de `has_caps_word` e `sentiment_score` extremo. **Não filtrar isso como ruído** — é o sinal real do nicho.
- **Nomes de filmes confundem topic modeling**: BERTopic pode agrupar todos os vídeos sobre "Invocação do Mal" num tópico só, separado de "filmes de possessão demoníaca em geral". Mitigação: rodar BERTopic em duas camadas — uma com nomes próprios mascarados (substituir títulos de filmes por `<MOVIE>` usando NER ou matching contra base do TMDb), outra sem mascarar. A primeira captura *temas*, a segunda captura *franquias virais*.
- **Sazonalidade forte**: Halloween (out) e Sexta-feira 13 são picos previsíveis. Adicionar feature `days_to_halloween` e `is_friday_13th_week` no modelo da Fase 3.
- **Lançamentos de cinema/streaming dominam outliers**: muitos outliers do nicho são vídeos sobre filmes que acabaram de sair (ex: novo Final Destination, novo A24 horror). O sistema deve cruzar com calendário de lançamentos — adicionar na Fase 1+ um ingest do TMDb para filmes/séries de terror lançados nos próximos 90 dias.
- **Subgênero importa muito para CTR**: filmes de possessão, slashers, terror psicológico, found footage — cada um tem audiência diferente. Tag de subgênero deve ser uma feature explícita. Pode vir do TMDb (`genres` + `keywords`).
- **Spoilers e formato afetam packaging**: títulos com "EXPLICADO", "FINAL EXPLICADO", "TUDO QUE VOCÊ NÃO ENTENDEU" performam bem no nicho. Adicionar features booleanas: `has_explained_keyword`, `has_ranking_keyword` ("top", "melhores", "piores"), `has_curiosity_keyword` ("você não sabia", "ninguém fala", "verdade por trás").
- **Avoid copyright traps**: o canal lida com clipes de filmes — o sistema NÃO deve sugerir reproduzir trechos de roteiros, letras de músicas de trilhas, ou texto extenso de sinopses oficiais. Restringir geração a títulos e descrições originais.

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

1. Confirme que entendeu a arquitetura me explicando em 5 linhas, destacando como o nicho de terror muda algumas escolhas (sazonalidade, subgêneros, mascaramento de nomes de filmes no topic modeling).
2. Liste exatamente quais variáveis de ambiente eu vou precisar configurar — incluir já uma `TMDB_API_KEY` (chave grátis em `themoviedb.org/settings/api`) porque a Fase 1+ vai precisar.
3. Implemente o utilitário `handle_resolver.py` LOGO no início da Fase 1, antes de ingerir vídeos — assim eu consigo passar a lista de handles do CLAUDE.md direto e ele resolve para IDs com cache.
4. Aí sim começar o setup propriamente dito.
