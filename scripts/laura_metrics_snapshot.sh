#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
METRICS_FILE="$REPORTS_DIR/laura_metrics.jsonl"
RETENTION_DAYS="${LAURA_METRICS_RETENTION_DAYS:-30}"

if ! [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
  RETENTION_DAYS=30
fi

mkdir -p "$REPORTS_DIR"
cd "$ROOT_DIR"

PY_CMD="$ROOT_DIR/.venv/bin/python"
if [[ ! -x "$PY_CMD" ]]; then
  PY_CMD="python3"
fi

set -a
source "$ROOT_DIR/.env"
set +a

ts_iso="$(date -Is)"
host_name="$(hostname)"

shop_status="unknown"
shop_name="unknown"
api_ok=0
if shop_json="$("$PY_CMD" -m shopee_agent.cli shop-info-default 2>/tmp/laura_metrics_shop.err)"; then
  shop_name="$(printf '%s' "$shop_json" | "$PY_CMD" -c 'import json,sys; d=json.load(sys.stdin); print(d.get("shop_name","unknown"))')"
  shop_status="$(printf '%s' "$shop_json" | "$PY_CMD" -c 'import json,sys; d=json.load(sys.stdin); print(d.get("status","unknown"))')"
  api_ok=1
fi

cron_ok=0
if ./scripts/laura_reconcile_cron.sh --check >/tmp/laura_metrics_cron.out 2>/tmp/laura_metrics_cron.err; then
  cron_ok=1
fi

backup_verify_ok=0
if ./scripts/laura_verify_backup.sh >/tmp/laura_metrics_backup.out 2>/tmp/laura_metrics_backup.err; then
  backup_verify_ok=1
fi

"$PY_CMD" - <<PY >> "$METRICS_FILE"
import json
row = {
  "timestamp": "$ts_iso",
  "host": "$host_name",
  "api_ok": bool($api_ok),
  "shop_name": "$shop_name",
  "shop_status": "$shop_status",
  "cron_ok": bool($cron_ok),
  "backup_verify_ok": bool($backup_verify_ok),
}
print(json.dumps(row, ensure_ascii=True))
PY

# Prune old rows by embedded timestamp, keeping true rolling retention.
"$PY_CMD" - <<PY
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

metrics_file = Path("$METRICS_FILE")
retention_days = int("$RETENTION_DAYS")
cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

kept = []
for line in metrics_file.read_text(encoding="utf-8").splitlines():
  s = line.strip()
  if not s:
    continue
  try:
    row = json.loads(s)
    ts = row.get("timestamp")
    if not ts:
      continue
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt >= cutoff:
      kept.append(json.dumps(row, ensure_ascii=True))
  except Exception:
    continue

metrics_file.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
PY

echo "Laura metrics snapshot saved: $METRICS_FILE"
