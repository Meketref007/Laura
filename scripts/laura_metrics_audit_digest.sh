#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
AUDIT_FILE="$REPORTS_DIR/laura_metrics_auto_remediate_audit.jsonl"
GUARD_STATE_FILE="$REPORTS_DIR/laura_metrics_audit_guard.state"
EARLY_STATE_FILE="$REPORTS_DIR/laura_metrics_audit_early_warning.state"
ENABLED="${LAURA_METRICS_AUDIT_DIGEST_ENABLED:-1}"
WINDOW_HOURS="${LAURA_METRICS_AUDIT_DIGEST_WINDOW_HOURS:-24}"
TREND_DELTA_PCT="${LAURA_METRICS_AUDIT_DIGEST_TREND_DELTA_PCT:-10}"
GUARD_CONSECUTIVE_BREACHES="${LAURA_METRICS_AUDIT_GUARD_CONSECUTIVE_BREACHES:-2}"
GUARD_MAX_INSUFFICIENT_STREAK="${LAURA_METRICS_AUDIT_GUARD_MAX_INSUFFICIENT_STREAK:-12}"
GUARD_INTERVAL_MINUTES="${LAURA_METRICS_AUDIT_GUARD_INTERVAL_MINUTES:-60}"

if ! [[ "$ENABLED" =~ ^[01]$ ]]; then
  ENABLED=1
fi
if ! [[ "$WINDOW_HOURS" =~ ^[0-9]+$ ]]; then
  WINDOW_HOURS=24
fi
if ! [[ "$TREND_DELTA_PCT" =~ ^[0-9]+$ ]]; then
  TREND_DELTA_PCT=10
fi
if (( TREND_DELTA_PCT > 100 )); then
  TREND_DELTA_PCT=100
fi
if ! [[ "$GUARD_CONSECUTIVE_BREACHES" =~ ^[0-9]+$ ]]; then
  GUARD_CONSECUTIVE_BREACHES=2
fi
if (( GUARD_CONSECUTIVE_BREACHES < 1 )); then
  GUARD_CONSECUTIVE_BREACHES=1
fi
if ! [[ "$GUARD_MAX_INSUFFICIENT_STREAK" =~ ^[0-9]+$ ]]; then
  GUARD_MAX_INSUFFICIENT_STREAK=12
fi
if (( GUARD_MAX_INSUFFICIENT_STREAK < 1 )); then
  GUARD_MAX_INSUFFICIENT_STREAK=1
fi
if ! [[ "$GUARD_INTERVAL_MINUTES" =~ ^[0-9]+$ ]]; then
  GUARD_INTERVAL_MINUTES=60
fi
if (( GUARD_INTERVAL_MINUTES < 1 )); then
  GUARD_INTERVAL_MINUTES=1
fi

if [[ "$ENABLED" == "0" ]]; then
  echo "Laura metrics audit digest disabled by LAURA_METRICS_AUDIT_DIGEST_ENABLED=0"
  exit 0
fi

cd "$ROOT_DIR"
set -a
source "$ROOT_DIR/.env"
set +a

if [[ ! -f "$AUDIT_FILE" ]]; then
  echo "Laura metrics audit digest: no audit file yet ($AUDIT_FILE)."
  exit 0
fi

summary_json="$(python3 - <<PY
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

total = len(current_rows)
status_counts = {}
cause_counts = {}
script_counts = {}
for r in current_rows:
    status = str(r.get("status", "unknown"))
    cause = str(r.get("cause", "unknown"))
    script = str(r.get("script", "unknown"))
    status_counts[status] = status_counts.get(status, 0) + 1
    cause_counts[cause] = cause_counts.get(cause, 0) + 1
    script_counts[script] = script_counts.get(script, 0) + 1

def top_item(d):
    if not d:
        return ("none", 0)
    k = max(d, key=d.get)
    return (k, d[k])

top_status, top_status_count = top_item(status_counts)
top_cause, top_cause_count = top_item(cause_counts)
top_script, top_script_count = top_item(script_counts)

