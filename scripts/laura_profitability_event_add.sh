#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
EVENTS_FILE="$REPORTS_DIR/laura_profitability_events.jsonl"

usage() {
  cat <<'USAGE'
Usage:
  laura_profitability_event_add.sh \
    --revenue 1000 --cogs 600 --ad-spend 120 --shipping-subsidy 30 --refunds 20 --orders 12 [--timestamp ISO8601]
USAGE
}

TIMESTAMP="$(date -Is)"
REVENUE=""
COGS=""
AD_SPEND=""
SHIPPING_SUBSIDY=""
REFUNDS=""
ORDERS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --timestamp)
      TIMESTAMP="$2"
      shift 2
      ;;
    --revenue)
      REVENUE="$2"
      shift 2
      ;;
    --cogs)
      COGS="$2"
      shift 2
      ;;
    --ad-spend)
      AD_SPEND="$2"
      shift 2
      ;;
    --shipping-subsidy)
      SHIPPING_SUBSIDY="$2"
      shift 2
      ;;
    --refunds)
      REFUNDS="$2"
      shift 2
      ;;
    --orders)
      ORDERS="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$REVENUE" || -z "$COGS" || -z "$AD_SPEND" || -z "$SHIPPING_SUBSIDY" || -z "$REFUNDS" || -z "$ORDERS" ]]; then
  echo "All metric arguments are required." >&2
  usage
  exit 2
fi

mkdir -p "$REPORTS_DIR"

python3 - <<PY >> "$EVENTS_FILE"
import json
from datetime import datetime

timestamp = "$TIMESTAMP"
# Validate timestamp format to avoid malformed history rows.
try:
  datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
except Exception as exc:
  raise SystemExit(f"Invalid --timestamp: {exc}")

row = {
  "timestamp": timestamp,
  "revenue": float("$REVENUE"),
  "cogs": float("$COGS"),
  "ad_spend": float("$AD_SPEND"),
  "shipping_subsidy": float("$SHIPPING_SUBSIDY"),
  "refunds": float("$REFUNDS"),
  "orders": int("$ORDERS"),
}
print(json.dumps(row, ensure_ascii=True))
PY

echo "Laura profitability event appended: $EVENTS_FILE"