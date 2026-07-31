#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
INPUT_FILE="$REPORTS_DIR/laura_profitability_inputs_latest.json"
STATE_FILE="$REPORTS_DIR/laura_profitability_input_freshness_guard.state"
ENABLED="${LAURA_PROFITABILITY_INPUT_FRESHNESS_GUARD_ENABLED:-1}"
MAX_AGE_MINUTES="${LAURA_PROFITABILITY_INPUT_FRESHNESS_MAX_AGE_MINUTES:-180}"
NOTIFY_RECOVERY="${LAURA_PROFITABILITY_INPUT_FRESHNESS_NOTIFY_RECOVERY:-1}"

if ! [[ "$ENABLED" =~ ^[01]$ ]]; then
  ENABLED=1
fi
if ! [[ "$MAX_AGE_MINUTES" =~ ^[0-9]+$ ]]; then
  MAX_AGE_MINUTES=180
fi
if (( MAX_AGE_MINUTES < 1 )); then
  MAX_AGE_MINUTES=1
fi
if ! [[ "$NOTIFY_RECOVERY" =~ ^[01]$ ]]; then
  NOTIFY_RECOVERY=1
fi

if [[ "$ENABLED" == "0" ]]; then
  echo "Laura profitability input freshness guard disabled by LAURA_PROFITABILITY_INPUT_FRESHNESS_GUARD_ENABLED=0"
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

if [[ ! -f "$INPUT_FILE" ]]; then
  msg="Laura profitability input freshness ALERT: arquivo ausente (${INPUT_FILE})."
  if [[ ! -f "$STATE_FILE" ]]; then
    echo "$msg"
    notify "$msg"
    echo "alerted" > "$STATE_FILE"
  else
    echo "Laura profitability input freshness guard: input ainda ausente, alerta suprimido."
  fi
  exit 1
fi

result="$(python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

path = Path("$INPUT_FILE")
try:
    row = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    print("INVALID|0|invalid_json")
    raise SystemExit(0)

ts = row.get("timestamp")
if not ts:
    print("INVALID|0|missing_timestamp")
    raise SystemExit(0)

try:
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
except Exception:
    print("INVALID|0|invalid_timestamp")
    raise SystemExit(0)

age_minutes = int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
print(f"OK|{age_minutes}|{dt.isoformat()}")
PY
)"

status="$(echo "$result" | cut -d'|' -f1)"
age_minutes="$(echo "$result" | cut -d'|' -f2)"
last_ts="$(echo "$result" | cut -d'|' -f3-)"

if ! [[ "$age_minutes" =~ ^[0-9]+$ ]]; then
  age_minutes=0
fi

if [[ "$status" != "OK" ]] || (( age_minutes > MAX_AGE_MINUTES )); then
  msg="Laura profitability input freshness ALERT: input stale/invalido (status=${status}, age=${age_minutes} min, limite=${MAX_AGE_MINUTES} min, last_ts=${last_ts})."
  if [[ ! -f "$STATE_FILE" ]]; then
    echo "$msg"
    notify "$msg"
    echo "alerted" > "$STATE_FILE"
  else
    echo "Laura profitability input freshness guard: condicao stale ainda ativa (status=${status}, age=${age_minutes}), alerta suprimido."
  fi
  exit 1
fi

if [[ -f "$STATE_FILE" ]]; then
  rm -f "$STATE_FILE"
  if [[ "$NOTIFY_RECOVERY" == "1" ]]; then
    notify "Laura profitability input freshness RECOVERY: input voltou ao normal (age=${age_minutes} min, limite=${MAX_AGE_MINUTES} min)."
  fi
fi

echo "Laura profitability input freshness guard OK: age=${age_minutes} min (limit=${MAX_AGE_MINUTES}, last_ts=${last_ts})"