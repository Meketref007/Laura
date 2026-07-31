#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

set -a
source "$ROOT_DIR/.env"
set +a

if [ -f "${ROOT_DIR}/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.venv/bin/activate"
fi

SHOP_ID=${LAURA_SHOP_ID:-${SHOPEE_DEFAULT_SHOP_ID:-}}
ACCESS_TOKEN=${LAURA_ACCESS_TOKEN:-${SHOPEE_DEFAULT_ACCESS_TOKEN:-}}
THRESHOLD=${LAURA_LOW_STOCK_THRESHOLD:-5}
MAX_ITEMS=${LAURA_INVENTORY_MAX_ITEMS:-50}
PAGE_SIZE=${LAURA_INVENTORY_PAGE_SIZE:-50}

if [ -z "$SHOP_ID" ] || [ -z "$ACCESS_TOKEN" ]; then
  echo "ERROR: LAURA_SHOP_ID or LAURA_ACCESS_TOKEN not set; aborting"
  exit 2
fi

.venv/bin/python -m shopee_agent.cli inventory-monitor \
  --shop-id "$SHOP_ID" \
  --access-token "$ACCESS_TOKEN" \
  --low-stock-threshold "$THRESHOLD" \
  --max-items "$MAX_ITEMS" \
  --page-size "$PAGE_SIZE"
