#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
EVENTS_FILE="$REPORTS_DIR/laura_profitability_events.jsonl"
OUTPUT_FILE="$REPORTS_DIR/laura_profitability_inputs_latest.json"

ENABLED="${LAURA_PROFITABILITY_INPUT_BUILDER_ENABLED:-1}"
WINDOW_HOURS="${LAURA_PROFITABILITY_INPUT_WINDOW_HOURS:-24}"

if ! [[ "$ENABLED" =~ ^[01]$ ]]; then
  ENABLED=1
fi
if ! [[ "$WINDOW_HOURS" =~ ^[0-9]+$ ]]; then
  WINDOW_HOURS=24
fi

if [[ "$ENABLED" == "0" ]]; then
  echo "Laura profitability input builder disabled by LAURA_PROFITABILITY_INPUT_BUILDER_ENABLED=0"
  exit 0
fi

mkdir -p "$REPORTS_DIR"
cd "$ROOT_DIR"
set -a
source "$ROOT_DIR/.env"
set +a

python3 - <<PY
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

now = datetime.now(timezone.utc)
cutoff = now - timedelta(hours=int("$WINDOW_HOURS"))

events_file = Path("$EVENTS_FILE")
output_file = Path("$OUTPUT_FILE")

totals = {
  "revenue": 0.0,
  "cogs": 0.0,
  "ad_spend": 0.0,
  "shipping_subsidy": 0.0,
  "refunds": 0.0,
  "orders": 0,
}

count = 0
invalid_lines = 0

if events_file.exists():
  for raw in events_file.read_text(encoding="utf-8").splitlines():
    s = raw.strip()
    if not s:
      continue
    try:
      row = json.loads(s)
      ts = row.get("timestamp")
      if not isinstance(ts, str) or not ts.strip():
        invalid_lines += 1
        continue
      dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
      if dt < cutoff:
        continue

      totals["revenue"] += float(row.get("revenue", 0.0) or 0.0)
      totals["cogs"] += float(row.get("cogs", 0.0) or 0.0)
      totals["ad_spend"] += float(row.get("ad_spend", 0.0) or 0.0)
      totals["shipping_subsidy"] += float(row.get("shipping_subsidy", 0.0) or 0.0)
      totals["refunds"] += float(row.get("refunds", 0.0) or 0.0)
      totals["orders"] += int(row.get("orders", 0) or 0)
      count += 1
    except Exception:
      invalid_lines += 1

out = {
  "timestamp": now.isoformat(),
  "window_hours": int("$WINDOW_HOURS"),
  "source_file": str(events_file),
  "events_count": count,
  "invalid_lines": invalid_lines,
  "revenue": round(totals["revenue"], 2),
  "cogs": round(totals["cogs"], 2),
  "ad_spend": round(totals["ad_spend"], 2),
  "shipping_subsidy": round(totals["shipping_subsidy"], 2),
  "refunds": round(totals["refunds"], 2),
  "orders": int(totals["orders"]),
}

output_file.write_text(json.dumps(out, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
print(json.dumps(out, ensure_ascii=True))
PY

echo "Laura profitability input built: $OUTPUT_FILE"