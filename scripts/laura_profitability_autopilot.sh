#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
INPUT_FILE="$REPORTS_DIR/laura_profitability_inputs_latest.json"
LATEST_FILE="$REPORTS_DIR/laura_profitability_latest.json"
HISTORY_FILE="$REPORTS_DIR/laura_profitability_history.jsonl"
AUDIT_FILE="$REPORTS_DIR/laura_profitability_actions_audit.jsonl"
STATE_FILE="$REPORTS_DIR/laura_profitability_state.json"
DEFAULT_ACTION_DISPATCHER="$ROOT_DIR/scripts/laura_profitability_action_dispatch.sh"

source "$ROOT_DIR/scripts/telegram_narrator.sh"

cd "$ROOT_DIR"
mkdir -p "$REPORTS_DIR"

set -a
source "$ROOT_DIR/.env"
set +a

ENABLED="${LAURA_PROFITABILITY_ENABLED:-1}"
EXECUTE_ENABLED="${LAURA_PROFITABILITY_EXECUTE_ENABLED:-0}"
COOLDOWN_MINUTES="${LAURA_PROFITABILITY_COOLDOWN_MINUTES:-120}"
INPUT_MAX_AGE_MINUTES="${LAURA_PROFITABILITY_INPUT_MAX_AGE_MINUTES:-180}"
MIN_MARGIN_PCT="${LAURA_PROFITABILITY_MIN_MARGIN_PCT:-12}"
MAX_REFUND_RATE_PCT="${LAURA_PROFITABILITY_MAX_REFUND_RATE_PCT:-6}"
MIN_ROAS="${LAURA_PROFITABILITY_MIN_ROAS:-3}"
MIN_ORDERS_FOR_SCALE="${LAURA_PROFITABILITY_MIN_ORDERS_FOR_SCALE:-20}"
EXEC_MAX_RUNS_WINDOW_HOURS="${LAURA_PROFITABILITY_EXEC_MAX_RUNS_WINDOW_HOURS:-24}"
EXEC_MAX_RUNS_PER_ACTION="${LAURA_PROFITABILITY_EXEC_MAX_RUNS_PER_ACTION:-4}"
EXEC_MAX_CONSECUTIVE_FAILURES="${LAURA_PROFITABILITY_EXEC_MAX_CONSECUTIVE_FAILURES:-3}"
EXEC_KILL_SWITCH="${LAURA_PROFITABILITY_EXEC_KILL_SWITCH:-1}"
EXEC_ALLOWED_ACTIONS="${LAURA_PROFITABILITY_EXEC_ALLOWED_ACTIONS:-}"

if ! [[ "$ENABLED" =~ ^[01]$ ]]; then
  ENABLED=1
fi
if ! [[ "$EXECUTE_ENABLED" =~ ^[01]$ ]]; then
  EXECUTE_ENABLED=0
fi
if ! [[ "$COOLDOWN_MINUTES" =~ ^[0-9]+$ ]]; then
  COOLDOWN_MINUTES=120
fi
if ! [[ "$INPUT_MAX_AGE_MINUTES" =~ ^[0-9]+$ ]]; then
  INPUT_MAX_AGE_MINUTES=180
fi
if ! [[ "$MIN_ORDERS_FOR_SCALE" =~ ^[0-9]+$ ]]; then
  MIN_ORDERS_FOR_SCALE=20
fi
if ! [[ "$EXEC_MAX_RUNS_WINDOW_HOURS" =~ ^[0-9]+$ ]]; then
  EXEC_MAX_RUNS_WINDOW_HOURS=24
fi
if ! [[ "$EXEC_MAX_RUNS_PER_ACTION" =~ ^[0-9]+$ ]]; then
  EXEC_MAX_RUNS_PER_ACTION=4
fi
if ! [[ "$EXEC_MAX_CONSECUTIVE_FAILURES" =~ ^[0-9]+$ ]]; then
  EXEC_MAX_CONSECUTIVE_FAILURES=3
fi
if ! [[ "$EXEC_KILL_SWITCH" =~ ^[01]$ ]]; then
  EXEC_KILL_SWITCH=1
fi

if [[ "$ENABLED" == "0" ]]; then
  tg_narrar alerta "Autopilot desativado" "LAURA_PROFITABILITY_ENABLED=0"
  echo "Laura profitability autopilot disabled by LAURA_PROFITABILITY_ENABLED=0"
  exit 0
