#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
AUDIT_FILE="$REPORTS_DIR/laura_metrics_auto_remediate_audit.jsonl"
GUARD_STATE_FILE="$REPORTS_DIR/laura_metrics_audit_guard.state"
STATE_FILE="$REPORTS_DIR/laura_metrics_audit_early_warning.state"

ENABLED="${LAURA_METRICS_AUDIT_EARLY_WARNING_ENABLED:-1}"
WINDOW_HOURS="${LAURA_METRICS_AUDIT_EARLY_WARNING_WINDOW_HOURS:-24}"
TREND_DELTA_PCT="${LAURA_METRICS_AUDIT_EARLY_WARNING_TREND_DELTA_PCT:-10}"
GUARD_CONSECUTIVE_BREACHES="${LAURA_METRICS_AUDIT_GUARD_CONSECUTIVE_BREACHES:-2}"
GUARD_MAX_INSUFFICIENT_STREAK="${LAURA_METRICS_AUDIT_GUARD_MAX_INSUFFICIENT_STREAK:-12}"
GUARD_INTERVAL_MINUTES="${LAURA_METRICS_AUDIT_GUARD_INTERVAL_MINUTES:-60}"
MAX_BREACH_ETA_MIN="${LAURA_METRICS_AUDIT_EARLY_WARNING_MAX_BREACH_ETA_MIN:-120}"
MAX_INSUFF_ETA_MIN="${LAURA_METRICS_AUDIT_EARLY_WARNING_MAX_INSUFF_ETA_MIN:-180}"
ESCALATE_STREAK="${LAURA_METRICS_AUDIT_EARLY_WARNING_ESCALATE_STREAK:-6}"
MAX_STATE_AGE_HOURS="${LAURA_METRICS_AUDIT_EARLY_WARNING_MAX_STATE_AGE_HOURS:-168}"

if ! [[ "$ENABLED" =~ ^[01]$ ]]; then
  ENABLED=1
fi
if ! [[ "$WINDOW_HOURS" =~ ^[0-9]+$ ]]; then
  WINDOW_HOURS=24
fi
if ! [[ "$TREND_DELTA_PCT" =~ ^[0-9]+$ ]]; then
  TREND_DELTA_PCT=10
fi
if ! [[ "$GUARD_CONSECUTIVE_BREACHES" =~ ^[0-9]+$ ]]; then
  GUARD_CONSECUTIVE_BREACHES=2
fi
if ! [[ "$GUARD_MAX_INSUFFICIENT_STREAK" =~ ^[0-9]+$ ]]; then
  GUARD_MAX_INSUFFICIENT_STREAK=12
fi
if ! [[ "$GUARD_INTERVAL_MINUTES" =~ ^[0-9]+$ ]]; then
  GUARD_INTERVAL_MINUTES=60
fi
if ! [[ "$MAX_BREACH_ETA_MIN" =~ ^[0-9]+$ ]]; then
  MAX_BREACH_ETA_MIN=120
fi
if ! [[ "$MAX_INSUFF_ETA_MIN" =~ ^[0-9]+$ ]]; then
  MAX_INSUFF_ETA_MIN=180
fi
if ! [[ "$ESCALATE_STREAK" =~ ^[0-9]+$ ]]; then
  ESCALATE_STREAK=6
fi
if ! [[ "$MAX_STATE_AGE_HOURS" =~ ^[0-9]+$ ]]; then
  MAX_STATE_AGE_HOURS=168
fi

if (( GUARD_CONSECUTIVE_BREACHES < 1 )); then
  GUARD_CONSECUTIVE_BREACHES=1
fi
if (( GUARD_MAX_INSUFFICIENT_STREAK < 1 )); then
  GUARD_MAX_INSUFFICIENT_STREAK=1
fi
if (( GUARD_INTERVAL_MINUTES < 1 )); then
  GUARD_INTERVAL_MINUTES=1
fi
if (( ESCALATE_STREAK < 1 )); then
  ESCALATE_STREAK=1
fi
if (( MAX_STATE_AGE_HOURS < 1 )); then
  MAX_STATE_AGE_HOURS=1
fi

