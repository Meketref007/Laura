#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
HISTORY_FILE="$REPORTS_DIR/laura_metrics_audit_self_test_history.jsonl"
STATE_FILE="$REPORTS_DIR/laura_metrics_audit_self_test_guard.state"
ENABLED="${LAURA_METRICS_AUDIT_SELF_TEST_GUARD_ENABLED:-1}"
WINDOW_HOURS="${LAURA_METRICS_AUDIT_SELF_TEST_GUARD_WINDOW_HOURS:-168}"
MIN_FAILED_RUNS="${LAURA_METRICS_AUDIT_SELF_TEST_GUARD_MIN_FAILED_RUNS:-1}"
MIN_RATIO_PCT="${LAURA_METRICS_AUDIT_SELF_TEST_GUARD_MIN_RATIO_PCT:-50}"
MIN_SAMPLES="${LAURA_METRICS_AUDIT_SELF_TEST_GUARD_MIN_SAMPLES:-1}"

if ! [[ "$ENABLED" =~ ^[01]$ ]]; then
  ENABLED=1
fi
if ! [[ "$WINDOW_HOURS" =~ ^[0-9]+$ ]]; then
  WINDOW_HOURS=168
fi
if ! [[ "$MIN_FAILED_RUNS" =~ ^[0-9]+$ ]]; then
  MIN_FAILED_RUNS=1
fi
if ! [[ "$MIN_RATIO_PCT" =~ ^[0-9]+$ ]]; then
  MIN_RATIO_PCT=50
fi
if ! [[ "$MIN_SAMPLES" =~ ^[0-9]+$ ]]; then
  MIN_SAMPLES=1
fi
if (( MIN_RATIO_PCT > 100 )); then
  MIN_RATIO_PCT=100
fi
if (( MIN_FAILED_RUNS < 1 )); then
  MIN_FAILED_RUNS=1
fi
if (( MIN_SAMPLES < 1 )); then
  MIN_SAMPLES=1
fi

if [[ "$ENABLED" == "0" ]]; then
  echo "Laura metrics audit self-test guard disabled by LAURA_METRICS_AUDIT_SELF_TEST_GUARD_ENABLED=0"
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

if [[ ! -f "$HISTORY_FILE" ]]; then
  echo "Laura metrics audit self-test guard: no history file yet ($HISTORY_FILE)."
  exit 0
fi

result="$(python3 - <<PY
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

path = Path("$HISTORY_FILE")
window_hours = int("$WINDOW_HOURS")
cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)

samples = 0
failed_runs = 0
total_failures = 0
latest_ts = ""
latest_failed_ts = ""

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
        samples += 1
        latest_ts = dt.isoformat()
        failures = int(row.get("failures", 0))
        if failures > 0:
            failed_runs += 1
            total_failures += failures
            latest_failed_ts = dt.isoformat()
    except Exception:
        continue

ratio_pct = int((failed_runs * 100) / samples) if samples > 0 else 0
print(f"{samples}|{failed_runs}|{ratio_pct}|{total_failures}|{latest_ts}|{latest_failed_ts}")
PY
)"

samples="$(echo "$result" | cut -d'|' -f1)"
failed_runs="$(echo "$result" | cut -d'|' -f2)"
ratio_pct="$(echo "$result" | cut -d'|' -f3)"
total_failures="$(echo "$result" | cut -d'|' -f4)"
latest_ts="$(echo "$result" | cut -d'|' -f5)"
latest_failed_ts="$(echo "$result" | cut -d'|' -f6)"

if ! [[ "$samples" =~ ^[0-9]+$ ]]; then
  samples=0
fi
if ! [[ "$failed_runs" =~ ^[0-9]+$ ]]; then
  failed_runs=0
fi
if ! [[ "$ratio_pct" =~ ^[0-9]+$ ]]; then
  ratio_pct=0
fi
if ! [[ "$total_failures" =~ ^[0-9]+$ ]]; then
  total_failures=0
fi

if (( samples < MIN_SAMPLES )); then
  echo "Laura metrics audit self-test guard: insufficient samples (${samples}/${MIN_SAMPLES}) in ${WINDOW_HOURS}h, skipping alert decision."
  exit 0
fi

condition_active=0
if (( failed_runs >= MIN_FAILED_RUNS && ratio_pct >= MIN_RATIO_PCT )); then
  condition_active=1
fi

if (( condition_active == 1 )); then
  msg="Laura audit self-test guard ALERT: ${failed_runs}/${samples} runs com falha (${ratio_pct}%) em ${WINDOW_HOURS}h, total_failures=${total_failures} (limites: min_failed=${MIN_FAILED_RUNS}, ratio=${MIN_RATIO_PCT}%)."
  if [[ ! -f "$STATE_FILE" ]]; then
    echo "$msg"
    notify "$msg"
    echo "alerted" > "$STATE_FILE"
  else
    echo "Laura audit self-test guard: alert condition still active (${failed_runs}/${samples}=${ratio_pct}%), notification suppressed."
  fi
  exit 1
fi

if [[ -f "$STATE_FILE" ]]; then
  rm -f "$STATE_FILE"
  notify "Laura audit self-test guard RECOVERY: falhas do self-test voltaram ao normal (${failed_runs}/${samples}=${ratio_pct}%) em ${WINDOW_HOURS}h."
fi

echo "Laura audit self-test guard OK: failed_runs=${failed_runs}/${samples} (${ratio_pct}%), total_failures=${total_failures}, latest=${latest_ts:-N/A}, latest_failed=${latest_failed_ts:-N/A}"