fi

decision_json="$(python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

input_path = Path("$INPUT_FILE")
max_age_minutes = int("$INPUT_MAX_AGE_MINUTES")
min_margin = float("$MIN_MARGIN_PCT")
max_refund_rate = float("$MAX_REFUND_RATE_PCT")
min_roas = float("$MIN_ROAS")
min_orders_for_scale = int("$MIN_ORDERS_FOR_SCALE")

now = datetime.now(timezone.utc)
out = {
  "timestamp": now.isoformat(),
  "decision_status": "ok",
  "action_key": "monitor_only",
  "priority": "LOW",
  "reason": "No profitability breach detected.",
  "should_execute": False,
  "input_age_minutes": None,
  "metrics": {
    "revenue": 0.0,
    "cogs": 0.0,
    "ad_spend": 0.0,
    "shipping_subsidy": 0.0,
    "refunds": 0.0,
    "orders": 0,
    "profit": 0.0,
    "margin_pct": 0.0,
    "roas": None,
    "refund_rate_pct": 0.0,
  },
}

if not input_path.exists():
  out["decision_status"] = "missing_input"
  out["action_key"] = "collect_fresh_data"
  out["priority"] = "HIGH"
  out["reason"] = "Profitability input file not found."
  print(json.dumps(out, ensure_ascii=True))
  raise SystemExit(0)

try:
  raw = json.loads(input_path.read_text(encoding="utf-8"))
except Exception as exc:
  out["decision_status"] = "invalid_input"
  out["action_key"] = "collect_fresh_data"
  out["priority"] = "HIGH"
  out["reason"] = f"Invalid profitability input JSON: {exc}"
  print(json.dumps(out, ensure_ascii=True))
  raise SystemExit(0)

raw_ts = raw.get("timestamp")
input_dt = None
if isinstance(raw_ts, str) and raw_ts.strip():
  try:
    input_dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
  except Exception:
    input_dt = None

if input_dt is None:
  try:
    input_dt = datetime.fromtimestamp(input_path.stat().st_mtime, tz=timezone.utc)
  except Exception:
    input_dt = now

age_min = int((now - input_dt).total_seconds() // 60)
out["input_age_minutes"] = age_min
if age_min > max_age_minutes:
  out["decision_status"] = "stale_input"
  out["action_key"] = "collect_fresh_data"
  out["priority"] = "HIGH"
  out["reason"] = f"Profitability input stale ({age_min} min > {max_age_minutes} min)."
  print(json.dumps(out, ensure_ascii=True))
  raise SystemExit(0)

def num(name, default=0.0):
  v = raw.get(name, default)
  try:
    return float(v)
  except Exception:
    return float(default)

def int_num(name, default=0):
  v = raw.get(name, default)
  try:
    return int(v)
  except Exception:
    return int(default)

revenue = num("revenue")
cogs = num("cogs")
ad_spend = num("ad_spend")
shipping_subsidy = num("shipping_subsidy")
refunds = num("refunds")
orders = int_num("orders")

profit = revenue - cogs - ad_spend - shipping_subsidy - refunds
margin_pct = 0.0 if revenue <= 0 else (profit / revenue) * 100.0
roas = None if ad_spend <= 0 else (revenue / ad_spend)
refund_rate_pct = 0.0 if revenue <= 0 else (refunds / revenue) * 100.0

out["metrics"] = {
  "revenue": round(revenue, 2),
  "cogs": round(cogs, 2),
  "ad_spend": round(ad_spend, 2),
  "shipping_subsidy": round(shipping_subsidy, 2),
  "refunds": round(refunds, 2),
  "orders": orders,
  "profit": round(profit, 2),
  "margin_pct": round(margin_pct, 2),
  "roas": None if roas is None else round(roas, 2),
  "refund_rate_pct": round(refund_rate_pct, 2),
}

if revenue <= 0:
  out["action_key"] = "monitor_only"
  out["priority"] = "LOW"
  out["reason"] = "Revenue is zero; monitor before taking profitability actions."
elif margin_pct < min_margin:
  out["action_key"] = "protect_margin"
  out["priority"] = "CRITICAL"
  out["reason"] = f"Margin below threshold ({margin_pct:.2f}% < {min_margin:.2f}%)."
  out["should_execute"] = True
elif refund_rate_pct > max_refund_rate:
  out["action_key"] = "refund_guard"
  out["priority"] = "HIGH"
  out["reason"] = f"Refund rate above threshold ({refund_rate_pct:.2f}% > {max_refund_rate:.2f}%)."
  out["should_execute"] = True
elif roas is not None and roas < min_roas:
  out["action_key"] = "pause_low_roas_ads"
  out["priority"] = "HIGH"
  out["reason"] = f"ROAS below threshold ({roas:.2f} < {min_roas:.2f})."
  out["should_execute"] = True
elif orders >= min_orders_for_scale and margin_pct >= min_margin and (roas is None or roas >= min_roas):
  out["action_key"] = "scale_winners"
  out["priority"] = "MEDIUM"
  out["reason"] = "Healthy profitability and order volume; scale best-performing products."
  out["should_execute"] = True

print(json.dumps(out, ensure_ascii=True))
PY
)"

