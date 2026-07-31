#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
AUDIT_FILE="$REPORTS_DIR/laura_webhook_ready_audit.jsonl"
WINDOW_HOURS="${LAURA_WEBHOOK_READY_DIGEST_WINDOW_HOURS:-24}"
ENABLED="${LAURA_WEBHOOK_READY_DIGEST_ENABLED:-1}"

if ! [[ "$WINDOW_HOURS" =~ ^[0-9]+$ ]]; then
  WINDOW_HOURS=24
fi
if ! [[ "$ENABLED" =~ ^[01]$ ]]; then
  ENABLED=1
fi

if [[ "$ENABLED" == "0" ]]; then
  echo "Laura webhook readiness digest disabled by LAURA_WEBHOOK_READY_DIGEST_ENABLED=0"
  exit 0
fi

if [[ ! -f "$AUDIT_FILE" ]]; then
  echo "Webhook readiness audit file not found: $AUDIT_FILE"
  exit 0
fi

cd "$ROOT_DIR"
if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_DIR/.env"
  set +a
fi

summary_json="$(python3 - <<PY
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

path = Path("$AUDIT_FILE")
window_hours = int("$WINDOW_HOURS")
cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)

rows = []
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
        if dt >= cutoff:
            rows.append(row)
    except Exception:
        continue

total = len(rows)
if total == 0:
    print(json.dumps({
        "total": 0,
        "ok_count": 0,
        "fail_count": 0,
        "success_pct": 0.0,
        "auto_healed_count": 0,
        "max_fail_streak": 0,
        "resolver_drift_count": 0,
        "max_resolver_fail_streak": 0,
        "retry_event_count": 0,
        "p95_unsigned_attempts": None,
        "p95_signed_attempts": None,
        "p95_unsigned_latency": None,
        "p95_signed_latency": None,
        "latest_callback_url": "unknown",
        "latest_resolver_source": "unknown",
    }, ensure_ascii=True))
    raise SystemExit(0)

ok_count = sum(1 for r in rows if r.get("status") == "ok")
fail_count = total - ok_count
auto_healed_count = sum(1 for r in rows if int(r.get("auto_healed", 0)) == 1)
max_fail_streak = max(int(r.get("fail_streak", 0)) for r in rows)
resolver_drift_count = sum(1 for r in rows if int(r.get("resolver_drift", 0)) == 1)
max_resolver_fail_streak = max(int(r.get("resolver_fail_streak", 0)) for r in rows)
retry_event_count = sum(
    1
    for r in rows
    if int(r.get("unsigned_attempts", 0)) > 1 or int(r.get("signed_attempts", 0)) > 1
)
latest_callback_url = rows[-1].get("callback_url", "unknown")
latest_resolver_source = rows[-1].get("resolver_source", "unknown")


def p95(values):
    if not values:
        return None
    values = sorted(values)
    idx = int(round(0.95 * (len(values) - 1)))
    return values[idx]


def parse_float(v):
    try:
        x = float(v)
        if x >= 0:
            return x
    except Exception:
        pass
    return None

unsigned = [parse_float(r.get("unsigned_latency_seconds")) for r in rows]
unsigned = [v for v in unsigned if v is not None]
signed = [parse_float(r.get("signed_latency_seconds")) for r in rows]
signed = [v for v in signed if v is not None]
unsigned_attempts = [int(r.get("unsigned_attempts", 0)) for r in rows if str(r.get("unsigned_attempts", "")).isdigit()]
signed_attempts = [int(r.get("signed_attempts", 0)) for r in rows if str(r.get("signed_attempts", "")).isdigit()]

out = {
    "total": total,
    "ok_count": ok_count,
    "fail_count": fail_count,
    "success_pct": round((ok_count / total) * 100.0, 2),
    "auto_healed_count": auto_healed_count,
    "max_fail_streak": max_fail_streak,
    "resolver_drift_count": resolver_drift_count,
    "max_resolver_fail_streak": max_resolver_fail_streak,
    "retry_event_count": retry_event_count,
    "p95_unsigned_attempts": p95(unsigned_attempts),
    "p95_signed_attempts": p95(signed_attempts),
    "p95_unsigned_latency": p95(unsigned),
    "p95_signed_latency": p95(signed),
    "latest_callback_url": latest_callback_url,
    "latest_resolver_source": latest_resolver_source,
}
print(json.dumps(out, ensure_ascii=True))
PY
)"

if [[ -z "${LAURA_ALERT_TELEGRAM_BOT_TOKEN:-}" || -z "${LAURA_ALERT_TELEGRAM_CHAT_ID:-}" ]]; then
  echo "Telegram not configured; readiness digest computed: $summary_json"
  exit 0
fi

message="$(python3 - <<PY
import json
s = json.loads('''$summary_json''')

p95_unsigned = s.get("p95_unsigned_latency")
p95_signed = s.get("p95_signed_latency")
p95_unsigned_attempts = s.get("p95_unsigned_attempts")
p95_signed_attempts = s.get("p95_signed_attempts")

def fmt(v):
    if v is None:
        return "n/a"
    return f"{v:.3f}s"

print(
    "Laura Webhook Readiness Digest (${WINDOW_HOURS}h)\\n"
    f"Host: $(hostname)\\n"
    f"Success: {s.get('ok_count', 0)}/{s.get('total', 0)} ({s.get('success_pct', 0)}%)\\n"
    f"Fails: {s.get('fail_count', 0)}\\n"
    f"Auto-healed: {s.get('auto_healed_count', 0)}\\n"
    f"Max Fail Streak: {s.get('max_fail_streak', 0)}\\n"
    f"Resolver Drift Events: {s.get('resolver_drift_count', 0)}\\n"
    f"Resolver Drift Max Streak: {s.get('max_resolver_fail_streak', 0)}\\n"
    f"Retry Events (>1 attempt): {s.get('retry_event_count', 0)}\\n"
    f"P95 Unsigned Attempts: {p95_unsigned_attempts if p95_unsigned_attempts is not None else 'n/a'}\\n"
    f"P95 Signed Attempts: {p95_signed_attempts if p95_signed_attempts is not None else 'n/a'}\\n"
    f"Resolver Source (latest): {s.get('latest_resolver_source', 'unknown')}\\n"
    f"P95 Unsigned Latency: {fmt(p95_unsigned)}\\n"
    f"P95 Signed Latency: {fmt(p95_signed)}\\n"
    f"Callback: {s.get('latest_callback_url', 'unknown')}"
)
PY
)"

curl -sS -X POST \
  "https://api.telegram.org/bot${LAURA_ALERT_TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${LAURA_ALERT_TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=${message}" \
  >/dev/null

echo "Laura webhook readiness digest sent."