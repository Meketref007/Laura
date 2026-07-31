#!/usr/bin/env bash
set -euo pipefail

# Small wrapper to run daily escrow ingestion.
# Usage: LAURA_SHOP_ID and LAURA_ACCESS_TOKEN should be set in environment or .env
# This script runs in project's venv if present.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Activate venv if exists
if [ -x "${ROOT_DIR}/.venv/bin/activate" ] || [ -f "${ROOT_DIR}/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "${ROOT_DIR}/.venv/bin/activate"
fi

SHOP_ID=${LAURA_SHOP_ID:-}
ACCESS_TOKEN=${LAURA_ACCESS_TOKEN:-}

if [ -z "$SHOP_ID" ] || [ -z "$ACCESS_TOKEN" ]; then
    echo "ERROR: LAURA_SHOP_ID or LAURA_ACCESS_TOKEN not set; aborting"
    exit 2
fi

# Run ingest (non-dry-run)
# We limit orders to 1000 to avoid runaway executions
.venv/bin/python -m shopee_agent.cli ingest-order-revenue --shop-id "$SHOP_ID" --access-token "$ACCESS_TOKEN" --max-orders 1000 || exit 1

echo "Ingest run completed"