action_key="$(python3 - <<PY
import json
print(json.loads('''$decision_json''').get("action_key", "monitor_only"))
PY
)"
priority="$(python3 - <<PY
import json
print(json.loads('''$decision_json''').get("priority", "LOW"))
PY
)"
reason="$(python3 - <<PY
import json
print(json.loads('''$decision_json''').get("reason", ""))
PY
)"
decision_status="$(python3 - <<PY
import json
print(json.loads('''$decision_json''').get("decision_status", "ok"))
PY
)"
should_execute="$(python3 - <<PY
import json
print(1 if json.loads('''$decision_json''').get("should_execute") else 0)
PY
)"

# Extract metrics from decision_json
revenue="$(python3 - <<PY
import json
print(json.loads('''$decision_json''').get("metrics", {}).get("revenue", 0))
PY
)"
margin_pct="$(python3 - <<PY
import json
print(json.loads('''$decision_json''').get("metrics", {}).get("margin_pct", 0))
PY
)"
orders="$(python3 - <<PY
import json
print(json.loads('''$decision_json''').get("metrics", {}).get("orders", 0))
PY
)"
cogs="$(python3 - <<PY
import json
print(json.loads('''$decision_json''').get("metrics", {}).get("cogs", 0))
PY
)"
roas="$(python3 - <<PY
import json
roas_val = json.loads('''$decision_json''').get("metrics", {}).get("roas")
print(roas_val if roas_val is not None else "N/A")
PY
)"
refund_rate_pct="$(python3 - <<PY
import json
print(json.loads('''$decision_json''').get("metrics", {}).get("refund_rate_pct", 0))
PY
)"

# Only send a consolidated summary at the end. Intermediate narration removed to avoid spam.

cooldown_seconds=$((COOLDOWN_MINUTES * 60))
now_epoch="$(date +%s)"
last_action_epoch="$(python3 - <<PY
import json
from pathlib import Path

path = Path("$STATE_FILE")
action = "$action_key"
if not path.exists():
  print(0)
else:
  try:
    state = json.loads(path.read_text(encoding="utf-8"))
    print(int(state.get("last_action_epoch", {}).get(action, 0)))
  except Exception:
    print(0)
PY
)"
if ! [[ "$last_action_epoch" =~ ^[0-9]+$ ]]; then
  last_action_epoch=0
fi

run_mode="observe"
run_status="not_applicable"
run_command=""
safety_success_runs_window=0
safety_consecutive_failures=0

if [[ "$decision_status" != "ok" ]]; then
  run_mode="observe"
  run_status="$decision_status"
elif [[ "$should_execute" == "0" ]]; then
  run_mode="observe"
  run_status="no_action_needed"
