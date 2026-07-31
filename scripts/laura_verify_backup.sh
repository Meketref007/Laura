#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
BACKUP_DIR="$ROOT_DIR/backups"
MAX_BACKUP_AGE_HOURS="${LAURA_VERIFY_BACKUP_MAX_AGE_HOURS:-48}"

if ! [[ "$MAX_BACKUP_AGE_HOURS" =~ ^[0-9]+$ ]]; then
  MAX_BACKUP_AGE_HOURS=48
fi

notify_failure() {
  local message="$1"
  if [[ -n "${LAURA_ALERT_TELEGRAM_BOT_TOKEN:-}" && -n "${LAURA_ALERT_TELEGRAM_CHAT_ID:-}" ]]; then
    curl -sS -X POST \
      "https://api.telegram.org/bot${LAURA_ALERT_TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d "chat_id=${LAURA_ALERT_TELEGRAM_CHAT_ID}" \
      --data-urlencode "text=${message}" \
      >/dev/null || true
  fi
}

if [[ ! -d "$BACKUP_DIR" ]]; then
  notify_failure "Laura backup verify: diretorio de backups nao encontrado (${BACKUP_DIR})."
  echo "ERROR: backup directory not found: $BACKUP_DIR" >&2
  exit 1
fi

latest_backup="$(ls -1t "$BACKUP_DIR"/laura_backup_*.tar.gz 2>/dev/null | head -n 1 || true)"
if [[ -z "$latest_backup" ]]; then
  notify_failure "Laura backup verify: nenhum arquivo de backup encontrado em ${BACKUP_DIR}."
  echo "ERROR: no backup file found" >&2
  exit 1
fi

now_ts=$(date +%s)
file_ts=$(stat -c %Y "$latest_backup")
age_hours=$(( (now_ts - file_ts) / 3600 ))

if (( age_hours > MAX_BACKUP_AGE_HOURS )); then
  notify_failure "Laura backup verify: backup mais recente com ${age_hours}h (limite ${MAX_BACKUP_AGE_HOURS}h): ${latest_backup}."
  echo "ERROR: latest backup too old (${age_hours}h): $latest_backup" >&2
  exit 1
fi

if ! tar -tzf "$latest_backup" >/tmp/laura_verify_backup.list 2>/tmp/laura_verify_backup.err; then
  notify_failure "Laura backup verify: arquivo corrompido ou invalido: ${latest_backup}."
  echo "ERROR: backup integrity check failed: $latest_backup" >&2
  cat /tmp/laura_verify_backup.err >&2 || true
  exit 1
fi

required_items=("README.md" "pyproject.toml" "requirements.txt" "scripts" "shopee_agent")
for item in "${required_items[@]}"; do
  if ! grep -qx "$item\|$item/.*" /tmp/laura_verify_backup.list; then
    notify_failure "Laura backup verify: item obrigatorio ausente no backup ${latest_backup}: ${item}."
    echo "ERROR: required item missing in backup: $item" >&2
    exit 1
  fi
done

echo "Laura backup verify OK: $latest_backup (age=${age_hours}h)"
