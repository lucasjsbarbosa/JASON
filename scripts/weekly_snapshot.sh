#!/usr/bin/env bash
# Weekly snapshot wrapper — invoked by cron (see crontab).
# Logs to data/snapshot.log; exit non-zero on failure so cron can email.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOG="${REPO}/data/snapshot.log"
UV="${HOME}/.local/bin/uv"

mkdir -p "${REPO}/data"
{
    echo
    echo "=== $(date -u +'%Y-%m-%dT%H:%M:%SZ') snapshot run ==="
    cd "${REPO}"
    "${UV}" run jason snapshot run
} >> "${LOG}" 2>&1
