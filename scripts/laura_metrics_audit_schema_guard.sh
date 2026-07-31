#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
AUDIT_FILE="$REPORTS_DIR/laura_metrics_auto_remediate_audit.jsonl"
STATE_FILE="$REPORTS_DIR/laura_metrics_audit_schema_guard.state"

ENABLED="${LAURA_METRICS_AUDIT_SCHEMA_GUARD_ENABLED:-1}"
WINDOW_HOURS="${LAURA_METRICS_AUDIT_SCHEMA_WINDOW_HOURS:-24}"
MAX_INVALID_LINES="${LAURA_METRICS_AUDIT_SCHEMA_MAX_INVALID_LINES:-0}"
MAX_UNKNOWN_STATUS="${LAURA_METRICS_AUDIT_SCHEMA_MAX_UNKNOWN_STATUS:-0}"

if ! [[ "$ENABLED" =~ ^[01]$ ]]; then
  ENABLED=1
fi
if ! [[ "$WINDOW_HOURS" =~ ^[0-9]+$ ]]; then
  WINDOW_HOURS=24
fi
if ! [[ "$MAX_INVALID_LINES" =~ ^[0-9]+$ ]]; then
  MAX_INVALID_LINES=0
fi
if ! [[ "$MAX_UNKNOWN_STATUS" =~ ^[0-9]+$ ]]; then
  MAX_UNKNOWN_STATUS=0
fi

if [[ "$ENABLED" == "0" ]]; then
  echo "Laura metrics audit schema guard disabled by LAURA_METRICS_AUDIT_SCHEMA_GUARD_ENABLED=0"
  exit 0
fi

cd "$ROOT_DIR"
set -a
source "$ROOT_DIR/.env"
set +a

notify() {
  local message="$1"
  if [[ -n "${LAURA_ALERT_TELEGRAM_BOT_TOKEN:-}" && -n "${LAURA_ALERT_TELEGRAM_CHAT_ID:-}" ]]; then
    curl -sS -X POST \
      "https://api.telegram.org/bot${LAURA_ALERT_TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d "chat_id=${LAURA_ALERT_TELEGRAM_CHAT_ID}" \
      --data-urlencode "text=${message}" \
      >/dev/null || true
  fi
}

if [[ ! -f "$AUDIT_FILE" ]]; then
  echo "Laura metrics audit schema guard: no audit file yet ($AUDIT_FILE)."
  exit 0
fi

result="$(python3 - <<PY
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

allowed = {
    "skipped_health_band",
    "skipped_no_data",
    "cooldown",
    "success",
    "failed",
    "auto_disabled",
    "guard_no_audit_file",
    "guard_insufficient_samples",
    "guard_insufficient_persistent",
    "guard_breach_waiting",
    "guard_alert_triggered",
    "guard_alert_active",
    "guard_recovery",
    "guard_ok",
}

path = Path("$AUDIT_FILE")
window_hours = int("$WINDOW_HOURS")
cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)

invalid_lines = 0
unknown_status = 0
samples = 0
for line in path.read_text(encoding="utf-8").splitlines():
    s = line.strip()
    if not s:
        continue
    try:
        row = json.loads(s)
    except Exception:
        invalid_lines += 1
        continue

    ts = row.get("timestamp")
    if not ts:
        invalid_lines += 1
        continue

    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        invalid_lines += 1
        continue

    if dt < cutoff:
        continue

    samples += 1
    status = str(row.get("status", "unknown"))
    if status not in allowed:
        unknown_status += 1

print(f"{invalid_lines}|{unknown_status}|{samples}")
PY
)"

invalid_lines="${result%%|*}"
rest="${result#*|}"
unknown_status="${rest%%|*}"
samples="${rest##*|}"

if ! [[ "$invalid_lines" =~ ^[0-9]+$ ]]; then
  invalid_lines=0
fi
if ! [[ "$unknown_status" =~ ^[0-9]+$ ]]; then
  unknown_status=0
fi
if ! [[ "$samples" =~ ^[0-9]+$ ]]; then
  samples=0
fi

if (( invalid_lines > MAX_INVALID_LINES || unknown_status > MAX_UNKNOWN_STATUS )); then
  msg="Laura metrics audit schema ALERT: invalid_lines=${invalid_lines} (max=${MAX_INVALID_LINES}), unknown_status=${unknown_status} (max=${MAX_UNKNOWN_STATUS}), samples=${samples}, window=${WINDOW_HOURS}h."
  if [[ ! -f "$STATE_FILE" ]]; then
    echo "$msg"
    notify "$msg"
    echo "alerted" > "$STATE_FILE"
  else
    echo "Laura metrics audit schema guard: condition still active, notification suppressed."
  fi
  exit 1
fi

if [[ -f "$STATE_FILE" ]]; then
  rm -f "$STATE_FILE"
  notify "Laura metrics audit schema RECOVERY: invalid_lines=${invalid_lines}, unknown_status=${unknown_status}, samples=${samples} in ${WINDOW_HOURS}h."
fi

echo "Laura metrics audit schema guard OK: invalid_lines=${invalid_lines}, unknown_status=${unknown_status}, samples=${samples}, window=${WINDOW_HOURS}h"
