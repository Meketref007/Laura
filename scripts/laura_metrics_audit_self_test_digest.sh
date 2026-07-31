#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
HISTORY_FILE="$REPORTS_DIR/laura_metrics_audit_self_test_history.jsonl"
LATEST_FILE="$REPORTS_DIR/laura_metrics_audit_self_test_digest_latest.json"
DIGEST_HISTORY_FILE="$REPORTS_DIR/laura_metrics_audit_self_test_digest_history.jsonl"
ENABLED="${LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_ENABLED:-1}"
WINDOW_HOURS="${LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_WINDOW_HOURS:-24}"
TREND_DELTA_PCT="${LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_TREND_DELTA_PCT:-10}"

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
if (( WINDOW_HOURS < 1 )); then
  WINDOW_HOURS=1
fi

if [[ "$ENABLED" == "0" ]]; then
  echo "Laura metrics audit self-test digest disabled by LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_ENABLED=0"
  exit 0
fi

cd "$ROOT_DIR"
set -a
source "$ROOT_DIR/.env"
set +a

if [[ ! -f "$HISTORY_FILE" ]]; then
  echo "Laura metrics audit self-test digest: no history file yet ($HISTORY_FILE)."
  exit 0
fi

mkdir -p "$REPORTS_DIR"

summary_json="$(python3 - <<PY
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

path = Path("$HISTORY_FILE")
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

def aggregate(rows):
    total_runs = len(rows)
    failed_runs = 0
    total_failures = 0
    failed_checks = {}
    last_failure_ts = ""
    for row in rows:
        failures = int(row.get("failures", 0))
        checks = row.get("checks", [])
        if failures > 0:
            failed_runs += 1
            total_failures += failures
            ts = str(row.get("timestamp", ""))
            if ts:
                last_failure_ts = ts
            if isinstance(checks, list):
                for item in checks:
                    if not isinstance(item, dict):
                        continue
                    status = str(item.get("status", ""))
                    name = str(item.get("name", "unknown"))
                    if status != "OK":
                        failed_checks[name] = failed_checks.get(name, 0) + 1
        else:
            if isinstance(checks, list):
                for item in checks:
                    if not isinstance(item, dict):
                        continue
                    status = str(item.get("status", ""))
                    name = str(item.get("name", "unknown"))
                    if status != "OK":
                        failed_checks[name] = failed_checks.get(name, 0) + 1
    failed_rate_pct = int((failed_runs * 100) / total_runs) if total_runs > 0 else 0
    top_failed_check = "none"
    top_failed_check_count = 0
    if failed_checks:
        top_failed_check = max(failed_checks, key=failed_checks.get)
        top_failed_check_count = int(failed_checks[top_failed_check])
    return {
        "total_runs": total_runs,
        "failed_runs": failed_runs,
        "failed_rate_pct": failed_rate_pct,
        "total_failures": total_failures,
        "failed_checks": failed_checks,
        "top_failed_check": top_failed_check,
        "top_failed_check_count": top_failed_check_count,
        "last_failure_ts": last_failure_ts,
    }

curr = aggregate(current_rows)
prev = aggregate(previous_rows)
rate_delta = int(curr["failed_rate_pct"] - prev["failed_rate_pct"])

if prev["total_runs"] == 0:
    trend = "NO_BASELINE"
elif rate_delta >= trend_delta_pct:
    trend = "WORSENING"
elif rate_delta <= -trend_delta_pct:
    trend = "IMPROVING"
else:
    trend = "STABLE"

payload = {
    "timestamp": now.isoformat(),
    "host": "$(hostname)",
    "window_hours": window_hours,
    "trend_delta_pct": trend_delta_pct,
    "current": curr,
    "previous": prev,
    "failed_rate_delta_pct": rate_delta,
    "trend": trend,
}
print(json.dumps(payload, ensure_ascii=True))
PY
)"

python3 - <<PY
import json
from pathlib import Path

payload = json.loads('''$summary_json''')
latest = Path("$LATEST_FILE")
history = Path("$DIGEST_HISTORY_FILE")
latest.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
with history.open("a", encoding="utf-8") as f:
    f.write(json.dumps(payload, ensure_ascii=True) + "\n")
PY

message="$(python3 - <<PY
import json

s = json.loads('''$summary_json''')
c = s.get("current", {})
p = s.get("previous", {})
trend = s.get("trend", "NO_BASELINE")
rate_delta = int(s.get("failed_rate_delta_pct", 0))

delta_text = ""
if trend != "NO_BASELINE":
    sign = "+" if rate_delta > 0 else ""
    delta_text = f" ({sign}{rate_delta}pp)"

lines = [
    f"Laura Audit Self-Test Digest ({s.get('window_hours', 24)}h)",
    f"Host: {s.get('host', 'unknown')}",
    f"Runs: {c.get('total_runs', 0)}",
    f"Failed Runs: {c.get('failed_runs', 0)} ({c.get('failed_rate_pct', 0)}%)",
    f"Total Failed Checks: {c.get('total_failures', 0)}",
    f"Top Failed Check: {c.get('top_failed_check', 'none')} ({c.get('top_failed_check_count', 0)})",
    f"Trend: {trend}{delta_text}",
    f"Previous Failed Rate: {p.get('failed_rate_pct', 0)}%",
    f"Last Failure: {c.get('last_failure_ts', 'N/A') or 'N/A'}",
    f"Artifacts: $LATEST_FILE | $DIGEST_HISTORY_FILE",
]
print("\\n".join(lines))
PY
)"

if [[ -z "${LAURA_ALERT_TELEGRAM_BOT_TOKEN:-}" || -z "${LAURA_ALERT_TELEGRAM_CHAT_ID:-}" ]]; then
  echo "$message"
  exit 0
fi

curl -sS -X POST \
  "https://api.telegram.org/bot${LAURA_ALERT_TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${LAURA_ALERT_TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=${message}" \
  >/dev/null

echo "$message"
