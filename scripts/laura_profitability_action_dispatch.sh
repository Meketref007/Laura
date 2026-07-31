#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
LATEST_DECISION_FILE="$REPORTS_DIR/laura_profitability_latest.json"
LATEST_RECOMMENDATION_FILE="$REPORTS_DIR/laura_profitability_action_recommendation_latest.json"
RECOMMENDATION_HISTORY_FILE="$REPORTS_DIR/laura_profitability_action_recommendation_history.jsonl"
NOTIFY_TELEGRAM="${LAURA_PROFITABILITY_ACTION_NOTIFY_TELEGRAM:-1}"

usage() {
  cat <<'USAGE'
Usage:
  laura_profitability_action_dispatch.sh --action <protect_margin|refund_guard|pause_low_roas_ads|scale_winners>
USAGE
}

# If called with --execute perform the action (requires LAURA_PROFITABILITY_EXECUTE_ENABLED=1 or explicit --force)
EXECUTE_MODE=0
FORCE_EXEC=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute)
      EXECUTE_MODE=1
      shift 1
      ;;
    --force)
      FORCE_EXEC=1
      shift 1
      ;;
    *)
      break
      ;;
  esac
done

ACTION_KEY=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --action)
      ACTION_KEY="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$ACTION_KEY" ]]; then
  echo "Missing --action" >&2
  usage
  exit 2
fi

case "$ACTION_KEY" in
  protect_margin|refund_guard|pause_low_roas_ads|scale_winners)
    ;;
  *)
    echo "Unsupported action: $ACTION_KEY" >&2
    exit 2
    ;;
esac

if ! [[ "$NOTIFY_TELEGRAM" =~ ^[01]$ ]]; then
  NOTIFY_TELEGRAM=1
fi

mkdir -p "$REPORTS_DIR"
cd "$ROOT_DIR"
set -a
source "$ROOT_DIR/.env"
set +a

recommendation_json="$(python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

action = "$ACTION_KEY"
latest_file = Path("$LATEST_DECISION_FILE")
now = datetime.now(timezone.utc)

decision = {}
if latest_file.exists():
  try:
    decision = json.loads(latest_file.read_text(encoding="utf-8"))
  except Exception:
    decision = {}

metrics = decision.get("metrics") if isinstance(decision, dict) else {}
if not isinstance(metrics, dict):
  metrics = {}

playbook = {
  "protect_margin": {
    "title": "Protect Margin",
    "next_step": "Reprice SKUs with lowest contribution margin and pause deep-discount bundles.",
    "risk": "Temporary conversion drop if repricing is aggressive.",
  },
  "refund_guard": {
    "title": "Refund Guard",
    "next_step": "Inspect top refund SKUs and tighten listing clarity plus shipping handling checks.",
    "risk": "Reduced catalog exposure if low-quality SKUs are paused quickly.",
  },
  "pause_low_roas_ads": {
    "title": "Pause Low ROAS Ads",
    "next_step": "Pause ad groups below ROAS floor and reallocate budget to best-converting sets.",
    "risk": "Traffic dip while campaigns rebalance.",
  },
  "scale_winners": {
    "title": "Scale Winners",
    "next_step": "Increase budget/inventory for top products while monitoring margin guardrails.",
    "risk": "Higher spend can compress margin if CAC rises.",
  },
}

item = playbook[action]
out = {
  "timestamp": now.isoformat(),
  "action_key": action,
  "title": item["title"],
  "next_step": item["next_step"],
  "risk": item["risk"],
  "decision_reason": decision.get("reason", "N/A"),
  "decision_priority": decision.get("priority", "N/A"),
  "decision_status": decision.get("decision_status", "N/A"),
  "metrics": {
    "revenue": metrics.get("revenue"),
    "profit": metrics.get("profit"),
    "margin_pct": metrics.get("margin_pct"),
    "roas": metrics.get("roas"),
    "refund_rate_pct": metrics.get("refund_rate_pct"),
    "orders": metrics.get("orders"),
  },
  "mode": "safe_recommendation_only",
}

print(json.dumps(out, ensure_ascii=True))
PY
)"

python3 - <<PY
import json
from pathlib import Path

