#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
METRICS_FILE="$REPORTS_DIR/laura_metrics.jsonl"
STATE_FILE="$REPORTS_DIR/laura_metrics_guard.state"
WINDOW_HOURS="${LAURA_METRICS_GUARD_WINDOW_HOURS:-24}"
MIN_SUCCESS_PCT="${LAURA_METRICS_GUARD_MIN_SUCCESS_PCT:-90}"
MIN_SAMPLES="${LAURA_METRICS_GUARD_MIN_SAMPLES:-6}"

if ! [[ "$WINDOW_HOURS" =~ ^[0-9]+$ ]]; then
  WINDOW_HOURS=24
fi
if ! [[ "$MIN_SUCCESS_PCT" =~ ^[0-9]+$ ]]; then
  MIN_SUCCESS_PCT=90
fi
if ! [[ "$MIN_SAMPLES" =~ ^[0-9]+$ ]]; then
  MIN_SAMPLES=6
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

if [[ ! -f "$METRICS_FILE" ]]; then
  echo "Laura metrics guard: no metrics file yet ($METRICS_FILE)."
  exit 0
fi

result="$(python3 - <<PY
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

metrics_file = Path("$METRICS_FILE")
window_hours = int("$WINDOW_HOURS")
cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)

rows = []
for line in metrics_file.read_text(encoding="utf-8").splitlines():
    s = line.strip()
    if not s:
        continue
    try:
        row = json.loads(s)
        ts = row.get("timestamp")
        if not ts:
            continue
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt >= cutoff:
            rows.append(row)
    except Exception:
        continue

total = len(rows)
if total == 0:
    print("NO_DATA|0|0|0")
else:
    oks = 0
    for r in rows:
        if r.get("api_ok") and r.get("cron_ok") and r.get("backup_verify_ok"):
            oks += 1
    pct = int((oks * 100) / total)
    print(f"OK|{total}|{oks}|{pct}")
PY
)"

status="$(echo "$result" | cut -d'|' -f1)"
total="$(echo "$result" | cut -d'|' -f2)"
oks="$(echo "$result" | cut -d'|' -f3)"
pct="$(echo "$result" | cut -d'|' -f4)"

if [[ "$status" == "NO_DATA" ]]; then
  echo "Laura metrics guard: no data in the last ${WINDOW_HOURS}h."
  exit 0
fi

if (( total < MIN_SAMPLES )); then
  echo "Laura metrics guard: insufficient samples (${total}/${MIN_SAMPLES}) in ${WINDOW_HOURS}h, skipping alert decision."
  exit 0
fi

if (( pct < MIN_SUCCESS_PCT )); then
  msg="Laura metrics guard ALERT: taxa de sucesso ${pct}% abaixo do minimo ${MIN_SUCCESS_PCT}% nas ultimas ${WINDOW_HOURS}h (ok=${oks}, total=${total})."
  if [[ ! -f "$STATE_FILE" ]]; then
    echo "$msg"
    notify "$msg"
    echo "alerted" > "$STATE_FILE"
  else
    echo "Laura metrics guard: alert condition still active (${pct}% < ${MIN_SUCCESS_PCT}%), notification suppressed."
  fi
  exit 1
fi

if [[ -f "$STATE_FILE" ]]; then
  rm -f "$STATE_FILE"
  notify "Laura metrics guard RECOVERY: taxa de sucesso voltou para ${pct}% (limite ${MIN_SUCCESS_PCT}%)."
fi

echo "Laura metrics guard OK: success=${pct}% (ok=${oks}, total=${total})"
