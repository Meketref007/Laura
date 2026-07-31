#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
AUDIT_FILE="$REPORTS_DIR/laura_metrics_auto_remediate_audit.jsonl"
STATE_FILE="$REPORTS_DIR/laura_metrics_audit_volume_guard.state"

ENABLED="${LAURA_METRICS_AUDIT_VOLUME_GUARD_ENABLED:-1}"
WINDOW_MINUTES="${LAURA_METRICS_AUDIT_VOLUME_WINDOW_MINUTES:-60}"
MAX_EVENTS="${LAURA_METRICS_AUDIT_VOLUME_MAX_EVENTS:-120}"

if ! [[ "$ENABLED" =~ ^[01]$ ]]; then
  ENABLED=1
fi
if ! [[ "$WINDOW_MINUTES" =~ ^[0-9]+$ ]]; then
  WINDOW_MINUTES=60
fi
if ! [[ "$MAX_EVENTS" =~ ^[0-9]+$ ]]; then
  MAX_EVENTS=120
fi
if (( WINDOW_MINUTES < 1 )); then
  WINDOW_MINUTES=60
fi
if (( MAX_EVENTS < 1 )); then
  MAX_EVENTS=120
fi

if [[ "$ENABLED" == "0" ]]; then
  echo "Laura metrics audit volume guard disabled by LAURA_METRICS_AUDIT_VOLUME_GUARD_ENABLED=0"
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
  echo "Laura metrics audit volume guard: no audit file yet ($AUDIT_FILE)."
  exit 0
fi

result="$(python3 - <<PY
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

path = Path("$AUDIT_FILE")
window_minutes = int("$WINDOW_MINUTES")
cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)

total = 0
status_counts = {}
for line in path.read_text(encoding="utf-8").splitlines():
    s = line.strip()
    if not s:
        continue
    try:
        row = json.loads(s)
        ts = row.get("timestamp")
        if not ts:
            continue
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt < cutoff:
            continue
        total += 1
        status = str(row.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
    except Exception:
        continue

if status_counts:
    top_status = max(status_counts, key=status_counts.get)
    top_count = status_counts[top_status]
else:
    top_status = "none"
    top_count = 0

print(f"{total}|{top_status}|{top_count}")
PY
)"

total="${result%%|*}"
rest="${result#*|}"
top_status="${rest%%|*}"
top_count="${rest##*|}"

if ! [[ "$total" =~ ^[0-9]+$ ]]; then
  total=0
fi
if ! [[ "$top_count" =~ ^[0-9]+$ ]]; then
  top_count=0
fi

if (( total > MAX_EVENTS )); then
  msg="Laura metrics audit volume ALERT: ${total} eventos em ${WINDOW_MINUTES} min (limite=${MAX_EVENTS}). Top status=${top_status} (${top_count})."
  if [[ ! -f "$STATE_FILE" ]]; then
    echo "$msg"
    notify "$msg"
    echo "alerted" > "$STATE_FILE"
  else
    echo "Laura metrics audit volume guard: high-volume condition still active (${total} > ${MAX_EVENTS}), notification suppressed."
  fi
  exit 1
fi

if [[ -f "$STATE_FILE" ]]; then
  rm -f "$STATE_FILE"
  notify "Laura metrics audit volume RECOVERY: volume voltou ao normal (${total}/${MAX_EVENTS} em ${WINDOW_MINUTES} min)."
fi

echo "Laura metrics audit volume guard OK: total=${total} (limit=${MAX_EVENTS}, window=${WINDOW_MINUTES}min, top=${top_status}:${top_count})"