latest = Path("$LATEST_RECOMMENDATION_FILE")
history = Path("$RECOMMENDATION_HISTORY_FILE")
row = json.loads('''$recommendation_json''')

latest.write_text(json.dumps(row, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
with history.open("a", encoding="utf-8") as f:
  f.write(json.dumps(row, ensure_ascii=True) + "\n")
PY

# Create a remediation case to allow approval via Telegram
case_id="$(python3 - <<PY
import json, uuid, time
row = json.loads('''$recommendation_json''')
cid = f"{row.get('action_key','action')}-{int(time.time())}"
row_case = {
  'case_id': cid,
  'action_key': row.get('action_key'),
  'title': row.get('title'),
  'payload': row.get('targets', []),
  'created_at': row.get('timestamp'),
  'executed': False,
  'execute_on_approve': True,
}
print(json.dumps(row_case, ensure_ascii=True))
PY
)"

python3 - <<PY
import json
from pathlib import Path
case = json.loads('''$case_id''')
cases = Path("$ROOT_DIR/reports/laura_remediation_cases.jsonl")
cases.parent.mkdir(parents=True, exist_ok=True)
with cases.open('a', encoding='utf-8') as fh:
  fh.write(json.dumps(case, ensure_ascii=True) + "\n")
PY

if [[ "$NOTIFY_TELEGRAM" == "1" && -n "${LAURA_ALERT_TELEGRAM_BOT_TOKEN:-}" && -n "${LAURA_ALERT_TELEGRAM_CHAT_ID:-}" ]]; then
  message="$(python3 - <<PY
import json
s = json.loads('''$recommendation_json''')
m = s.get("metrics") or {}
print(
  "Laura Profitability Action Dispatcher\n"
  f"Action: {s.get('action_key')}\n"
  f"Title: {s.get('title')}\n"
  f"Reason: {s.get('decision_reason')}\n"
  f"Next Step: {s.get('next_step')}\n"
  f"Risk: {s.get('risk')}\n"
  f"Profit: {m.get('profit')} | Margin: {m.get('margin_pct')} | ROAS: {m.get('roas')} | Refund Rate: {m.get('refund_rate_pct')}"
)
PY
)"

  keyboard="$(python3 - <<PY
import json
case = json.loads('''$case_id''')
print(json.dumps({
  'inline_keyboard': [[
    {'text': 'Aprovar', 'callback_data': f"approve:{case['case_id']}"},
    {'text': 'Cancelar', 'callback_data': f"cancel:{case['case_id']}"},
  ]]
}, ensure_ascii=True))
PY
)"

  curl -sS -X POST \
    "https://api.telegram.org/bot${LAURA_ALERT_TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${LAURA_ALERT_TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${message}" \
    --data-urlencode "reply_markup=${keyboard}" \
    >/dev/null || true
fi

echo "Laura profitability action dispatcher OK: action=${ACTION_KEY} latest=${LATEST_RECOMMENDATION_FILE}"

# If requested, perform the action (requires LAURA_PROFITABILITY_EXECUTE_ENABLED=1 or --force)
if [[ "$EXECUTE_MODE" -eq 1 ]]; then
  if [[ "${LAURA_PROFITABILITY_EXECUTE_ENABLED:-0}" != "1" && "$FORCE_EXEC" -ne 1 ]]; then
  echo "Execution blocked: set LAURA_PROFITABILITY_EXECUTE_ENABLED=1 or use --force" >&2
  exit 0
  fi

  # Pass ACTION_KEY via env so Python can read it
  export ACTION_KEY="$ACTION_KEY"

  REPORTS_ARG="--reports-dir=$ROOT_DIR/reports"
  DRY_FLAG=""
  if [[ "${LAURA_PROFITABILITY_DRY_RUN:-0}" == "1" ]]; then
    DRY_FLAG="--dry-run"
  fi

  PY_CMD="${ROOT_DIR}/.venv/bin/python"
  if [[ ! -x "$PY_CMD" ]]; then
    PY_CMD="python3"
  fi

  "$PY_CMD" -m shopee_agent.autopilot_actions --action "$ACTION_KEY" $REPORTS_ARG $DRY_FLAG
fi