#!/usr/bin/env bash
# Bootstrap JASON num notebook depois do `git clone`.
#
# Premissas:
#   - WSL (Ubuntu) ou Linux nativo
#   - git-lfs instalado (sudo apt install -y git-lfs)
#   - uv instalado (curl -LsSf https://astral.sh/uv/install.sh | sh)
#   - node + npm instalado
#
# O que faz:
#   1. git lfs pull → baixa warehouse.duckdb + artifacts do modelo
#   2. uv sync --group ml → cria .venv e baixa deps Python (~3GB)
#   3. (apps/web) npm install → deps Next.js (~600MB)
#   4. jason ingest thumbnails → re-baixa thumbs do CDN do YouTube (free)
#   5. avisa pra criar o .env e rodar a API + dashboard
#
# Uso:
#   git clone https://github.com/lucasjsbarbosa/JASON.git ~/projetos/jason
#   cd ~/projetos/jason
#   bash scripts/bootstrap-laptop.sh

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)

bold() { printf "\033[1m%s\033[0m\n" "$*"; }
warn() { printf "\033[33m%s\033[0m\n" "$*"; }
ok()   { printf "\033[32m%s\033[0m\n" "$*"; }

bold "→ JASON bootstrap (laptop)"
echo "  trabalhando em: $ROOT"
echo

# --- 1. git LFS ------------------------------------------------------------
if ! command -v git-lfs >/dev/null 2>&1; then
  warn "git-lfs não encontrado. Instala primeiro:"
  echo "    sudo apt install -y git-lfs"
  exit 1
fi
bold "1/5 → git lfs pull (warehouse.duckdb + modelo treinado)"
git lfs install --local
git lfs pull
ok "    ok"
echo

# --- 2. Python deps -------------------------------------------------------
bold "2/5 → uv sync --group ml (deps Python, primeira vez ~3GB)"
if ! command -v uv >/dev/null 2>&1; then
  warn "uv não encontrado. Instala antes:"
  echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi
uv sync --group ml
ok "    ok"
echo

# --- 3. Node deps ---------------------------------------------------------
bold "3/5 → npm install em apps/web"
if ! command -v npm >/dev/null 2>&1; then
  warn "npm não encontrado. Instala node 20+: https://nodejs.org"
  exit 1
fi
( cd apps/web && npm install )
ok "    ok"
echo

# --- 4. .env -------------------------------------------------------------
bold "4/5 → checando .env"
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    warn "    .env criado a partir de .env.example"
    warn "    EDITE .env e preenche YOUTUBE_DATA_API_KEY + ANTHROPIC_API_KEY"
    warn "    (TMDb e analytics são opcionais)"
  else
    warn "    .env não existe e não há .env.example. Crie manualmente."
  fi
else
  ok "    .env já existe"
fi
echo

# --- 5. thumbnails --------------------------------------------------------
bold "5/5 → re-baixando thumbnails (CDN do YouTube, free)"
if [ -d data/thumbnails ] && [ "$(ls -A data/thumbnails 2>/dev/null)" ]; then
  ok "    data/thumbnails/ já tem arquivos, pulando"
else
  echo "    isso pode levar 5-15 min, ~3GB de imagens..."
  uv run jason ingest thumbnails || warn "    (algumas falhas é ok — só as públicas baixam)"
fi
echo

ok "✓ pronto. Pra rodar:"
echo "    uv run jason api               # backend FastAPI :8000"
echo "    cd apps/web && npm run dev     # frontend Next.js :3000"
echo "    abre http://localhost:3000 no navegador"
