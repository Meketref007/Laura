#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
NOTIFY_ON_FIX="${LAURA_SECURITY_GUARD_NOTIFY_ON_FIX:-1}"

if ! [[ "$NOTIFY_ON_FIX" =~ ^[01]$ ]]; then
  NOTIFY_ON_FIX=1
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

needs_fix=0
fixed_items=()

fix_if_needed() {
  local file="$1"
  if [[ -e "$file" ]]; then
    perms="$(stat -c %a "$file")"
    # Require owner-only rw (600) for sensitive env artifacts.
    if [[ "$perms" != "600" ]]; then
      chmod 600 "$file"
      fixed_items+=("$file:$perms->600")
      needs_fix=1
    fi
  fi
}

fix_if_needed "$ROOT_DIR/.env"
fix_if_needed "$ROOT_DIR/.env.bak"

for f in "$ROOT_DIR"/.env.pre-restore.*; do
  if [[ -e "$f" ]]; then
    fix_if_needed "$f"
  fi
done

if [[ $needs_fix -eq 1 ]]; then
  echo "Laura security guard fixed permissions:"
  for item in "${fixed_items[@]}"; do
    echo "- $item"
  done

  if [[ "$NOTIFY_ON_FIX" == "1" ]]; then
    msg="Laura security guard corrigiu permissoes de arquivos sensiveis no host $(hostname): ${fixed_items[*]}"
    notify "$msg"
  fi
  exit 0
fi

echo "Laura security guard OK: no permission drift detected."
