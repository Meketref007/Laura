#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
AUTO_HEAL="${LAURA_CRON_GUARD_AUTO_HEAL:-1}"

if ! [[ "$AUTO_HEAL" =~ ^[01]$ ]]; then
  AUTO_HEAL=1
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

if ./scripts/laura_reconcile_cron.sh --check >/tmp/laura_cron_guard.out 2>/tmp/laura_cron_guard.err; then
  echo "Laura cron guard OK: no drift."
  exit 0
fi

err_msg="$(cat /tmp/laura_cron_guard.err 2>/dev/null || true)"
out_msg="$(cat /tmp/laura_cron_guard.out 2>/dev/null || true)"
base_msg="Laura cron guard detectou drift no agendamento."

if [[ "$AUTO_HEAL" == "1" ]]; then
  if ./scripts/laura_reconcile_cron.sh apply >/tmp/laura_cron_guard_heal.out 2>/tmp/laura_cron_guard_heal.err; then
    notify "${base_msg} Auto-heal aplicado com sucesso no host $(hostname)."
    echo "Laura cron guard: drift fixed by auto-heal."
    exit 0
  fi

  heal_err="$(cat /tmp/laura_cron_guard_heal.err 2>/dev/null || true)"
  notify "${base_msg} Falha no auto-heal no host $(hostname). Check manual needed. ${heal_err}"
  echo "ERROR: drift detected and auto-heal failed"
  echo "$err_msg"
  echo "$out_msg"
  echo "$heal_err"
  exit 1
fi

notify "${base_msg} Auto-heal desativado no host $(hostname). Corrija com laura_reconcile_cron.sh apply."
echo "ERROR: drift detected (auto-heal disabled)"
echo "$err_msg"
echo "$out_msg"
exit 1