if [[ "$ENABLED" == "0" ]]; then
  echo "Laura metrics audit early warning disabled by LAURA_METRICS_AUDIT_EARLY_WARNING_ENABLED=0"
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

write_state() {
  local warned="$1"
  local streak="$2"
  local escalated="$3"
  local updated_epoch="$4"
  echo "${warned}|${streak}|${escalated}|${updated_epoch}" > "$STATE_FILE"
}

if [[ ! -f "$AUDIT_FILE" ]]; then
  echo "Laura metrics audit early warning: no audit file yet ($AUDIT_FILE)."
  exit 0
fi

summary="$(python3 - <<PY
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

path = Path("$AUDIT_FILE")
window_hours = int("$WINDOW_HOURS")
trend_delta_pct = int("$TREND_DELTA_PCT")
now = datetime.now(timezone.utc)
current_cutoff = now - timedelta(hours=window_hours)
previous_cutoff = now - timedelta(hours=window_hours * 2)

current_rows = []
previous_rows = []
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
        if dt >= current_cutoff:
            current_rows.append(row)
        elif previous_cutoff <= dt < current_cutoff:
            previous_rows.append(row)
    except Exception:
        continue

curr_total = len(current_rows)
prev_total = len(previous_rows)
curr_skipped = sum(1 for r in current_rows if str(r.get("status", "unknown")) == "skipped_health_band")
prev_skipped = sum(1 for r in previous_rows if str(r.get("status", "unknown")) == "skipped_health_band")

curr_rate = int((curr_skipped * 100) / curr_total) if curr_total > 0 else 0
prev_rate = int((prev_skipped * 100) / prev_total) if prev_total > 0 else 0
delta = curr_rate - prev_rate

if prev_total == 0:
    trend = "NO_BASELINE"
elif delta >= trend_delta_pct:
    trend = "WORSENING"
elif delta <= -trend_delta_pct:
    trend = "IMPROVING"
else:
    trend = "STABLE"

print(json.dumps({
    "trend": trend,
    "delta": delta,
    "curr_rate": curr_rate,
    "prev_rate": prev_rate,
    "curr_total": curr_total,
    "prev_total": prev_total,
}, ensure_ascii=True))
PY
)"

state_raw=""
if [[ -f "$GUARD_STATE_FILE" ]]; then
  state_raw="$(cat "$GUARD_STATE_FILE" 2>/dev/null || true)"
fi

breach_count=0
alert_active=0
insufficient_streak=0
insufficient_alert_active=0
if [[ "$state_raw" == "alerted" ]]; then
  breach_count="$GUARD_CONSECUTIVE_BREACHES"
  alert_active=1
elif [[ -n "$state_raw" ]]; then
  b="$(echo "$state_raw" | cut -d'|' -f1)"
  a="$(echo "$state_raw" | cut -d'|' -f2)"
  i="$(echo "$state_raw" | cut -d'|' -f3)"
  ia="$(echo "$state_raw" | cut -d'|' -f4)"
  if [[ "$b" =~ ^[0-9]+$ ]]; then breach_count="$b"; fi
  if [[ "$a" =~ ^[01]$ ]]; then alert_active="$a"; fi
  if [[ "$i" =~ ^[0-9]+$ ]]; then insufficient_streak="$i"; fi
  if [[ "$ia" =~ ^[01]$ ]]; then insufficient_alert_active="$ia"; fi
fi

if (( alert_active == 1 )); then
  breach_remaining=0
else
  breach_remaining=$((GUARD_CONSECUTIVE_BREACHES - breach_count))
  if (( breach_remaining < 0 )); then breach_remaining=0; fi
fi

if (( insufficient_alert_active == 1 )); then
  insufficient_remaining=0
else
  insufficient_remaining=$((GUARD_MAX_INSUFFICIENT_STREAK - insufficient_streak))
  if (( insufficient_remaining < 0 )); then insufficient_remaining=0; fi
fi

breach_eta_min=$((breach_remaining * GUARD_INTERVAL_MINUTES))
insufficient_eta_min=$((insufficient_remaining * GUARD_INTERVAL_MINUTES))

