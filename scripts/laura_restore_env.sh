#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
ENV_FILE="$ROOT_DIR/.env"
BACKUP_FILE="$ROOT_DIR/.env.bak"
DRY_RUN=0

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "Backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Environment file not found: $ENV_FILE" >&2
  exit 1
fi

ts="$(date +%Y%m%d_%H%M%S)"
pre_restore="$ROOT_DIR/.env.pre-restore.${ts}"

if [[ $DRY_RUN -eq 1 ]]; then
  echo "DRY RUN"
  echo "Would create pre-restore snapshot: $pre_restore"
  echo "Would restore: $ENV_FILE from $BACKUP_FILE"
  exit 0
fi

cp "$ENV_FILE" "$pre_restore"
tmp_file="$ROOT_DIR/.env.restore.tmp"
cp "$BACKUP_FILE" "$tmp_file"
mv "$tmp_file" "$ENV_FILE"

echo "Restore completed."
echo "Current env restored from: $BACKUP_FILE"
echo "Previous env snapshot saved at: $pre_restore"
