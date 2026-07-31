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

"$PY_CMD" -m shopee_agent.cli orders-notify-poll \
  --window-minutes "${LAURA_ORDERS_NOTIFY_WINDOW_MINUTES:-180}" \
  --page-size "${LAURA_ORDERS_NOTIFY_PAGE_SIZE:-50}" \
  --max-orders "${LAURA_ORDERS_NOTIFY_MAX_ORDERS:-100}"