prev_total = len(previous_rows)
prev_skipped = sum(1 for r in previous_rows if str(r.get("status", "unknown")) == "skipped_health_band")
curr_skipped = status_counts.get("skipped_health_band", 0)

curr_rate = int((curr_skipped * 100) / total) if total > 0 else 0
prev_rate = int((prev_skipped * 100) / prev_total) if prev_total > 0 else 0
rate_delta = curr_rate - prev_rate

if prev_total == 0:
  trend = "NO_BASELINE"
elif rate_delta >= trend_delta_pct:
  trend = "WORSENING"
elif rate_delta <= -trend_delta_pct:
  trend = "IMPROVING"
else:
  trend = "STABLE"

out = {
    "total": total,
  "prev_total": prev_total,
    "top_status": top_status,
    "top_status_count": top_status_count,
    "top_cause": top_cause,
    "top_cause_count": top_cause_count,
    "top_script": top_script,
    "top_script_count": top_script_count,
    "status_counts": status_counts,
    "curr_skipped_rate_pct": curr_rate,
    "prev_skipped_rate_pct": prev_rate,
    "skipped_rate_delta_pct": rate_delta,
    "skipped_rate_trend": trend,
}
print(json.dumps(out, ensure_ascii=True))
PY
)"

guard_state_json="$(python3 - <<PY
import json
import time
from pathlib import Path

path = Path("$GUARD_STATE_FILE")
raw = path.read_text(encoding="utf-8").strip() if path.exists() else ""

breach_count = 0
alerted = 0
insufficient_streak = 0
insufficient_alerted = 0
updated_epoch = 0
state_age_seconds = -1

if raw == "alerted":
  breach_count = 1
  alerted = 1
elif raw:
  parts = raw.split("|")
  if len(parts) >= 1 and parts[0].isdigit():
    breach_count = int(parts[0])
  if len(parts) >= 2 and parts[1] in {"0", "1"}:
    alerted = int(parts[1])
  if len(parts) >= 3 and parts[2].isdigit():
    insufficient_streak = int(parts[2])
  if len(parts) >= 4 and parts[3] in {"0", "1"}:
    insufficient_alerted = int(parts[3])
  if len(parts) >= 5 and parts[4].isdigit():
    updated_epoch = int(parts[4])

if updated_epoch > 0:
  state_age_seconds = int(time.time()) - updated_epoch

out = {
  "present": path.exists(),
  "raw": raw,
  "breach_count": breach_count,
  "alerted": alerted,
  "insufficient_streak": insufficient_streak,
  "insufficient_alerted": insufficient_alerted,
  "updated_epoch": updated_epoch,
  "state_age_seconds": state_age_seconds,
}
print(json.dumps(out, ensure_ascii=True))
PY
)"

early_state_json="$(python3 - <<PY
import json
import time
from pathlib import Path

path = Path("$EARLY_STATE_FILE")
raw = path.read_text(encoding="utf-8").strip() if path.exists() else ""

warned = 0
streak = 0
escalated = 0
updated_epoch = 0
state_age_seconds = -1

if raw == "1":
  warned = 1
  streak = 1
elif raw:
  parts = raw.split("|")
  if len(parts) >= 1 and parts[0] in {"0", "1"}:
    warned = int(parts[0])
  if len(parts) >= 2 and parts[1].isdigit():
    streak = int(parts[1])
  if len(parts) >= 3 and parts[2] in {"0", "1"}:
    escalated = int(parts[2])
  if len(parts) >= 4 and parts[3].isdigit():
    updated_epoch = int(parts[3])

if updated_epoch > 0:
  state_age_seconds = int(time.time()) - updated_epoch

out = {
  "present": path.exists(),
  "raw": raw,
  "warned": warned,
  "streak": streak,
  "escalated": escalated,
  "updated_epoch": updated_epoch,
  "state_age_seconds": state_age_seconds,
}
print(json.dumps(out, ensure_ascii=True))
PY
)"

