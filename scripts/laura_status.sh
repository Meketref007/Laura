#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
LOG_FILE="$ROOT_DIR/logs/laura_healthcheck.log"
MAX_SUCCESS_AGE_MIN="${LAURA_STATUS_MAX_HEALTHCHECK_SUCCESS_AGE_MIN:-240}"
MAX_ERROR_RECENCY_MIN="${LAURA_STATUS_MAX_HEALTHCHECK_ERROR_RECENCY_MIN:-120}"

if ! [[ "$MAX_SUCCESS_AGE_MIN" =~ ^[0-9]+$ ]]; then
  MAX_SUCCESS_AGE_MIN=240
fi
if ! [[ "$MAX_ERROR_RECENCY_MIN" =~ ^[0-9]+$ ]]; then
  MAX_ERROR_RECENCY_MIN=120
fi

cd "$ROOT_DIR"
set -a
source "$ROOT_DIR/.env"
set +a

echo "=== Laura Status ==="
echo "Timestamp: $(date -Is)"
echo "Host: $(hostname)"
echo

echo "[1] Environment"
if [[ -n "${SHOPEE_PARTNER_ID:-}" && -n "${SHOPEE_DEFAULT_SHOP_ID:-}" ]]; then
  echo "OK: partner/shop configurados"
else
  echo "WARN: variaveis essenciais ausentes no .env"
fi

if [[ -n "${LAURA_ALERT_TELEGRAM_BOT_TOKEN:-}" && -n "${LAURA_ALERT_TELEGRAM_CHAT_ID:-}" ]]; then
  echo "OK: alerta Telegram configurado"
else
  echo "WARN: alerta Telegram incompleto"
fi

echo

echo "[2] Scheduler (cron)"
cron_content="$(crontab -l 2>/dev/null || true)"
if grep -Fq "@reboot /home/shopee/agente/scripts/run_laura_healthcheck.sh" <<< "$cron_content"; then
  echo "OK: @reboot configurado"
else
  echo "WARN: @reboot nao encontrado"
fi

if grep -Fq "0 */3 * * * /home/shopee/agente/scripts/run_laura_healthcheck.sh" <<< "$cron_content"; then
  echo "OK: execucao a cada 3 horas configurada"
else
  echo "WARN: agendamento 3h nao encontrado"
fi

echo

echo "[3] Last health-check log"
if [[ -f "$LOG_FILE" ]]; then
  tail -n 10 "$LOG_FILE"

  health_summary="OK"

  last_success_ts="$(awk '/\[INFO\] Laura health-check finished/ {print prev} {prev=$0}' "$LOG_FILE" | tail -n 1 || true)"
  last_error_ts="$(awk '/\[ERROR\] Laura health-check failed/ {print prev} {prev=$0}' "$LOG_FILE" | tail -n 1 || true)"
  last_error_line="$(grep -E "\[ERROR\] Laura health-check failed" "$LOG_FILE" | tail -n 1 || true)"

  if [[ -n "$last_success_ts" ]]; then
    success_age_min="$(python3 - <<PY
from datetime import datetime, timezone
ts = "$last_success_ts".strip()
if not ts:
    print("unknown")
else:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        age = int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
        print(age)
    except Exception:
        print("unknown")
PY
)"
    echo "INFO: ultimo sucesso do health-check em ${last_success_ts} (idade=${success_age_min} min)"
    if [[ "$success_age_min" == "unknown" ]] || (( success_age_min > MAX_SUCCESS_AGE_MIN )); then
      health_summary="WARN"
      echo "WARN: ultimo sucesso acima do limite (${success_age_min} min > ${MAX_SUCCESS_AGE_MIN} min)"
    fi
  else
    echo "WARN: nenhum sucesso de health-check encontrado no log"
    health_summary="WARN"
  fi

  if [[ -n "$last_error_line" ]]; then
    error_age_min="$(python3 - <<PY
from datetime import datetime, timezone
ts = "$last_error_ts".strip()
if not ts:
    print("unknown")
else:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        age = int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
        print(age)
    except Exception:
        print("unknown")
PY
)"
    if [[ -n "$last_error_ts" ]]; then
      echo "INFO: ultimo erro de health-check em ${last_error_ts} (idade=${error_age_min} min): $last_error_line"
    else
      echo "INFO: ultimo erro de health-check: $last_error_line"
    fi

    if [[ "$error_age_min" != "unknown" ]] && (( error_age_min <= MAX_ERROR_RECENCY_MIN )); then
      health_summary="WARN"
      echo "WARN: erro recente de health-check dentro da janela critica (${error_age_min} min <= ${MAX_ERROR_RECENCY_MIN} min)"
    fi
  else
    echo "INFO: nenhum erro de health-check encontrado no log"
  fi

  echo "INFO: health-check summary=${health_summary} (max_success_age=${MAX_SUCCESS_AGE_MIN} min, error_recency_window=${MAX_ERROR_RECENCY_MIN} min)"
else
  echo "WARN: log nao encontrado em $LOG_FILE"
fi

echo

echo "[4] API connectivity (shop-info-default)"
set +e
PY_CMD="${ROOT_DIR}/.venv/bin/python"
if [[ ! -x "$PY_CMD" ]]; then
  PY_CMD="python3"
