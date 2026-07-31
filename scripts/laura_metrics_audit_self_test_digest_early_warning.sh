#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
DIGEST_LATEST_FILE="$REPORTS_DIR/laura_metrics_audit_self_test_digest_latest.json"
STATE_FILE="$REPORTS_DIR/laura_metrics_audit_self_test_digest_early_warning.state"
ENABLED="${LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_EARLY_WARNING_ENABLED:-1}"
WARN_AGE_MINUTES="${LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_EARLY_WARNING_WARN_AGE_MINUTES:-1200}"
WINDOW_HOURS="${LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_EARLY_WARNING_WINDOW_HOURS:-24}"
WARN_RUNS_THRESHOLD="${LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_EARLY_WARNING_WARN_RUNS_THRESHOLD:-2}"
TREND_DELTA_PCT="${LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_EARLY_WARNING_TREND_DELTA_PCT:-10}"
ESCALATE_STREAK="${LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_EARLY_WARNING_ESCALATE_STREAK:-6}"
MAX_STATE_AGE_HOURS="${LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_EARLY_WARNING_MAX_STATE_AGE_HOURS:-168}"

if ! [[ "$ENABLED" =~ ^[01]$ ]]; then
  ENABLED=1
fi
if ! [[ "$WARN_AGE_MINUTES" =~ ^[0-9]+$ ]]; then
  WARN_AGE_MINUTES=1200
fi
if ! [[ "$WINDOW_HOURS" =~ ^[0-9]+$ ]]; then
  WINDOW_HOURS=24
fi
if ! [[ "$WARN_RUNS_THRESHOLD" =~ ^[0-9]+$ ]]; then
  WARN_RUNS_THRESHOLD=2
fi
if ! [[ "$TREND_DELTA_PCT" =~ ^[0-9]+$ ]]; then
  TREND_DELTA_PCT=10
fi
if ! [[ "$ESCALATE_STREAK" =~ ^[0-9]+$ ]]; then
  ESCALATE_STREAK=6
fi
if ! [[ "$MAX_STATE_AGE_HOURS" =~ ^[0-9]+$ ]]; then
  MAX_STATE_AGE_HOURS=168
fi

if (( WARN_AGE_MINUTES < 1 )); then
  WARN_AGE_MINUTES=1
fi
if (( WINDOW_HOURS < 1 )); then
  WINDOW_HOURS=1
fi
if (( WARN_RUNS_THRESHOLD < 1 )); then
  WARN_RUNS_THRESHOLD=1
fi
if (( TREND_DELTA_PCT > 100 )); then
  TREND_DELTA_PCT=100
fi
if (( ESCALATE_STREAK < 1 )); then
  ESCALATE_STREAK=1
fi
if (( MAX_STATE_AGE_HOURS < 1 )); then
  MAX_STATE_AGE_HOURS=1
fi

if [[ "$ENABLED" == "0" ]]; then
  echo "Laura self-test digest early warning disabled by LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_EARLY_WARNING_ENABLED=0"
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

if [[ ! -f "$DIGEST_LATEST_FILE" ]]; then
  echo "Laura self-test digest early warning: no digest file yet ($DIGEST_LATEST_FILE)."
  exit 0
fi

result="$(python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

path = Path("$DIGEST_LATEST_FILE")
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    print("INVALID|0|0|0|0|0|0|0|0|unknown|unknown")
    raise SystemExit(0)

now = datetime.now(timezone.utc)
ts = payload.get("timestamp")
if not ts:
    print("INVALID|0|0|0|0|0|0|0|0|unknown|unknown")
    raise SystemExit(0)

try:
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
except Exception:
    print("INVALID|0|0|0|0|0|0|0|0|unknown|unknown")
    raise SystemExit(0)

age_minutes = int((now - dt).total_seconds() // 60)
window_hours = int("$WINDOW_HOURS")
warn_runs_threshold = int("$WARN_RUNS_THRESHOLD")
trend_delta_pct = int("$TREND_DELTA_PCT")

current = payload.get("current") if isinstance(payload.get("current"), dict) else {}
previous = payload.get("previous") if isinstance(payload.get("previous"), dict) else {}
trend = str(payload.get("trend", "NO_BASELINE"))
failed_rate_delta_pct = int(payload.get("failed_rate_delta_pct", 0))
current_runs = int(current.get("total_runs", 0))
current_failed_rate = int(current.get("failed_rate_pct", 0))
previous_failed_rate = int(previous.get("failed_rate_pct", 0))

print(
    f"OK|{age_minutes}|{current_runs}|{current_failed_rate}|{previous_failed_rate}|{failed_rate_delta_pct}|{window_hours}|{warn_runs_threshold}|{trend_delta_pct}|{trend}|{dt.isoformat()}"
)
PY
)"

