#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
BASELINE_LATEST_FILE="$REPORTS_DIR/laura_profitability_llm_baseline_latest.json"
STATE_FILE="$REPORTS_DIR/laura_profitability_llm_baseline_alert.state"

ENABLED="${LAURA_LLM_BASELINE_ALERT_ENABLED:-1}"
WINDOW_HOURS="${LAURA_LLM_BASELINE_ALERT_WINDOW_HOURS:-24}"
POSTURE_THRESHOLD="${LAURA_LLM_BASELINE_ALERT_POSTURE_THRESHOLD:-ATTENTION}"
CONSECUTIVE_BREACHES="${LAURA_LLM_BASELINE_ALERT_CONSECUTIVE_BREACHES:-2}"
MIN_RUNS="${LAURA_LLM_BASELINE_ALERT_MIN_RUNS:-3}"
ESCALATE_STREAK="${LAURA_LLM_BASELINE_ALERT_ESCALATE_STREAK:-6}"
MAX_STATE_AGE_HOURS="${LAURA_LLM_BASELINE_ALERT_MAX_STATE_AGE_HOURS:-168}"

if ! [[ "$ENABLED" =~ ^[01]$ ]]; then
  ENABLED=1
fi
if ! [[ "$WINDOW_HOURS" =~ ^[0-9]+$ ]]; then
  WINDOW_HOURS=24
fi
if ! [[ "$CONSECUTIVE_BREACHES" =~ ^[0-9]+$ ]]; then
  CONSECUTIVE_BREACHES=2
fi
if ! [[ "$MIN_RUNS" =~ ^[0-9]+$ ]]; then
  MIN_RUNS=3
fi
if ! [[ "$ESCALATE_STREAK" =~ ^[0-9]+$ ]]; then
  ESCALATE_STREAK=6
fi
if ! [[ "$MAX_STATE_AGE_HOURS" =~ ^[0-9]+$ ]]; then
  MAX_STATE_AGE_HOURS=168
fi

if (( CONSECUTIVE_BREACHES < 1 )); then
  CONSECUTIVE_BREACHES=1
fi
if (( MIN_RUNS < 1 )); then
  MIN_RUNS=1
fi
if (( ESCALATE_STREAK < 1 )); then
  ESCALATE_STREAK=1
fi
if (( MAX_STATE_AGE_HOURS < 1 )); then
  MAX_STATE_AGE_HOURS=1
fi

POSTURE_THRESHOLD="$(echo "$POSTURE_THRESHOLD" | tr '[:lower:]' '[:upper:]')"
case "$POSTURE_THRESHOLD" in
  ATTENTION|CRITICAL) ;;
  *)
    POSTURE_THRESHOLD="ATTENTION"
    ;;
esac

if [[ "$ENABLED" == "0" ]]; then
  echo "Laura LLM baseline alert disabled by LAURA_LLM_BASELINE_ALERT_ENABLED=0"
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
  local alerted="$1"
  local streak="$2"
  local escalated="$3"
  local updated_epoch="$4"
  echo "${alerted}|${streak}|${escalated}|${updated_epoch}" > "$STATE_FILE"
}

# Atualiza baseline mais recente antes de avaliar alerta.
if ! ./scripts/laura_llm_baseline_audit.sh --window-hours "$WINDOW_HOURS" >/tmp/laura_llm_baseline_alert_audit.out 2>&1; then
  echo "Laura LLM baseline alert: baseline audit falhou"
  cat /tmp/laura_llm_baseline_alert_audit.out
  exit 1
fi

if [[ ! -f "$BASELINE_LATEST_FILE" ]]; then
  echo "Laura LLM baseline alert: baseline latest nao encontrado ($BASELINE_LATEST_FILE)"
  exit 1
fi

summary_json="$(python3 - <<PY
import json
from pathlib import Path

path = Path("$BASELINE_LATEST_FILE")
row = json.loads(path.read_text(encoding="utf-8"))
posture = str(row.get("posture", "INSUFFICIENT_DATA")).upper()
counts = row.get("counts") or {}
out = {
    "posture": posture,
    "window_hours": row.get("window_hours"),
    "fallback_rate_pct": row.get("fallback_rate_pct"),
    "total_runs": int(counts.get("total_runs", 0) or 0),
    "fallback_runs": int(counts.get("fallback_runs", 0) or 0),
    "native_runs": int(counts.get("native_runs", 0) or 0),
}
print(json.dumps(out, ensure_ascii=True))
PY
)"

