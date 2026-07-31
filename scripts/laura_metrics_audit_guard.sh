#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
AUDIT_FILE="$REPORTS_DIR/laura_metrics_auto_remediate_audit.jsonl"
STATE_FILE="$REPORTS_DIR/laura_metrics_audit_guard.state"
ENABLED="${LAURA_METRICS_AUDIT_GUARD_ENABLED:-1}"
WINDOW_HOURS="${LAURA_METRICS_AUDIT_GUARD_WINDOW_HOURS:-24}"
MIN_EVENTS="${LAURA_METRICS_AUDIT_GUARD_MIN_SKIPPED_HEALTH_BAND:-6}"
MIN_RATIO_PCT="${LAURA_METRICS_AUDIT_GUARD_MIN_RATIO_PCT:-60}"
MIN_SAMPLES="${LAURA_METRICS_AUDIT_GUARD_MIN_SAMPLES:-10}"
MAX_INSUFFICIENT_STREAK="${LAURA_METRICS_AUDIT_GUARD_MAX_INSUFFICIENT_STREAK:-12}"
CONSECUTIVE_BREACHES="${LAURA_METRICS_AUDIT_GUARD_CONSECUTIVE_BREACHES:-2}"
MAX_STATE_AGE_HOURS="${LAURA_METRICS_AUDIT_GUARD_MAX_STATE_AGE_HOURS:-168}"
STATUS_FILTER="${LAURA_METRICS_AUDIT_GUARD_STATUS:-skipped_health_band}"

if ! [[ "$ENABLED" =~ ^[01]$ ]]; then
  ENABLED=1
fi
if ! [[ "$WINDOW_HOURS" =~ ^[0-9]+$ ]]; then
  WINDOW_HOURS=24
fi
if ! [[ "$MIN_EVENTS" =~ ^[0-9]+$ ]]; then
  MIN_EVENTS=6
fi
if ! [[ "$MIN_RATIO_PCT" =~ ^[0-9]+$ ]]; then
  MIN_RATIO_PCT=60
fi
if ! [[ "$MIN_SAMPLES" =~ ^[0-9]+$ ]]; then
  MIN_SAMPLES=10
fi
if ! [[ "$MAX_INSUFFICIENT_STREAK" =~ ^[0-9]+$ ]]; then
  MAX_INSUFFICIENT_STREAK=12
fi
if (( MAX_INSUFFICIENT_STREAK < 1 )); then
  MAX_INSUFFICIENT_STREAK=1
fi
if ! [[ "$MAX_STATE_AGE_HOURS" =~ ^[0-9]+$ ]]; then
  MAX_STATE_AGE_HOURS=168
fi
if (( MAX_STATE_AGE_HOURS < 1 )); then
  MAX_STATE_AGE_HOURS=1
fi
if ! [[ "$CONSECUTIVE_BREACHES" =~ ^[0-9]+$ ]]; then
  CONSECUTIVE_BREACHES=2
fi
if (( CONSECUTIVE_BREACHES < 1 )); then
  CONSECUTIVE_BREACHES=1
fi
if (( MIN_RATIO_PCT > 100 )); then
  MIN_RATIO_PCT=100
fi

if [[ "$ENABLED" == "0" ]]; then
  echo "Laura metrics audit guard disabled by LAURA_METRICS_AUDIT_GUARD_ENABLED=0"
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

log_audit_event() {
  local event_status="$1"
  local note="${2:-}"
  python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

audit = Path("$AUDIT_FILE")
audit.parent.mkdir(parents=True, exist_ok=True)
entry = {
  "timestamp": datetime.now(timezone.utc).isoformat(),
  "script": "laura_metrics_audit_guard.sh",
  "mode": "decision",
  "status": "$event_status",
  "cause": "$STATUS_FILTER",
  "health_band": "N/A",
  "count": int("${count:-0}"),
  "samples": int("${samples:-0}"),
  "ratio_pct": int("${ratio_pct:-0}"),
  "note": "$note",
}
with audit.open("a", encoding="utf-8") as f:
  f.write(json.dumps(entry, ensure_ascii=True) + "\\n")
PY
}

write_state() {
  local b="$1"
  local a="$2"
  local i="$3"
  local ia="$4"
  local ts="$5"
  echo "${b}|${a}|${i}|${ia}|${ts}" > "$STATE_FILE"
}

if [[ ! -f "$AUDIT_FILE" ]]; then
  echo "Laura metrics audit guard: no audit file yet ($AUDIT_FILE)."
  log_audit_event "guard_no_audit_file" "audit file missing at start"
  exit 0
fi

result="$(python3 - <<PY
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

path = Path("$AUDIT_FILE")
window_hours = int("$WINDOW_HOURS")
status_filter = "$STATUS_FILTER"
cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)

count = 0
samples = 0
for line in path.read_text(encoding="utf-8").splitlines():
    s = line.strip()
    if not s:
        continue
    try:
        row = json.loads(s)
        ts = row.get("timestamp")
        status = row.get("status")
        if not ts:
            continue
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt < cutoff:
            continue
        samples += 1
        if status == status_filter:
            count += 1
    except Exception:
        continue

print(f"{count}|{samples}")
PY
)"

count="${result%%|*}"
samples="${result##*|}"

if ! [[ "$count" =~ ^[0-9]+$ ]]; then
  count=0
fi
if ! [[ "$samples" =~ ^[0-9]+$ ]]; then
  samples=0
fi

ratio_pct=0
if (( samples > 0 )); then
  ratio_pct=$(( (count * 100) / samples ))
fi

