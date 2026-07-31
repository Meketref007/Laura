#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
BACKUP_DIR="$ROOT_DIR/backups"
MAX_BACKUP_AGE_HOURS="${LAURA_RESTORE_DRILL_MAX_AGE_HOURS:-72}"

if ! [[ "$MAX_BACKUP_AGE_HOURS" =~ ^[0-9]+$ ]]; then
  MAX_BACKUP_AGE_HOURS=72
fi

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

latest_backup="$(ls -1t "$BACKUP_DIR"/laura_backup_*.tar.gz 2>/dev/null | head -n 1 || true)"
if [[ -z "$latest_backup" ]]; then
  notify "Laura restore drill: nenhum backup encontrado para teste."
  echo "ERROR: no backup found for restore drill" >&2
  exit 1
fi

now_ts=$(date +%s)
file_ts=$(stat -c %Y "$latest_backup")
age_hours=$(( (now_ts - file_ts) / 3600 ))
if (( age_hours > MAX_BACKUP_AGE_HOURS )); then
  notify "Laura restore drill: backup muito antigo (${age_hours}h) para teste: ${latest_backup}."
  echo "ERROR: backup too old for restore drill (${age_hours}h)" >&2
  exit 1
fi

drill_dir="$(mktemp -d /tmp/laura_restore_drill_XXXXXX)"
cleanup() {
  rm -rf "$drill_dir"
}
trap cleanup EXIT

if ! tar -xzf "$latest_backup" -C "$drill_dir"; then
  notify "Laura restore drill: falha ao extrair backup ${latest_backup}."
  echo "ERROR: failed to extract backup" >&2
  exit 1
fi

required_items=("README.md" "pyproject.toml" "requirements.txt" "scripts" "shopee_agent")
for item in "${required_items[@]}"; do
  if [[ ! -e "$drill_dir/$item" ]]; then
    notify "Laura restore drill: item ausente no restore simulado (${item}) do backup ${latest_backup}."
    echo "ERROR: missing required item in drill restore: $item" >&2
    exit 1
  fi
done

summary="Laura restore drill OK: backup ${latest_backup} restaurado em ambiente temporario (${drill_dir})."
echo "$summary"
notify "$summary"
