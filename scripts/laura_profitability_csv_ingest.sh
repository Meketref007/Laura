#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
SOURCE_CSV="${LAURA_PROFITABILITY_CSV_SOURCE_FILE:-$REPORTS_DIR/laura_profitability_events_inbox.csv}"
EVENTS_FILE="$REPORTS_DIR/laura_profitability_events.jsonl"
ARCHIVE_DIR="${LAURA_PROFITABILITY_CSV_ARCHIVE_DIR:-$REPORTS_DIR/profitability_ingest_archive}"
ENABLED="${LAURA_PROFITABILITY_CSV_INGEST_ENABLED:-1}"

if ! [[ "$ENABLED" =~ ^[01]$ ]]; then
  ENABLED=1
fi

if [[ "$ENABLED" == "0" ]]; then
  echo "Laura profitability CSV ingest disabled by LAURA_PROFITABILITY_CSV_INGEST_ENABLED=0"
  exit 0
fi

mkdir -p "$REPORTS_DIR"
mkdir -p "$ARCHIVE_DIR"

if [[ ! -f "$SOURCE_CSV" ]]; then
  echo "Laura profitability CSV ingest: source file not found, nothing to import ($SOURCE_CSV)"
  exit 0
fi

tmp_result="$(python3 - <<PY
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

source = Path("$SOURCE_CSV")
events_file = Path("$EVENTS_FILE")

required = [
  "timestamp",
  "revenue",
  "cogs",
  "ad_spend",
  "shipping_subsidy",
  "refunds",
  "orders",
]

imported = 0
skipped = 0
errors = []
rows = []

with source.open("r", encoding="utf-8") as f:
  reader = csv.DictReader(f)
  headers = reader.fieldnames or []
  missing = [k for k in required if k not in headers]
  if missing:
    print(json.dumps({
      "ok": False,
      "error": f"missing columns: {', '.join(missing)}",
      "imported": 0,
      "skipped": 0,
    }, ensure_ascii=True))
    raise SystemExit(0)

  for i, row in enumerate(reader, start=2):
    try:
      ts = str(row.get("timestamp", "")).strip()
      datetime.fromisoformat(ts.replace("Z", "+00:00"))
      normalized = {
        "timestamp": ts,
        "revenue": float(row.get("revenue", 0.0) or 0.0),
        "cogs": float(row.get("cogs", 0.0) or 0.0),
        "ad_spend": float(row.get("ad_spend", 0.0) or 0.0),
        "shipping_subsidy": float(row.get("shipping_subsidy", 0.0) or 0.0),
        "refunds": float(row.get("refunds", 0.0) or 0.0),
        "orders": int(row.get("orders", 0) or 0),
      }
      rows.append(normalized)
      imported += 1
    except Exception as exc:
      skipped += 1
      errors.append(f"line {i}: {exc}")

if rows:
  with events_file.open("a", encoding="utf-8") as out:
    for r in rows:
      out.write(json.dumps(r, ensure_ascii=True) + "\\n")

print(json.dumps({
  "ok": True,
  "imported": imported,
  "skipped": skipped,
  "errors": errors[:5],
}, ensure_ascii=True))
PY
)"

ok="$(python3 - <<PY
import json
print(1 if json.loads('''$tmp_result''').get("ok") else 0)
PY
)"

if [[ "$ok" != "1" ]]; then
  err_msg="$(python3 - <<PY
import json
print(json.loads('''$tmp_result''').get("error", "unknown error"))
PY
)"
  echo "Laura profitability CSV ingest failed: $err_msg"
  exit 1
fi

imported="$(python3 - <<PY
import json
print(int(json.loads('''$tmp_result''').get("imported", 0)))
PY
)"
skipped="$(python3 - <<PY
import json
print(int(json.loads('''$tmp_result''').get("skipped", 0)))
PY
)"
errors_preview="$(python3 - <<PY
import json
errs = json.loads('''$tmp_result''').get("errors", [])
print(" | ".join(errs) if errs else "")
PY
)"

archive_file="$ARCHIVE_DIR/laura_profitability_events_inbox_$(date +%Y%m%d_%H%M%S).csv"
mv "$SOURCE_CSV" "$archive_file"

echo "Laura profitability CSV ingest OK: imported=${imported}, skipped=${skipped}, source_archived=${archive_file}"
if [[ -n "$errors_preview" ]]; then
  echo "Laura profitability CSV ingest warnings: ${errors_preview}"
fi