status="$(echo "$result" | cut -d'|' -f1)"
age_minutes="$(echo "$result" | cut -d'|' -f2)"
current_runs="$(echo "$result" | cut -d'|' -f3)"
current_failed_rate="$(echo "$result" | cut -d'|' -f4)"
previous_failed_rate="$(echo "$result" | cut -d'|' -f5)"
failed_rate_delta_pct="$(echo "$result" | cut -d'|' -f6)"
window_hours="$(echo "$result" | cut -d'|' -f7)"
warn_runs_threshold="$(echo "$result" | cut -d'|' -f8)"
trend_delta_pct="$(echo "$result" | cut -d'|' -f9)"
trend="$(echo "$result" | cut -d'|' -f10)"
last_ts="$(echo "$result" | cut -d'|' -f11-)"

if ! [[ "$age_minutes" =~ ^[0-9]+$ ]]; then
  age_minutes=0
fi
if ! [[ "$current_runs" =~ ^[0-9]+$ ]]; then
  current_runs=0
fi
if ! [[ "$current_failed_rate" =~ ^[0-9]+$ ]]; then
  current_failed_rate=0
fi
if ! [[ "$previous_failed_rate" =~ ^[0-9]+$ ]]; then
  previous_failed_rate=0
fi
if ! [[ "$failed_rate_delta_pct" =~ ^[0-9]+$ ]]; then
  failed_rate_delta_pct=0
fi
if ! [[ "$window_hours" =~ ^[0-9]+$ ]]; then
  window_hours=$WINDOW_HOURS
fi
if ! [[ "$warn_runs_threshold" =~ ^[0-9]+$ ]]; then
  warn_runs_threshold=$WARN_RUNS_THRESHOLD
fi
if ! [[ "$trend_delta_pct" =~ ^[0-9]+$ ]]; then
  trend_delta_pct=$TREND_DELTA_PCT
fi

if [[ "$status" != "OK" ]]; then
  echo "Laura self-test digest early warning: digest invalid, waiting for schema guard."
  exit 0
fi

now_epoch="$(date +%s)"
state_updated_epoch=0
warned=0
warning_streak=0
escalated=0
if [[ -f "$STATE_FILE" ]]; then
  state_raw="$(cat "$STATE_FILE" 2>/dev/null || true)"
  if [[ "$state_raw" == "1" ]]; then
    warned=1
    warning_streak=1
  elif [[ -n "$state_raw" ]]; then
    w="$(echo "$state_raw" | cut -d'|' -f1)"
    s="$(echo "$state_raw" | cut -d'|' -f2)"
    e="$(echo "$state_raw" | cut -d'|' -f3)"
    u="$(echo "$state_raw" | cut -d'|' -f4)"
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
  echo "Laura self-test digest early warning: stale state reset (age exceeded ${MAX_STATE_AGE_HOURS}h)."
fi

warn_age=0
warn_volume=0
warn_trend=0
if (( age_minutes >= WARN_AGE_MINUTES )); then
  warn_age=1
fi
if (( current_runs >= warn_runs_threshold )); then
  warn_volume=1
fi
if [[ "$trend" == "WORSENING" ]] && (( failed_rate_delta_pct >= trend_delta_pct )); then
  warn_trend=1
fi

if (( warn_age == 1 || warn_volume == 1 || warn_trend == 1 )); then
  warning_streak=$((warning_streak + 1))
  msg="Laura self-test digest EARLY WARNING: age=${age_minutes}min/${WARN_AGE_MINUTES}, runs=${current_runs}/${warn_runs_threshold}, trend=${trend} (${previous_failed_rate}% -> ${current_failed_rate}%, delta=${failed_rate_delta_pct}pp). last_ts=${last_ts}."
  if (( warned == 0 )); then
    echo "$msg"
    notify "$msg"
    warned=1
  else
    echo "Laura self-test digest early warning: condition still active, notification suppressed."
  fi

  if (( warning_streak >= ESCALATE_STREAK && escalated == 0 )); then
    esc_msg="Laura self-test digest EARLY WARNING ESCALATION: risco persistente por ${warning_streak} execucoes consecutivas (threshold=${ESCALATE_STREAK}). age=${age_minutes}min, runs=${current_runs}, trend=${trend}."
    echo "$esc_msg"
    notify "$esc_msg"
    escalated=1
  fi

  write_state "$warned" "$warning_streak" "$escalated" "$now_epoch"
  exit 0
fi

if (( warned == 1 || escalated == 1 )); then
  notify "Laura self-test digest EARLY WARNING RECOVERY: risco voltou ao normal (age=${age_minutes}min, runs=${current_runs}, trend=${trend})."
fi
write_state "0" "0" "0" "$now_epoch"

echo "Laura self-test digest early warning OK: age=${age_minutes}min, runs=${current_runs}, trend=${trend}"
