#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
BACKUP_DIR="$ROOT_DIR/backups"
RETENTION_DAYS="${LAURA_BACKUP_RETENTION_DAYS:-14}"

source "$ROOT_DIR/scripts/telegram_narrator.sh"

if ! [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
  RETENTION_DAYS=14
fi

mkdir -p "$BACKUP_DIR"

stamp="$(date +%Y%m%d_%H%M%S)"
out="$BACKUP_DIR/laura_backup_${stamp}.tar.gz"

tg_narrar backup "*Backup* iniciado" "$(date -u +'%Y-%m-%d')"

cd "$ROOT_DIR"

# Backup critical runtime and project configuration for quick recovery.
tar -czf "$out" \
  .env \
  .env.bak \
  README.md \
  pyproject.toml \
  requirements.txt \
  scripts \
  shopee_agent \
  2>/dev/null || tar -czf "$out" README.md pyproject.toml requirements.txt scripts shopee_agent

find "$BACKUP_DIR" -maxdepth 1 -type f -name "laura_backup_*.tar.gz" -mtime "+$RETENTION_DAYS" -delete

echo "Laura backup created: $out"

tg_narrar feito "Backup concluído" "Arquivo: ${out}"
