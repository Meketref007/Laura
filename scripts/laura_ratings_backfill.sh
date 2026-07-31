#!/bin/bash
# laura_ratings_backfill.sh - Process all pending unanswered ratings
# Usage: ./laura_ratings_backfill.sh [--lookback-days N] [--dry-run]
# Designed for cron scheduling (daily run)

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

# Load environment
if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

# Parameters
LOOKBACK_DAYS="${LAURA_RATINGS_BACKFILL_DAYS:-60}"
BATCH_SIZE="${LAURA_RATINGS_BACKFILL_BATCH_SIZE:-50}"
ACCESS_TOKEN="${SHOPEE_DEFAULT_ACCESS_TOKEN:-}"
SHOP_ID="${SHOPEE_DEFAULT_SHOP_ID:-}"
DRY_RUN="${1:-}"

# Validate
if [[ -z "$ACCESS_TOKEN" || -z "$SHOP_ID" ]]; then
    echo "ERROR: SHOPEE_DEFAULT_ACCESS_TOKEN and SHOPEE_DEFAULT_SHOP_ID must be set in .env"
    exit 1
fi

# Activate venv if available
if [[ -d .venv ]]; then
    source .venv/bin/activate
fi

# Run ratings backfill
.venv/bin/python -m shopee_agent.cli ratings-backfill \
    --access-token "$ACCESS_TOKEN" \
    --shop-id "$SHOP_ID" \
    --lookback-days "$LOOKBACK_DAYS" \
    --batch-size "$BATCH_SIZE" \
    ${DRY_RUN:+$DRY_RUN}

exit 0
