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

"$PY_CMD" -m shopee_agent.cli ingest-order-revenue \
  --days "${LAURA_ORDER_REVENUE_INGEST_DAYS:-30}" \
  --page-size "${LAURA_ORDER_REVENUE_PAGE_SIZE:-50}" \
  --max-orders "${LAURA_ORDER_REVENUE_MAX_ORDERS:-200}"