else
  case "$action_key" in
    protect_margin)
      run_command="${LAURA_PROFITABILITY_ACTION_PROTECT_MARGIN_CMD:-$DEFAULT_ACTION_DISPATCHER --action protect_margin}"
      ;;
    refund_guard)
      run_command="${LAURA_PROFITABILITY_ACTION_REFUND_GUARD_CMD:-$DEFAULT_ACTION_DISPATCHER --action refund_guard}"
      ;;
    pause_low_roas_ads)
      run_command="${LAURA_PROFITABILITY_ACTION_PAUSE_LOW_ROAS_ADS_CMD:-$DEFAULT_ACTION_DISPATCHER --action pause_low_roas_ads}"
      ;;
    scale_winners)
      run_command="${LAURA_PROFITABILITY_ACTION_SCALE_WINNERS_CMD:-$DEFAULT_ACTION_DISPATCHER --action scale_winners}"
      ;;
    *)
      run_command=""
      ;;
  esac

  if (( now_epoch - last_action_epoch < cooldown_seconds )); then
    run_mode="cooldown"
    run_status="cooldown_active"
  elif [[ -z "$run_command" ]]; then
    run_mode="plan_only"
    run_status="missing_action_command"
  elif [[ "$EXECUTE_ENABLED" == "0" ]]; then
    run_mode="dry_run"
    tg_narrar alerta "⚠️ Modo *dry_run* — ação *${action_key}* sugerida mas não executada" \
      "Para ativar: LAURA_PROFITABILITY_EXECUTE_ENABLED=1"
    if [[ "$run_command" == "$DEFAULT_ACTION_DISPATCHER"* ]]; then
      if bash -lc "$run_command" >/tmp/laura_profitability_action.out 2>/tmp/laura_profitability_action.err; then
        run_status="execution_disabled_plan_generated"
      else
        run_status="execution_disabled_plan_failed"
      fi
    else
      run_status="execution_disabled"
    fi
  else
    if [[ "$EXEC_KILL_SWITCH" == "1" ]]; then
      run_mode="safety_lock"
      run_status="kill_switch_active"
    else
      allowed_action=0
      if [[ -z "$EXEC_ALLOWED_ACTIONS" ]]; then
        allowed_action=1
      else
        IFS=',' read -r -a allowed_list <<< "$EXEC_ALLOWED_ACTIONS"
        for allowed in "${allowed_list[@]}"; do
          allowed_trimmed="$(echo "$allowed" | xargs)"
          if [[ "$allowed_trimmed" == "$action_key" ]]; then
            allowed_action=1
            break
          fi
        done
      fi

      if [[ "$allowed_action" != "1" ]]; then
        run_mode="safety_lock"
        run_status="action_not_allowed"
      else
        safety_json="$(python3 - <<PY
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

audit_file = Path("$AUDIT_FILE")
action = "$action_key"
window_h = int("$EXEC_MAX_RUNS_WINDOW_HOURS")
max_runs = int("$EXEC_MAX_RUNS_PER_ACTION")
max_fails = int("$EXEC_MAX_CONSECUTIVE_FAILURES")

now = datetime.now(timezone.utc)
cutoff = now - timedelta(hours=window_h)

rows = []
if audit_file.exists():
  for raw in audit_file.read_text(encoding="utf-8").splitlines():
    s = raw.strip()
    if not s:
      continue
    try:
      r = json.loads(s)
    except Exception:
      continue
    ts = r.get("timestamp")
    if not ts:
      continue
    try:
      dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
      continue
    r["_dt"] = dt
    rows.append(r)

rows.sort(key=lambda x: x.get("_dt"))
same_action = [r for r in rows if r.get("action_key") == action]

success_runs_window = sum(
  1
  for r in same_action
  if r.get("run_mode") == "execute"
  and r.get("run_status") == "success"
  and r.get("_dt") >= cutoff
)

consecutive_failures = 0
for r in reversed(same_action):
  if r.get("run_mode") != "execute":
    continue
  if r.get("run_status") == "failed":
    consecutive_failures += 1
  else:
    break

allow = True
reason = "allow"
if max_runs > 0 and success_runs_window >= max_runs:
  allow = False
  reason = "max_runs_reached"
elif max_fails > 0 and consecutive_failures >= max_fails:
  allow = False
  reason = "circuit_breaker_open"

print(json.dumps({
  "allow": allow,
  "reason": reason,
  "success_runs_window": success_runs_window,
  "consecutive_failures": consecutive_failures,
}, ensure_ascii=True))
PY
)"

        safety_allow="$(python3 - <<PY
import json
print(1 if json.loads('''$safety_json''').get("allow") else 0)
PY
)"
        safety_reason="$(python3 - <<PY
import json
print(json.loads('''$safety_json''').get("reason", "unknown"))
PY
)"
        safety_success_runs_window="$(python3 - <<PY
import json
print(int(json.loads('''$safety_json''').get("success_runs_window", 0)))
PY
)"
        safety_consecutive_failures="$(python3 - <<PY
import json
print(int(json.loads('''$safety_json''').get("consecutive_failures", 0)))
PY
)"

        if [[ "$safety_allow" == "1" ]]; then
          run_mode="execute"
          tg_narrar fazendo "Executando *${action_key}*..." "${reason}"
          if bash -lc "$run_command" >/tmp/laura_profitability_action.out 2>/tmp/laura_profitability_action.err; then
            run_status="success"
          else
            run_status="failed"
          fi
        else
          run_mode="safety_lock"
          run_status="$safety_reason"
        fi
      fi
    fi
  fi
