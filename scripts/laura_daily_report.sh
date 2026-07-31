#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
LOG_FILE="$ROOT_DIR/logs/laura_healthcheck.log"
PY_CMD="$ROOT_DIR/.venv/bin/python"

if [[ ! -x "$PY_CMD" ]]; then
  PY_CMD="python3"
fi

cd "$ROOT_DIR"
set -a
source "$ROOT_DIR/.env"
set +a

if [[ -z "${LAURA_ALERT_TELEGRAM_BOT_TOKEN:-}" || -z "${LAURA_ALERT_TELEGRAM_CHAT_ID:-}" ]]; then
  echo "Telegram not configured; skipping daily report."
  exit 0
fi

now_iso="$(date -Is)"
host_name="$(hostname)"

shop_json="$("$PY_CMD" -m shopee_agent.cli shop-info-default 2>/tmp/laura_daily_report.err || true)"
shop_code=$?

if [[ $shop_code -eq 0 ]]; then
  shop_name="$(echo "$shop_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("shop_name","unknown"))')"
  shop_status="$(echo "$shop_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("status","unknown"))')"
  shop_region="$(echo "$shop_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("region","unknown"))')"
  api_line="API: OK"
else
  shop_name="unknown"
  shop_status="unknown"
  shop_region="unknown"
  api_line="API: ERROR"
fi

baseline_line="LLM baseline: unavailable"
if [[ -f "$ROOT_DIR/reports/laura_profitability_llm_baseline_latest.json" ]]; then
  baseline_line="$("$PY_CMD" - <<PY
import json
from pathlib import Path

path = Path("$ROOT_DIR/reports/laura_profitability_llm_baseline_latest.json")
try:
    data = json.loads(path.read_text(encoding="utf-8"))
    posture = data.get("posture", "unknown")
    fallback_rate = data.get("fallback_rate_pct", "unknown")
    total_runs = (data.get("counts") or {}).get("total_runs", "unknown")
    print(f"LLM baseline: posture={posture} fallback_rate={fallback_rate}% total_runs={total_runs}")
except Exception as exc:
    print(f"LLM baseline: invalid ({exc})")
PY
)"
fi

last_log_line="no log"
if [[ -f "$LOG_FILE" ]]; then
  last_log_line="$(tail -n 1 "$LOG_FILE" | tr -d '\r')"
fi

message=$(
  cat <<EOF
Laura Daily Report
Time: ${now_iso}
Host: ${host_name}
Shop: ${shop_name}
Status: ${shop_status}
Region: ${shop_region}
${api_line}
${baseline_line}
Last log: ${last_log_line}
EOF
)

curl -sS -X POST \
  "https://api.telegram.org/bot${LAURA_ALERT_TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${LAURA_ALERT_TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=${message}" \
  >/dev/null

echo "Laura daily report sent."
