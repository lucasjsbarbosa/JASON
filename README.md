# JASON

> *"They call him JSON. He parses your YouTube data and won't stop until your CTR is dead."*

YouTube growth engine para o canal `@babygiulybaby` (reviews e análises de filmes de terror em PT-BR). Pega dados de vídeos próprios + canais vizinhos via API oficial, detecta outliers do nicho via **multiplier** corrigido por idade, prevê o multiplier de títulos candidatos com LightGBM, e gera 10 candidatos por vídeo via Claude (com prompt caching).

## Quickstart (5 min)

Pré-requisitos: WSL Ubuntu, [`uv`](https://docs.astral.sh/uv/), Python 3.11+, conta no Google Cloud + TMDb + Anthropic.

```bash
git clone <repo>
cd jason

# Deps base (~100MB) — basta pra ingest, snapshot, dashboard
uv sync

# Deps de ML (~3GB de torch + sentence-transformers + open_clip + bertopic
# + lightgbm + sklearn + pandas) — só quando for rodar features ML
uv sync --group ml

# Configuração de chaves
cp .env.example .env
# Cola sua chave silenciosamente (não vaza no histórico do shell):
read -rsp 'YOUTUBE_DATA_API_KEY: ' KEY && \
  sed -i "s|^YOUTUBE_DATA_API_KEY=.*|YOUTUBE_DATA_API_KEY=${KEY}|" .env && unset KEY
# (repita para TMDB_API_KEY e ANTHROPIC_API_KEY)

# Inicializa o DuckDB com todas as migrations
uv run jason db init

# Ingest: resolve handles → puxa videos → snapshot inicial → thumbnails
uv run jason ingest resolve-handles -f canais.txt -o canais_ids.txt
uv run jason ingest channels --ids UCxxxxx,UCyyyyy,...
uv run jason ingest thumbnails
uv run jason ingest tmdb-releases    # release calendar de horror

# Features (precisa do grupo ml acima)
uv run jason features title
uv run jason features embeddings --titles --thumbnails
uv run jason features topics --themes --franchises

# Dashboard
uv run jason dashboard
```

## Rodar num segundo computador (notebook, etc)

O `warehouse.duckdb` e os artifacts do modelo treinado estão versionados via
**Git LFS** — `git clone` puxa eles automaticamente. Thumbnails (~3GB) NÃO
estão no repo, mas regeram via `jason ingest thumbnails` (gratuito, vem do
CDN do YouTube — só os URLs ficam guardados no DB).

```bash
# Pré-requisitos no notebook: git-lfs + uv + node 20+
sudo apt install -y git-lfs                # uma vez
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone + bootstrap
git clone https://github.com/lucasjsbarbosa/JASON.git ~/projetos/jason
cd ~/projetos/jason
bash scripts/bootstrap-laptop.sh           # faz tudo: lfs pull, uv sync,
                                           # npm install, re-baixa thumbs
```

Depois disso, **edite `.env`** com suas chaves (`YOUTUBE_DATA_API_KEY`,
`ANTHROPIC_API_KEY`) e rode `uv run jason api` + `cd apps/web && npm run dev`.

Manter sincronizado: o desktop é dono da ingestão (snapshot diário roda lá).
No notebook, `git pull` quando você quiser puxar warehouse atualizado do
desktop.

## Cadência de produção

- **Diariamente (ou semanal mínimo)**: `jason snapshot run` — coleta views/likes/comments atuais. Sem isso, o `views_at_28d` da Fase 2 nunca interpola e o modelo da Fase 3 não treina. Use Windows Task Scheduler ou cron — wrapper já em `scripts/weekly_snapshot.sh`.
- **Após ~28 dias de snapshots**: `jason features outliers` calcula multipliers e percentis intra-canal.
- **Quando outliers materializarem**: `jason model train` ajusta o LightGBM.
- **Por vídeo novo**: `jason suggest --transcript transcript.txt` gera 10 candidatos via Claude e ranqueia pelos top 3 — manda pro Test & Compare nativo do YouTube.

## Estrutura

```
jason/
├── CLAUDE.md                # spec completa + changelog (v1.x)
├── canais.txt               # 25 canais ativos do nicho (auditados)
├── migrations/              # 7 migrations DuckDB, aplicadas em ordem por `db init`
├── scripts/
│   ├── audit_channels.py        # checa freshness via API (FRESCO/MORTO/etc)
│   ├── report_features.py       # niche-flag rates por canal
│   └── weekly_snapshot.sh       # cron/Task Scheduler wrapper
├── src/jason/
│   ├── ingestion/           # YouTube Data v3, snapshots, thumbnails, transcripts, TMDb
│   ├── features/            # title features, outliers, embeddings, topics
│   ├── models/              # LightGBM regressor (train/predict, k-means clusters)
│   ├── generation/          # RAG + Claude com prompt caching
│   └── dashboard/           # Streamlit, 5 abas
├── tests/                   # pytest, fully mocked APIs
└── data/                    # gitignored
    ├── warehouse.duckdb
    ├── raw/                 # JSONL bruto da videos.list
    ├── thumbnails/
    └── transcripts/
```

## Filosofia

1. **Outlier multiplier > views absoluto.** `views_at_28d / mediana(últimos 30 do mesmo canal)` corrige o viés de idade — vídeo de 2 anos não é outlier só por ter acumulado.
2. **Subdivide o nicho.** Reviews ≠ análises ≠ rankings ≠ true crime. BERTopic em duas camadas (com mascaramento de nomes próprios) separa esses padrões.
3. **Test & Compare é o juiz, não o JASON.** Geração de títulos alimenta o A/B nativo do YouTube com candidatos de alta qualidade — quem vence é o `watch_time_share` que o YouTube mede.
4. **Prompt caching agressivo.** A geração via Claude tem ~80% do prompt fixo (referências de outliers, regras) — `cache_control: ephemeral` corta custo e latência.

Veja [`CLAUDE.md`](CLAUDE.md) para a spec completa, fases de implementação e changelog detalhado.