fi

api_output="$("$PY_CMD" -m shopee_agent.cli shop-info-default 2>&1)"
api_code=$?
set -e

if [[ $api_code -eq 0 ]]; then
  echo "OK: conectividade com Shopee ativa"
  echo "$api_output" | tail -n 12
else
  echo "ERROR: falha ao consultar shop-info-default"
  echo "$api_output"
  exit 1
fi

echo
echo "[5] Self-test digest status"
set +e
digest_status_output="$(./scripts/laura_metrics_audit_self_test_digest_status.sh 2>&1)"
digest_status_code=$?
set -e

if [[ $digest_status_code -eq 0 ]]; then
  echo "$digest_status_output"
else
  echo "WARN: self-test digest status command failed"
  echo "$digest_status_output"
fi

echo
echo "[6] Profitability autopilot"
profit_latest="$ROOT_DIR/reports/laura_profitability_latest.json"
profit_input_latest="$ROOT_DIR/reports/laura_profitability_inputs_latest.json"
profit_input_freshness_limit_min="${LAURA_PROFITABILITY_INPUT_FRESHNESS_MAX_AGE_MINUTES:-180}"
profit_exec_enabled="${LAURA_PROFITABILITY_EXECUTE_ENABLED:-0}"
profit_exec_kill_switch="${LAURA_PROFITABILITY_EXEC_KILL_SWITCH:-1}"
profit_exec_allowed_actions="${LAURA_PROFITABILITY_EXEC_ALLOWED_ACTIONS:-ALL}"
if ! [[ "$profit_input_freshness_limit_min" =~ ^[0-9]+$ ]]; then
  profit_input_freshness_limit_min=180
fi
if ! [[ "$profit_exec_enabled" =~ ^[01]$ ]]; then
  profit_exec_enabled=0
fi
if ! [[ "$profit_exec_kill_switch" =~ ^[01]$ ]]; then
  profit_exec_kill_switch=1
fi

profit_exec_posture="SAFE"
profit_exec_posture_reason="execution disabled"
if [[ "$profit_exec_enabled" == "1" && "$profit_exec_kill_switch" == "0" ]]; then
  if [[ -z "$profit_exec_allowed_actions" || "$profit_exec_allowed_actions" == "ALL" ]]; then
    profit_exec_posture="LIVE"
    profit_exec_posture_reason="execution enabled for all actions"
  else
    profit_exec_posture="CANARY"
    profit_exec_posture_reason="execution enabled with action allowlist"
  fi
elif [[ "$profit_exec_kill_switch" == "1" ]]; then
  profit_exec_posture="SAFE"
  profit_exec_posture_reason="kill switch active"
fi

echo "INFO: profitability rollout config execute_enabled=${profit_exec_enabled} kill_switch=${profit_exec_kill_switch} allowed_actions=${profit_exec_allowed_actions}"
echo "INFO: EXECUTION_POSTURE=${profit_exec_posture} (${profit_exec_posture_reason})"

if [[ -f "$profit_input_latest" ]]; then
  input_age_min="$(python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

path = Path("$profit_input_latest")
try:
  row = json.loads(path.read_text(encoding="utf-8"))
  ts = row.get("timestamp")
  if not ts:
    print("unknown")
  else:
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    age = int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
    print(age)
except Exception:
  print("unknown")
PY
)"
  echo "INFO: profitability input latest age=${input_age_min} min (limit=${profit_input_freshness_limit_min} min)"
  if [[ "$input_age_min" == "unknown" ]] || (( input_age_min > profit_input_freshness_limit_min )); then
    echo "WARN: profitability input stale/invalido"
  fi
else
  echo "WARN: profitability input latest not found ($profit_input_latest)"
fi

if [[ -f "$profit_latest" ]]; then
  python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

path = Path("$profit_latest")
try:
  data = json.loads(path.read_text(encoding="utf-8"))
except Exception as exc:
  print(f"WARN: invalid profitability latest JSON: {exc}")
  raise SystemExit(0)

recorded_at = data.get("recorded_at") or data.get("timestamp")
age_min = "unknown"
if isinstance(recorded_at, str) and recorded_at.strip():
  try:
    dt = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
    age_min = int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
  except Exception:
    pass

execution = data.get("execution") or {}
metrics = data.get("metrics") or {}

