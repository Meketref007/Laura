#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
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

timestamp="$(date -Is)"
host_name="$(hostname)"

declare -a results
all_ok=1

run_step() {
  local label="$1"
  shift

  if "$@" >/tmp/laura_dr_monthly.out 2>/tmp/laura_dr_monthly.err; then
    results+=("OK | ${label}")
  else
    results+=("ERROR | ${label}")
    all_ok=0
  fi
}

run_step "Backup" ./scripts/laura_backup.sh
run_step "Verify backup" ./scripts/laura_verify_backup.sh
run_step "Restore drill" ./scripts/laura_restore_drill.sh
run_step "Self-test" ./scripts/laura_self_test.sh

summary="Laura DR Monthly\nTime: ${timestamp}\nHost: ${host_name}\n"
for line in "${results[@]}"; do
  summary+="${line}\n"
done

if [[ $all_ok -eq 1 ]]; then
  summary+="Result: ALL OK"
  printf "%b\n" "$summary"
  notify "$summary"
  exit 0
fi

summary+="Result: ERRORS FOUND"
printf "%b\n" "$summary"
notify "$summary"
exit 1
