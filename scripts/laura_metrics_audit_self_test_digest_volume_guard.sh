#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
DIGEST_HISTORY_FILE="$REPORTS_DIR/laura_metrics_audit_self_test_digest_history.jsonl"
STATE_FILE="$REPORTS_DIR/laura_metrics_audit_self_test_digest_volume_guard.state"
ENABLED="${LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_VOLUME_GUARD_ENABLED:-1}"
WINDOW_HOURS="${LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_VOLUME_WINDOW_HOURS:-24}"
MAX_DIGEST_RUNS="${LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_VOLUME_MAX_RUNS:-2}"

if ! [[ "$ENABLED" =~ ^[01]$ ]]; then
  ENABLED=1
fi
if ! [[ "$WINDOW_HOURS" =~ ^[0-9]+$ ]]; then
  WINDOW_HOURS=24
fi
if ! [[ "$MAX_DIGEST_RUNS" =~ ^[0-9]+$ ]]; then
  MAX_DIGEST_RUNS=2
fi
if (( WINDOW_HOURS < 1 )); then
  WINDOW_HOURS=1
fi
if (( MAX_DIGEST_RUNS < 1 )); then
  MAX_DIGEST_RUNS=1
fi

if [[ "$ENABLED" == "0" ]]; then
  echo "Laura self-test digest volume guard disabled by LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_VOLUME_GUARD_ENABLED=0"
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

if [[ ! -f "$DIGEST_HISTORY_FILE" ]]; then
  echo "Laura self-test digest volume guard: no digest history yet ($DIGEST_HISTORY_FILE)."
  exit 0
fi

result="$(python3 - <<PY
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

path = Path("$DIGEST_HISTORY_FILE")
window_hours = int("$WINDOW_HOURS")
cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)

total = 0
trend_counts = {}
latest_ts = ""
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
        latest_ts = dt.isoformat()
        trend = str(row.get("trend", "unknown"))
        trend_counts[trend] = trend_counts.get(trend, 0) + 1
    except Exception:
        continue

if trend_counts:
    top_trend = max(trend_counts, key=trend_counts.get)
    top_trend_count = trend_counts[top_trend]
else:
    top_trend = "none"
    top_trend_count = 0

print(f"{total}|{top_trend}|{top_trend_count}|{latest_ts}")
PY
)"

total="$(echo "$result" | cut -d'|' -f1)"
top_trend="$(echo "$result" | cut -d'|' -f2)"
top_trend_count="$(echo "$result" | cut -d'|' -f3)"
latest_ts="$(echo "$result" | cut -d'|' -f4-)"

if ! [[ "$total" =~ ^[0-9]+$ ]]; then
  total=0
fi
if ! [[ "$top_trend_count" =~ ^[0-9]+$ ]]; then
  top_trend_count=0
fi

if (( total > MAX_DIGEST_RUNS )); then
  msg="Laura self-test digest volume ALERT: ${total} digests em ${WINDOW_HOURS}h (limite=${MAX_DIGEST_RUNS}). Top trend=${top_trend} (${top_trend_count}), latest_ts=${latest_ts}."
  if [[ ! -f "$STATE_FILE" ]]; then
    echo "$msg"
    notify "$msg"
    echo "alerted" > "$STATE_FILE"
  else
    echo "Laura self-test digest volume guard: high-volume condition still active (${total} > ${MAX_DIGEST_RUNS}), notification suppressed."
  fi
  exit 1
fi

if [[ -f "$STATE_FILE" ]]; then
  rm -f "$STATE_FILE"
  notify "Laura self-test digest volume RECOVERY: volume voltou ao normal (${total}/${MAX_DIGEST_RUNS} em ${WINDOW_HOURS}h)."
fi

echo "Laura self-test digest volume guard OK: total=${total} (limit=${MAX_DIGEST_RUNS}, window=${WINDOW_HOURS}h, top=${top_trend}:${top_trend_count}, latest_ts=${latest_ts})"
