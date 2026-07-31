#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
OUT_DIR="$ROOT_DIR/reports"
STAMP="$(date +%Y%m%d_%H%M%S)"
BUNDLE_DIR="$OUT_DIR/laura_incident_${STAMP}"

mkdir -p "$BUNDLE_DIR"
cd "$ROOT_DIR"

# 1) Basic host and runtime metadata.
{
  echo "timestamp=$(date -Is)"
  echo "host=$(hostname)"
  echo "cwd=$ROOT_DIR"
  echo "python=$(python3 --version 2>&1)"
} > "$BUNDLE_DIR/system.txt"

# 2) Cron and file inventory.
crontab -l > "$BUNDLE_DIR/cron.txt" 2>/dev/null || true
ls -lah "$ROOT_DIR/scripts" > "$BUNDLE_DIR/scripts_ls.txt" 2>/dev/null || true
ls -lah "$ROOT_DIR/logs" > "$BUNDLE_DIR/logs_ls.txt" 2>/dev/null || true
ls -lah "$ROOT_DIR/backups" > "$BUNDLE_DIR/backups_ls.txt" 2>/dev/null || true

# 3) Redacted env snapshot (keys only, values hidden).
if [[ -f "$ROOT_DIR/.env" ]]; then
  awk -F= '
    /^[[:space:]]*#/ {next}
    /^[[:space:]]*$/ {next}
    {
      key=$1
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", key)
      if (length(key) > 0) {
        print key "=<redacted>"
      }
    }
  ' "$ROOT_DIR/.env" > "$BUNDLE_DIR/env_redacted.txt"
fi

# 4) Recent logs.
if [[ -f "$ROOT_DIR/logs/laura_healthcheck.log" ]]; then
  tail -n 300 "$ROOT_DIR/logs/laura_healthcheck.log" > "$BUNDLE_DIR/laura_healthcheck_tail.txt"
fi

# 5) Quick command diagnostics.
./scripts/laura_reconcile_cron.sh --check > "$BUNDLE_DIR/reconcile_check.txt" 2>&1 || true
./scripts/laura_status.sh > "$BUNDLE_DIR/laura_status.txt" 2>&1 || true
./scripts/laura_metrics_audit_self_test_digest_status.sh > "$BUNDLE_DIR/self_test_digest_status.txt" 2>&1 || true
./scripts/laura_verify_backup.sh > "$BUNDLE_DIR/verify_backup.txt" 2>&1 || true

# 6) Compress bundle for sharing.
ARCHIVE="$OUT_DIR/laura_incident_${STAMP}.tar.gz"
tar -czf "$ARCHIVE" -C "$OUT_DIR" "laura_incident_${STAMP}"

echo "Laura incident bundle created: $ARCHIVE"
