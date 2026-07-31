#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
cd "$ROOT_DIR"

PY_CMD="$ROOT_DIR/.venv/bin/python"
if [[ ! -x "$PY_CMD" ]]; then
  PY_CMD="python3"
fi

set -a
source "$ROOT_DIR/.env"
set +a

timestamp="$(date -Is)"
host_name="$(hostname)"

declare -a results
all_ok=1

run_check() {
  local label="$1"
  shift

  if "$@" >/tmp/laura_self_test.out 2>/tmp/laura_self_test.err; then
    results+=("OK | ${label}")
  else
    results+=("ERROR | ${label}")
    all_ok=0
  fi
}

run_check "CLI shop-info-default" "$PY_CMD" -m shopee_agent.cli shop-info-default
run_check "Scheduled health-check script" "$ROOT_DIR/scripts/run_laura_healthcheck.sh"
run_check "Watchdog script" "$ROOT_DIR/scripts/laura_watchdog.sh"
run_check "Telegram channel test" "$ROOT_DIR/scripts/test_laura_telegram_alert.sh"
run_check "Self-test digest status" "$ROOT_DIR/scripts/laura_metrics_audit_self_test_digest_status.sh"

summary="Laura Self-Test\nTime: ${timestamp}\nHost: ${host_name}\n"
for line in "${results[@]}"; do
  summary+="${line}\n"
done

if [[ -n "${LAURA_ALERT_TELEGRAM_BOT_TOKEN:-}" && -n "${LAURA_ALERT_TELEGRAM_CHAT_ID:-}" ]]; then
  curl -sS -X POST \
    "https://api.telegram.org/bot${LAURA_ALERT_TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${LAURA_ALERT_TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${summary}" \
    >/dev/null || true
fi

printf "%b" "$summary"

if [[ $all_ok -eq 1 ]]; then
  echo "Self-test finished: ALL OK"
  exit 0
fi

echo "Self-test finished: ERRORS FOUND"
exit 1