fi

allowed_actions_sanitized=""
if [[ -n "$EXEC_ALLOWED_ACTIONS" ]]; then
  IFS=',' read -r -a allowed_list_view <<< "$EXEC_ALLOWED_ACTIONS"
  for allowed in "${allowed_list_view[@]}"; do
    allowed_trimmed="$(echo "$allowed" | xargs)"
    if [[ -n "$allowed_trimmed" ]]; then
      if [[ -n "$allowed_actions_sanitized" ]]; then
        allowed_actions_sanitized+=","
      fi
      allowed_actions_sanitized+="$allowed_trimmed"
    fi
  done
fi

if [[ -z "$allowed_actions_sanitized" ]]; then
  allowed_actions_sanitized="ALL"
fi

final_json="$(python3 - <<PY
import json
from datetime import datetime, timezone

base = json.loads('''$decision_json''')
base["host"] = "$(hostname)"
base["execution"] = {
  "mode": "$run_mode",
  "status": "$run_status",
  "command": "$run_command",
  "execute_enabled": bool(int("$EXECUTE_ENABLED")),
  "cooldown_minutes": int("$COOLDOWN_MINUTES"),
  "safety_max_runs_window_hours": int("$EXEC_MAX_RUNS_WINDOW_HOURS"),
  "safety_max_runs_per_action": int("$EXEC_MAX_RUNS_PER_ACTION"),
  "safety_max_consecutive_failures": int("$EXEC_MAX_CONSECUTIVE_FAILURES"),
  "safety_success_runs_window": int("$safety_success_runs_window"),
  "safety_consecutive_failures": int("$safety_consecutive_failures"),
  "safety_kill_switch": bool(int("$EXEC_KILL_SWITCH")),
  "safety_allowed_actions": "$allowed_actions_sanitized",
}
base["recorded_at"] = datetime.now(timezone.utc).isoformat()
print(json.dumps(base, ensure_ascii=True))
PY
)"

python3 - <<PY
import json
from pathlib import Path

latest = Path("$LATEST_FILE")
history = Path("$HISTORY_FILE")
audit = Path("$AUDIT_FILE")
state_file = Path("$STATE_FILE")
row = json.loads('''$final_json''')

latest.write_text(json.dumps(row, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
with history.open("a", encoding="utf-8") as f:
  f.write(json.dumps(row, ensure_ascii=True) + "\n")

audit_row = {
  "timestamp": row.get("recorded_at"),
  "action_key": row.get("action_key"),
  "priority": row.get("priority"),
  "decision_status": row.get("decision_status"),
  "run_mode": row.get("execution", {}).get("mode"),
  "run_status": row.get("execution", {}).get("status"),
}
with audit.open("a", encoding="utf-8") as f:
  f.write(json.dumps(audit_row, ensure_ascii=True) + "\n")

try:
  state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
except Exception:
  state = {}

last_action_epoch = state.get("last_action_epoch", {})
if not isinstance(last_action_epoch, dict):
  last_action_epoch = {}

if row.get("execution", {}).get("mode") == "execute" and row.get("execution", {}).get("status") == "success":
  import time
  last_action_epoch[row.get("action_key", "unknown")] = int(time.time())

state["last_action_epoch"] = last_action_epoch
state["last_recorded_at"] = row.get("recorded_at")
state_file.write_text(json.dumps(state, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
PY

echo "Laura profitability autopilot finished: action=${action_key} priority=${priority} mode=${run_mode} status=${run_status}"
echo "Reason: ${reason}"
echo "Latest report: $LATEST_FILE"

# Decide whether to notify: only if revenue>0 or action is not monitor_only
should_notify=0
rv=$(python3 - <<PY
try:
    v=float('${revenue}')
    print(1 if v>0 else 0)
except Exception:
    print(0)
PY
)
if [[ "$rv" == "1" ]]; then
  should_notify=1
fi
if [[ "${action_key}" != "monitor_only" ]]; then
  should_notify=1
fi

if [[ "$should_notify" == "1" ]]; then
  tg_enviar_resumo_autopilot "${action_key}" "${reason}" "${revenue}" "${margin_pct}" "${orders}" "${roas}"
fi