#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
RETENTION_DAYS="${LAURA_ENV_SNAPSHOT_RETENTION_DAYS:-30}"

if ! [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
  RETENTION_DAYS=30
fi

cd "$ROOT_DIR"

# Remove old pre-restore snapshots that may contain sensitive env values.
find "$ROOT_DIR" \
  -maxdepth 1 \
  -type f \
  -name ".env.pre-restore.*" \
  -mtime "+$RETENTION_DAYS" \
  -print \
  -delete

# Remove stale temp files created by restore/update routines.
find "$ROOT_DIR" \
  -maxdepth 1 \
  -type f \
  \( -name ".env.tmp" -o -name ".env.restore.tmp" \) \
  -print \
  -delete

echo "Laura housekeeping OK: retention=${RETENTION_DAYS} days"