breach_count=0
alerted=0
insufficient_streak=0
insufficient_alerted=0
state_updated_epoch=0
now_epoch="$(date +%s)"
if [[ -f "$STATE_FILE" ]]; then
  state_raw="$(cat "$STATE_FILE" 2>/dev/null || true)"
  if [[ "$state_raw" == "alerted" ]]; then
    breach_count="$CONSECUTIVE_BREACHES"
    alerted=1
  else
    state_breach="$(echo "$state_raw" | cut -d'|' -f1)"
    state_alerted="$(echo "$state_raw" | cut -d'|' -f2)"
    state_insufficient="$(echo "$state_raw" | cut -d'|' -f3)"
    state_insufficient_alerted="$(echo "$state_raw" | cut -d'|' -f4)"
    state_updated_raw="$(echo "$state_raw" | cut -d'|' -f5)"
    if [[ "$state_breach" =~ ^[0-9]+$ ]]; then
      breach_count="$state_breach"
    fi
    if [[ "$state_alerted" =~ ^[01]$ ]]; then
      alerted="$state_alerted"
    fi
    if [[ "$state_insufficient" =~ ^[0-9]+$ ]]; then
      insufficient_streak="$state_insufficient"
    fi
    if [[ "$state_insufficient_alerted" =~ ^[01]$ ]]; then
      insufficient_alerted="$state_insufficient_alerted"
    fi
    if [[ "$state_updated_raw" =~ ^[0-9]+$ ]]; then
      state_updated_epoch="$state_updated_raw"
    fi
  fi
fi

max_state_age_secs="$((MAX_STATE_AGE_HOURS * 3600))"
if (( state_updated_epoch > 0 && now_epoch - state_updated_epoch > max_state_age_secs )); then
  breach_count=0
  alerted=0
  insufficient_streak=0
  insufficient_alerted=0
  echo "Laura metrics audit guard: stale state reset (age exceeded ${MAX_STATE_AGE_HOURS}h)."
fi

if (( samples < MIN_SAMPLES )); then
  insufficient_streak=$((insufficient_streak + 1))
  if (( insufficient_streak >= MAX_INSUFFICIENT_STREAK )); then
    msg="Laura metrics audit guard ALERT: amostragem insuficiente persistente (${samples}/${MIN_SAMPLES}) por ${insufficient_streak} execucoes consecutivas em ${WINDOW_HOURS}h."
    if (( insufficient_alerted == 0 )); then
      echo "$msg"
      notify "$msg"
      insufficient_alerted=1
    else
      echo "Laura metrics audit guard: insufficient-sample condition still active (${insufficient_streak}/${MAX_INSUFFICIENT_STREAK}), notification suppressed."
    fi
    log_audit_event "guard_insufficient_persistent" "streak=${insufficient_streak}/${MAX_INSUFFICIENT_STREAK}"
  else
    echo "Laura metrics audit guard: insufficient samples (${samples}/${MIN_SAMPLES}) in ${WINDOW_HOURS}h, streak ${insufficient_streak}/${MAX_INSUFFICIENT_STREAK}, skipping alert decision."
    log_audit_event "guard_insufficient_samples" "streak=${insufficient_streak}/${MAX_INSUFFICIENT_STREAK}"
  fi
  write_state "$breach_count" "$alerted" "$insufficient_streak" "$insufficient_alerted" "$now_epoch"
  exit 0
fi

if (( insufficient_alerted == 1 )); then
  notify "Laura metrics audit guard RECOVERY: amostragem voltou ao normal (${samples}/${MIN_SAMPLES}) apos ${insufficient_streak} execucoes insuficientes consecutivas."
fi
insufficient_streak=0
insufficient_alerted=0

if (( count >= MIN_EVENTS && ratio_pct >= MIN_RATIO_PCT )); then
  breach_count=$((breach_count + 1))
  if (( breach_count < CONSECUTIVE_BREACHES )); then
    write_state "$breach_count" "$alerted" "$insufficient_streak" "$insufficient_alerted" "$now_epoch"
    echo "Laura metrics audit guard: breach ${breach_count}/${CONSECUTIVE_BREACHES} (${count}/${samples}=${ratio_pct}%), waiting confirmation."
    log_audit_event "guard_breach_waiting" "breach=${breach_count}/${CONSECUTIVE_BREACHES}"
    exit 0
  fi

  msg="Laura metrics audit guard ALERT: status ${STATUS_FILTER} apareceu ${count} vezes (${ratio_pct}%) em ${samples} eventos nas ultimas ${WINDOW_HOURS}h (limites: min=${MIN_EVENTS}, ratio=${MIN_RATIO_PCT}%)."
  if (( alerted == 0 )); then
    echo "$msg"
    notify "$msg"
    write_state "$breach_count" "1" "$insufficient_streak" "$insufficient_alerted" "$now_epoch"
    log_audit_event "guard_alert_triggered" "breach confirmed"
  else
    echo "Laura metrics audit guard: alert condition still active (${count}/${samples}=${ratio_pct}%), notification suppressed."
    write_state "$breach_count" "1" "$insufficient_streak" "$insufficient_alerted" "$now_epoch"
    log_audit_event "guard_alert_active" "breach still active"
  fi
  exit 1
fi

if (( alerted == 1 )); then
  notify "Laura metrics audit guard RECOVERY: status ${STATUS_FILTER} caiu para ${count}/${samples} (${ratio_pct}%) nas ultimas ${WINDOW_HOURS}h (limites: min=${MIN_EVENTS}, ratio=${MIN_RATIO_PCT}%)."
  log_audit_event "guard_recovery" "condition recovered"
else
  log_audit_event "guard_ok" "within thresholds"
fi
write_state "0" "0" "$insufficient_streak" "$insufficient_alerted" "$now_epoch"

echo "Laura metrics audit guard OK: status ${STATUS_FILTER}=${count}/${samples} (${ratio_pct}%) in ${WINDOW_HOURS}h"
