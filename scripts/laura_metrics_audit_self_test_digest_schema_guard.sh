#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
DIGEST_LATEST_FILE="$REPORTS_DIR/laura_metrics_audit_self_test_digest_latest.json"
STATE_FILE="$REPORTS_DIR/laura_metrics_audit_self_test_digest_schema_guard.state"
ENABLED="${LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_SCHEMA_GUARD_ENABLED:-1}"
MAX_INVALID_FIELDS="${LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_SCHEMA_MAX_INVALID_FIELDS:-0}"

if ! [[ "$ENABLED" =~ ^[01]$ ]]; then
  ENABLED=1
fi
if ! [[ "$MAX_INVALID_FIELDS" =~ ^[0-9]+$ ]]; then
  MAX_INVALID_FIELDS=0
fi

if [[ "$ENABLED" == "0" ]]; then
  echo "Laura self-test digest schema guard disabled by LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_SCHEMA_GUARD_ENABLED=0"
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

if [[ ! -f "$DIGEST_LATEST_FILE" ]]; then
  msg="Laura self-test digest schema ALERT: arquivo ausente (${DIGEST_LATEST_FILE})."
  if [[ ! -f "$STATE_FILE" ]]; then
    echo "$msg"
    notify "$msg"
    echo "alerted" > "$STATE_FILE"
  else
    echo "Laura self-test digest schema guard: digest file still missing, notification suppressed."
  fi
  exit 1
fi

result="$(python3 - <<PY
import json
from pathlib import Path

path = Path("$DIGEST_LATEST_FILE")
required_top = {"timestamp", "host", "window_hours", "trend_delta_pct", "current", "previous", "failed_rate_delta_pct", "trend"}
required_current = {"total_runs", "failed_runs", "failed_rate_pct", "total_failures", "failed_checks", "top_failed_check", "top_failed_check_count", "last_failure_ts"}
required_previous = {"total_runs", "failed_runs", "failed_rate_pct", "total_failures", "failed_checks", "top_failed_check", "top_failed_check_count", "last_failure_ts"}

invalid_fields = 0
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    print("INVALID|0|invalid_json")
    raise SystemExit(0)

for key in required_top:
    if key not in payload:
        invalid_fields += 1

current = payload.get("current")
previous = payload.get("previous")
if not isinstance(current, dict):
    invalid_fields += 1
    current = {}
if not isinstance(previous, dict):
    invalid_fields += 1
    previous = {}

for key in required_current:
    if key not in current:
        invalid_fields += 1
for key in required_previous:
    if key not in previous:
        invalid_fields += 1

trend = str(payload.get("trend", ""))
if trend not in {"NO_BASELINE", "WORSENING", "IMPROVING", "STABLE"}:
    invalid_fields += 1

try:
    int(payload.get("window_hours", 0))
    int(payload.get("trend_delta_pct", 0))
    int(payload.get("failed_rate_delta_pct", 0))
    int(current.get("total_runs", 0))
    int(current.get("failed_runs", 0))
    int(current.get("failed_rate_pct", 0))
    int(current.get("total_failures", 0))
    int(current.get("top_failed_check_count", 0))
    int(previous.get("total_runs", 0))
    int(previous.get("failed_runs", 0))
    int(previous.get("failed_rate_pct", 0))
    int(previous.get("total_failures", 0))
    int(previous.get("top_failed_check_count", 0))
except Exception:
    invalid_fields += 1

print(f"OK|{invalid_fields}")
PY
)"

status="$(echo "$result" | cut -d'|' -f1)"
invalid_fields="$(echo "$result" | cut -d'|' -f2)"

if ! [[ "$invalid_fields" =~ ^[0-9]+$ ]]; then
  invalid_fields=0
fi

if [[ "$status" != "OK" ]] || (( invalid_fields > MAX_INVALID_FIELDS )); then
  msg="Laura self-test digest schema ALERT: invalid_fields=${invalid_fields} (max=${MAX_INVALID_FIELDS}) in ${DIGEST_LATEST_FILE}."
  if [[ ! -f "$STATE_FILE" ]]; then
    echo "$msg"
    notify "$msg"
    echo "alerted" > "$STATE_FILE"
  else
    echo "Laura self-test digest schema guard: invalid schema condition still active (${invalid_fields} > ${MAX_INVALID_FIELDS}), notification suppressed."
  fi
  exit 1
fi

if [[ -f "$STATE_FILE" ]]; then
  rm -f "$STATE_FILE"
  notify "Laura self-test digest schema RECOVERY: schema voltou ao normal (invalid_fields=${invalid_fields})."
fi

echo "Laura self-test digest schema guard OK: invalid_fields=${invalid_fields}, file=${DIGEST_LATEST_FILE}"