posture="$(python3 - <<PY
import json
s = json.loads('''$summary_json''')
print(s.get("posture", "INSUFFICIENT_DATA"))
PY
)"

total_runs="$(python3 - <<PY
import json
s = json.loads('''$summary_json''')
print(s.get("total_runs", 0))
PY
)"

fallback_rate="$(python3 - <<PY
import json
s = json.loads('''$summary_json''')
print(s.get("fallback_rate_pct", "unknown"))
PY
)"

posture_level=0
case "$posture" in
  CRITICAL) posture_level=2 ;;
  ATTENTION) posture_level=1 ;;
  STABLE|INSUFFICIENT_DATA) posture_level=0 ;;
  *) posture_level=0 ;;
esac

threshold_level=1
case "$POSTURE_THRESHOLD" in
  CRITICAL) threshold_level=2 ;;
  ATTENTION) threshold_level=1 ;;
esac

should_breach=0
if (( total_runs >= MIN_RUNS )) && (( posture_level >= threshold_level )); then
  should_breach=1
fi

alerted=0
streak=0
escalated=0
state_updated_epoch=0
now_epoch="$(date +%s)"

if [[ -f "$STATE_FILE" ]]; then
  raw="$(cat "$STATE_FILE" 2>/dev/null || true)"
  if [[ "$raw" == "1" ]]; then
    alerted=1
    streak=1
  elif [[ -n "$raw" ]]; then
    f1="$(echo "$raw" | cut -d'|' -f1)"
    f2="$(echo "$raw" | cut -d'|' -f2)"
    f3="$(echo "$raw" | cut -d'|' -f3)"
    f4="$(echo "$raw" | cut -d'|' -f4)"
    if [[ "$f1" =~ ^[01]$ ]]; then alerted="$f1"; fi
    if [[ "$f2" =~ ^[0-9]+$ ]]; then streak="$f2"; fi
    if [[ "$f3" =~ ^[01]$ ]]; then escalated="$f3"; fi
    if [[ "$f4" =~ ^[0-9]+$ ]]; then state_updated_epoch="$f4"; fi
  fi
fi

max_state_age_secs="$((MAX_STATE_AGE_HOURS * 3600))"
if (( state_updated_epoch > 0 && now_epoch - state_updated_epoch > max_state_age_secs )); then
  alerted=0
  streak=0
  escalated=0
  echo "Laura LLM baseline alert: stale state reset (>${MAX_STATE_AGE_HOURS}h)."
fi

if (( should_breach == 1 )); then
  streak=$((streak + 1))

  if (( alerted == 0 )) && (( streak >= CONSECUTIVE_BREACHES )); then
    msg="Laura LLM baseline ALERT: posture=${posture}, fallback_rate=${fallback_rate}%, total_runs=${total_runs}, threshold=${POSTURE_THRESHOLD}, streak=${streak}/${CONSECUTIVE_BREACHES}."
    echo "$msg"
    notify "$msg"
    alerted=1
  else
    echo "Laura LLM baseline alert pending/active: posture=${posture}, fallback_rate=${fallback_rate}%, streak=${streak}."
  fi

  if (( streak >= ESCALATE_STREAK )) && (( escalated == 0 )); then
    esc_msg="Laura LLM baseline ALERT ESCALATION: risco persistente por ${streak} execucoes, posture=${posture}, fallback_rate=${fallback_rate}%."
    echo "$esc_msg"
    notify "$esc_msg"
    escalated=1
  fi

  write_state "$alerted" "$streak" "$escalated" "$now_epoch"
  exit 0
fi

if (( alerted == 1 || escalated == 1 )); then
  recovery_msg="Laura LLM baseline RECOVERY: posture=${posture}, fallback_rate=${fallback_rate}%, total_runs=${total_runs}."
  echo "$recovery_msg"
  notify "$recovery_msg"
fi

write_state "0" "0" "0" "$now_epoch"
echo "Laura LLM baseline alert OK: posture=${posture}, fallback_rate=${fallback_rate}%, total_runs=${total_runs}."
