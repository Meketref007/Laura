#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
AUDIT_FILE="$REPORTS_DIR/laura_metrics_auto_remediate_audit.jsonl"
STATE_FILE="$REPORTS_DIR/laura_metrics_audit_freshness_guard.state"
ENABLED="${LAURA_METRICS_AUDIT_FRESHNESS_GUARD_ENABLED:-1}"
MAX_AGE_MINUTES="${LAURA_METRICS_AUDIT_FRESHNESS_MAX_AGE_MINUTES:-180}"

if ! [[ "$ENABLED" =~ ^[01]$ ]]; then
  ENABLED=1
fi
if ! [[ "$MAX_AGE_MINUTES" =~ ^[0-9]+$ ]]; then
  MAX_AGE_MINUTES=180
fi

if [[ "$ENABLED" == "0" ]]; then
  echo "Laura metrics audit freshness guard disabled by LAURA_METRICS_AUDIT_FRESHNESS_GUARD_ENABLED=0"
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
  echo "Laura metrics audit freshness guard: audit file not found ($AUDIT_FILE), skipping."
  exit 0
fi

result="$(python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

path = Path("$AUDIT_FILE")
last_dt = None

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
        if last_dt is None or dt > last_dt:
            last_dt = dt
    except Exception:
        continue

if last_dt is None:
    print("NO_DATA|0|unknown")
else:
    now = datetime.now(timezone.utc)
    age_minutes = int((now - last_dt).total_seconds() // 60)
    print(f"OK|{age_minutes}|{last_dt.isoformat()}")
PY
)"

status="$(echo "$result" | cut -d'|' -f1)"
age_minutes="$(echo "$result" | cut -d'|' -f2)"
last_ts="$(echo "$result" | cut -d'|' -f3-)"

if ! [[ "$age_minutes" =~ ^[0-9]+$ ]]; then
  age_minutes=0
fi

if [[ "$status" == "NO_DATA" ]] || (( age_minutes > MAX_AGE_MINUTES )); then
  msg="Laura metrics audit freshness ALERT: ultimo evento de auditoria muito antigo (${age_minutes} min, limite=${MAX_AGE_MINUTES} min, last_ts=${last_ts})."
  if [[ ! -f "$STATE_FILE" ]]; then
    echo "$msg"
    notify "$msg"
    echo "alerted" > "$STATE_FILE"
  else
    echo "Laura metrics audit freshness guard: stale condition still active (${age_minutes} > ${MAX_AGE_MINUTES}), notification suppressed."
  fi
  exit 1
fi

if [[ -f "$STATE_FILE" ]]; then
  rm -f "$STATE_FILE"
  notify "Laura metrics audit freshness RECOVERY: idade do ultimo evento voltou ao normal (${age_minutes} min, limite=${MAX_AGE_MINUTES} min)."
fi

echo "Laura metrics audit freshness guard OK: age=${age_minutes} min (limit=${MAX_AGE_MINUTES}, last_ts=${last_ts})"