print(
  "INFO: action={action} priority={priority} decision={decision} mode={mode} run_status={run_status}".format(
    action=data.get("action_key", "unknown"),
    priority=data.get("priority", "unknown"),
    decision=data.get("decision_status", "unknown"),
    mode=execution.get("mode", "unknown"),
    run_status=execution.get("status", "unknown"),
  )
)
print(
  "INFO: margin_pct={margin} roas={roas} refund_rate_pct={refund} profit={profit} age_min={age}".format(
    margin=metrics.get("margin_pct", "unknown"),
    roas=metrics.get("roas", "unknown"),
    refund=metrics.get("refund_rate_pct", "unknown"),
    profit=metrics.get("profit", "unknown"),
    age=age_min,
  )
)
print(
  "INFO: safety kill_switch={kill} allowed_actions={allowed} max_runs_window_h={window} max_runs_per_action={max_runs} max_consecutive_failures={max_fails} window_successes={window_ok} consecutive_failures={fails}".format(
    kill=execution.get("safety_kill_switch", "unknown"),
    allowed=execution.get("safety_allowed_actions", "unknown"),
    window=execution.get("safety_max_runs_window_hours", "unknown"),
    max_runs=execution.get("safety_max_runs_per_action", "unknown"),
    max_fails=execution.get("safety_max_consecutive_failures", "unknown"),
    window_ok=execution.get("safety_success_runs_window", "unknown"),
    fails=execution.get("safety_consecutive_failures", "unknown"),
  )
)
print("INFO: reason={}".format(data.get("reason", "")))
PY
else
  echo "WARN: profitability latest report not found ($profit_latest)"
fi

profit_input_guard_state="$ROOT_DIR/reports/laura_profitability_input_freshness_guard.state"
if [[ -f "$profit_input_guard_state" ]]; then
  echo "WARN: profitability input freshness guard state ativo ($profit_input_guard_state)"
else
  echo "INFO: profitability input freshness guard state normal"
fi

echo
echo "[7] LLM local status"
llm_latest="$ROOT_DIR/reports/laura_profitability_llm_latest.json"
if [[ -f "$llm_latest" ]]; then
  python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

path = Path("$llm_latest")
try:
  row = json.loads(path.read_text(encoding="utf-8"))
except Exception as exc:
  print(f"WARN: invalid LLM latest JSON: {exc}")
  raise SystemExit(0)

model = str(row.get("model", "unknown"))
fallback = "(fallback)" in model
ts = str(row.get("timestamp", "")).strip()
age_min = "unknown"
if ts:
  try:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    age_min = int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
  except Exception:
    pass

print(
  "INFO: llm_latest model={model} fallback={fallback} age_min={age}".format(
    model=model,
    fallback=fallback,
    age=age_min,
  )
)
print(
  "INFO: llm_latest action={action} priority={priority} confidence={confidence}".format(
    action=row.get("action", "unknown"),
    priority=row.get("priority", "unknown"),
    confidence=row.get("confidence", "unknown"),
  )
)
if fallback:
  print("WARN: LLM fallback detectado no ultimo resultado")
PY
else
  echo "WARN: LLM latest report not found ($llm_latest)"
fi

echo
echo "[8] LLM baseline audit (24h)"
llm_baseline_latest="$ROOT_DIR/reports/laura_profitability_llm_baseline_latest.json"
set +e
baseline_output="$(./scripts/laura_llm_baseline_audit.sh --window-hours 24 2>&1)"
baseline_code=$?
set -e

if [[ $baseline_code -ne 0 ]]; then
  echo "WARN: baseline audit falhou"
  echo "$baseline_output"
elif [[ ! -f "$llm_baseline_latest" ]]; then
  echo "WARN: baseline latest nao encontrado ($llm_baseline_latest)"
else
  python3 - <<PY
import json
from pathlib import Path

path = Path("$llm_baseline_latest")
try:
  row = json.loads(path.read_text(encoding="utf-8"))
except Exception as exc:
  print(f"WARN: invalid baseline JSON: {exc}")
  raise SystemExit(0)

counts = row.get("counts") or {}
lat = ((row.get("latency_ms") or {}).get("all") or {})
print(
  "INFO: llm_baseline posture={posture} window_h={window} fallback_rate_pct={rate}".format(
    posture=row.get("posture", "unknown"),
    window=row.get("window_hours", "unknown"),
    rate=row.get("fallback_rate_pct", "unknown"),
  )
)
print(
  "INFO: llm_baseline runs total={total} fallback={fallback} native={native} p95_ms={p95} avg_ms={avg}".format(
    total=counts.get("total_runs", "unknown"),
    fallback=counts.get("fallback_runs", "unknown"),
    native=counts.get("native_runs", "unknown"),
    p95=lat.get("p95_ms", "unknown"),
    avg=lat.get("avg_ms", "unknown"),
  )
)
if str(row.get("posture", "")).upper() in {"CRITICAL", "ATTENTION"}:
  print("WARN: baseline indica alta taxa de fallback da LLM")
PY

  llm_baseline_alert_state="$ROOT_DIR/reports/laura_profitability_llm_baseline_alert.state"
  if [[ -f "$llm_baseline_alert_state" ]]; then
    echo "INFO: llm_baseline_alert_state raw=$(cat "$llm_baseline_alert_state" 2>/dev/null || true)"
  else
    echo "INFO: llm_baseline_alert_state ausente (sem historico de guard ainda)"
  fi
fi

echo
echo "[9] Webhook doctor"
set +e
webhook_doctor_output="$(./scripts/laura_webhook_doctor.sh 2>&1)"
webhook_doctor_code=$?
set -e

if [[ $webhook_doctor_code -eq 0 ]]; then
  echo "$webhook_doctor_output"
else
  echo "WARN: webhook doctor reportou atencao"
  echo "$webhook_doctor_output"
fi

echo
echo "Laura status check finished."