message="$(python3 - <<PY
import json

s = json.loads('''$summary_json''')
g = json.loads('''$guard_state_json''')
e = json.loads('''$early_state_json''')
status_counts = s.get("status_counts", {})
breach_count = int(g.get("breach_count", 0))
alert_active = int(g.get("alerted", 0))
insufficient_streak = int(g.get("insufficient_streak", 0))
insufficient_alert_active = int(g.get("insufficient_alerted", 0))
guard_consecutive = int("$GUARD_CONSECUTIVE_BREACHES")
guard_insufficient_max = int("$GUARD_MAX_INSUFFICIENT_STREAK")
guard_interval_minutes = int("$GUARD_INTERVAL_MINUTES")

if alert_active == 1:
  breach_remaining = 0
else:
  breach_remaining = max(0, guard_consecutive - breach_count)

if insufficient_alert_active == 1:
  insufficient_remaining = 0
else:
  insufficient_remaining = max(0, guard_insufficient_max - insufficient_streak)

breach_eta_min = breach_remaining * guard_interval_minutes
insufficient_eta_min = insufficient_remaining * guard_interval_minutes

curr_rate = int(s.get("curr_skipped_rate_pct", 0))
prev_rate = int(s.get("prev_skipped_rate_pct", 0))
rate_delta = int(s.get("skipped_rate_delta_pct", 0))
trend = s.get("skipped_rate_trend", "NO_BASELINE")

if trend == "NO_BASELINE":
  trend_line = "Skipped Trend: NO_BASELINE"
else:
  sign = "+" if rate_delta > 0 else ""
  trend_line = f"Skipped Trend: {trend} ({sign}{rate_delta}pp, {prev_rate}% -> {curr_rate}%)"

def get(name):
    return status_counts.get(name, 0)

lines = [
    "Laura Metrics Audit Digest (${WINDOW_HOURS}h)",
    f"Host: $(hostname)",
    f"Events: {s.get('total', 0)}",
    f"Top Status: {s.get('top_status', 'none')} ({s.get('top_status_count', 0)})",
    f"Top Cause: {s.get('top_cause', 'none')} ({s.get('top_cause_count', 0)})",
    f"Top Script: {s.get('top_script', 'none')} ({s.get('top_script_count', 0)})",
    trend_line,
    f"skipped_health_band: {get('skipped_health_band')}",
    f"skipped_no_data: {get('skipped_no_data')}",
    f"cooldown: {get('cooldown')}",
    f"success: {get('success')}",
    f"failed: {get('failed')}",
    f"Guard Breach Count: {g.get('breach_count', 0)}",
    f"Guard Alert Active: {g.get('alerted', 0)}",
    f"Guard Breach Remaining: {breach_remaining}",
    f"Guard Breach ETA Min: {breach_eta_min}",
    f"Insufficient Streak: {g.get('insufficient_streak', 0)}",
    f"Insufficient Alert Active: {g.get('insufficient_alerted', 0)}",
    f"Insufficient Remaining: {insufficient_remaining}",
    f"Insufficient ETA Min: {insufficient_eta_min}",
    f"Guard State Age Sec: {g.get('state_age_seconds', -1)}",
    f"Early Warning Active: {e.get('warned', 0)}",
    f"Early Warning Streak: {e.get('streak', 0)}",
    f"Early Warning Escalated: {e.get('escalated', 0)}",
    f"Early State Age Sec: {e.get('state_age_seconds', -1)}",
]
print("\\n".join(lines))
PY
)"

if [[ -z "${LAURA_ALERT_TELEGRAM_BOT_TOKEN:-}" || -z "${LAURA_ALERT_TELEGRAM_CHAT_ID:-}" ]]; then
  echo "Telegram not configured; audit digest: $summary_json"
  exit 0
fi

curl -sS -X POST \
  "https://api.telegram.org/bot${LAURA_ALERT_TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${LAURA_ALERT_TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=${message}" \
  >/dev/null

echo "Laura metrics audit digest sent."
