#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  chmod 600 .env
  echo "OK: permissions set to 600 for .env"
else
  echo "WARN: .env not found"
fi

if [[ -f ".env.bak" ]]; then
  chmod 600 .env.bak
  echo "OK: permissions set to 600 for .env.bak"
else
  echo "INFO: .env.bak not found"
fi

# Harden restore snapshots if present
for f in .env.pre-restore.*; do
  if [[ -e "$f" ]]; then
    chmod 600 "$f"
    echo "OK: permissions set to 600 for $f"
  fi
done

echo "Laura env security hardening finished."