trend="$(python3 - <<PY
import json
s = json.loads('''$summary''')
print(s.get("trend", "NO_BASELINE"))
PY
)"
delta="$(python3 - <<PY
import json
s = json.loads('''$summary''')
print(s.get("delta", 0))
PY
)"
curr_rate="$(python3 - <<PY
import json
s = json.loads('''$summary''')
print(s.get("curr_rate", 0))
PY
)"
prev_rate="$(python3 - <<PY
import json
s = json.loads('''$summary''')
print(s.get("prev_rate", 0))
PY
)"

risk_breach=0
risk_insufficient=0
if (( breach_eta_min <= MAX_BREACH_ETA_MIN )); then
  risk_breach=1
fi
if (( insufficient_eta_min <= MAX_INSUFF_ETA_MIN )); then
  risk_insufficient=1
fi

trigger=0
if [[ "$trend" == "WORSENING" ]] && (( risk_breach == 1 || risk_insufficient == 1 )); then
  trigger=1
fi

warned=0
warning_streak=0
escalated=0
state_updated_epoch=0
now_epoch="$(date +%s)"
if [[ -f "$STATE_FILE" ]]; then
  warned_raw="$(cat "$STATE_FILE" 2>/dev/null || true)"
  if [[ "$warned_raw" == "1" ]]; then
    warned=1
    warning_streak=1
  elif [[ -n "$warned_raw" ]]; then
    w="$(echo "$warned_raw" | cut -d'|' -f1)"
    s="$(echo "$warned_raw" | cut -d'|' -f2)"
    e="$(echo "$warned_raw" | cut -d'|' -f3)"
    u="$(echo "$warned_raw" | cut -d'|' -f4)"
    if [[ "$w" =~ ^[01]$ ]]; then warned="$w"; fi
    if [[ "$s" =~ ^[0-9]+$ ]]; then warning_streak="$s"; fi
    if [[ "$e" =~ ^[01]$ ]]; then escalated="$e"; fi
    if [[ "$u" =~ ^[0-9]+$ ]]; then state_updated_epoch="$u"; fi
  fi
fi

max_state_age_secs="$((MAX_STATE_AGE_HOURS * 3600))"
if (( state_updated_epoch > 0 && now_epoch - state_updated_epoch > max_state_age_secs )); then
  warned=0
  warning_streak=0
  escalated=0
  echo "Laura metrics audit early warning: stale state reset (age exceeded ${MAX_STATE_AGE_HOURS}h)."
fi

if (( trigger == 1 )); then
  warning_streak=$((warning_streak + 1))
  msg="Laura metrics audit EARLY WARNING: tendencia WORSENING em skipped_health_band (${prev_rate}% -> ${curr_rate}%, delta=${delta}pp). ETA breach=${breach_eta_min}min (<=${MAX_BREACH_ETA_MIN}) e ETA insufficient=${insufficient_eta_min}min (<=${MAX_INSUFF_ETA_MIN})."
  if (( warned == 0 )); then
    echo "$msg"
    notify "$msg"
    warned=1
  else
    echo "Laura metrics audit early warning: condition still active, notification suppressed."
  fi

  if (( warning_streak >= ESCALATE_STREAK && escalated == 0 )); then
    esc_msg="Laura metrics audit EARLY WARNING ESCALATION: risco persistente por ${warning_streak} execucoes consecutivas (threshold=${ESCALATE_STREAK}). Trend=${trend}, skipped ${prev_rate}% -> ${curr_rate}%, ETA breach=${breach_eta_min}min, ETA insufficient=${insufficient_eta_min}min."
    echo "$esc_msg"
    notify "$esc_msg"
    escalated=1
  fi

  write_state "$warned" "$warning_streak" "$escalated" "$now_epoch"
  exit 0
fi

if (( warned == 1 || escalated == 1 )); then
  notify "Laura metrics audit EARLY WARNING RECOVERY: tendencia/ETA voltou para zona segura (trend=${trend}, breach_eta=${breach_eta_min}min, insufficient_eta=${insufficient_eta_min}min, streak=${warning_streak})."
fi
write_state "0" "0" "0" "$now_epoch"

echo "Laura metrics audit early warning OK: trend=${trend}, breach_eta=${breach_eta_min}min, insufficient_eta=${insufficient_eta_min}min"
