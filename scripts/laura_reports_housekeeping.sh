#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
RETENTION_DAYS="${LAURA_REPORT_RETENTION_DAYS:-14}"
METRICS_AUDIT_RETENTION_DAYS="${LAURA_METRICS_AUDIT_RETENTION_DAYS:-30}"
METRICS_AUDIT_SELF_TEST_RETENTION_DAYS="${LAURA_METRICS_AUDIT_SELF_TEST_RETENTION_DAYS:-$METRICS_AUDIT_RETENTION_DAYS}"
METRICS_AUDIT_SELF_TEST_DIGEST_RETENTION_DAYS="${LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_RETENTION_DAYS:-$METRICS_AUDIT_SELF_TEST_RETENTION_DAYS}"
METRICS_AUDIT_SELF_TEST_DIGEST_STATE_RETENTION_DAYS="${LAURA_METRICS_AUDIT_SELF_TEST_DIGEST_STATE_RETENTION_DAYS:-7}"
PROFITABILITY_RETENTION_DAYS="${LAURA_PROFITABILITY_RETENTION_DAYS:-30}"
WEBHOOK_READY_AUDIT_RETENTION_DAYS="${LAURA_WEBHOOK_READY_AUDIT_RETENTION_DAYS:-30}"

if ! [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
  RETENTION_DAYS=14
fi
if ! [[ "$METRICS_AUDIT_RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
  METRICS_AUDIT_RETENTION_DAYS=30
fi
if ! [[ "$METRICS_AUDIT_SELF_TEST_RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
  METRICS_AUDIT_SELF_TEST_RETENTION_DAYS="$METRICS_AUDIT_RETENTION_DAYS"
fi
if ! [[ "$METRICS_AUDIT_SELF_TEST_DIGEST_RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
  METRICS_AUDIT_SELF_TEST_DIGEST_RETENTION_DAYS="$METRICS_AUDIT_SELF_TEST_RETENTION_DAYS"
fi
if ! [[ "$METRICS_AUDIT_SELF_TEST_DIGEST_STATE_RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
  METRICS_AUDIT_SELF_TEST_DIGEST_STATE_RETENTION_DAYS=7
fi
if ! [[ "$PROFITABILITY_RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
  PROFITABILITY_RETENTION_DAYS=30
fi
if ! [[ "$WEBHOOK_READY_AUDIT_RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
  WEBHOOK_READY_AUDIT_RETENTION_DAYS=30
fi

if [[ ! -d "$REPORTS_DIR" ]]; then
  echo "Laura reports housekeeping: reports directory not found, nothing to do."
  exit 0
fi

find "$REPORTS_DIR" \
  -maxdepth 1 \
  -type f \
  -name "laura_incident_*.tar.gz" \
  -mtime "+$RETENTION_DAYS" \
  -print \
  -delete

find "$REPORTS_DIR" \
  -maxdepth 1 \
  -type d \
  -name "laura_incident_*" \
  -mtime "+$RETENTION_DAYS" \
  -print \
  -exec rm -rf {} +

audit_file="$REPORTS_DIR/laura_metrics_auto_remediate_audit.jsonl"
if [[ -f "$audit_file" ]]; then
  python3 - <<PY
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

path = Path("$audit_file")
retention_days = int("$METRICS_AUDIT_RETENTION_DAYS")
cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

kept = []
for line in path.read_text(encoding="utf-8").splitlines():
    s = line.strip()
    if not s:
        continue
    try:
        row = json.loads(s)
        ts = row.get("timestamp")
        if not ts:
            continue
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt >= cutoff:
            kept.append(json.dumps(row, ensure_ascii=True))
    except Exception:
        continue

path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
print(f"Laura reports housekeeping: metrics audit rows kept={len(kept)} retention={retention_days}d")
PY
fi

self_test_history_file="$REPORTS_DIR/laura_metrics_audit_self_test_history.jsonl"
if [[ -f "$self_test_history_file" ]]; then
  python3 - <<PY
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

path = Path("$self_test_history_file")
retention_days = int("$METRICS_AUDIT_SELF_TEST_RETENTION_DAYS")
cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

kept = []
for line in path.read_text(encoding="utf-8").splitlines():
  s = line.strip()
  if not s:
    continue
  try:
    row = json.loads(s)
    ts = row.get("timestamp")
    if not ts:
      continue
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if dt >= cutoff:
      kept.append(json.dumps(row, ensure_ascii=True))
  except Exception:
    continue

path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
print(f"Laura reports housekeeping: self-test rows kept={len(kept)} retention={retention_days}d")
PY
fi

self_test_digest_history_file="$REPORTS_DIR/laura_metrics_audit_self_test_digest_history.jsonl"
if [[ -f "$self_test_digest_history_file" ]]; then
  python3 - <<PY
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

path = Path("$self_test_digest_history_file")
retention_days = int("$METRICS_AUDIT_SELF_TEST_DIGEST_RETENTION_DAYS")
cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

kept = []
for line in path.read_text(encoding="utf-8").splitlines():
  s = line.strip()
  if not s:
    continue
  try:
    row = json.loads(s)
    ts = row.get("timestamp")
    if not ts:
      continue
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if dt >= cutoff:
      kept.append(json.dumps(row, ensure_ascii=True))
  except Exception:
    continue

path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
print(f"Laura reports housekeeping: self-test digest rows kept={len(kept)} retention={retention_days}d")
PY
fi

profitability_events_file="$REPORTS_DIR/laura_profitability_events.jsonl"
if [[ -f "$profitability_events_file" ]]; then
  python3 - <<PY
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

path = Path("$profitability_events_file")
retention_days = int("$PROFITABILITY_RETENTION_DAYS")
cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

kept = []
for line in path.read_text(encoding="utf-8").splitlines():
  s = line.strip()
  if not s:
    continue
  try:
    row = json.loads(s)
    ts = row.get("timestamp")
    if not ts:
      continue
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if dt >= cutoff:
      kept.append(json.dumps(row, ensure_ascii=True))
  except Exception:
    continue

path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
print(f"Laura reports housekeeping: profitability events kept={len(kept)} retention={retention_days}d")
PY
fi

profitability_history_file="$REPORTS_DIR/laura_profitability_history.jsonl"
if [[ -f "$profitability_history_file" ]]; then
  python3 - <<PY
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

path = Path("$profitability_history_file")
retention_days = int("$PROFITABILITY_RETENTION_DAYS")
cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

kept = []
for line in path.read_text(encoding="utf-8").splitlines():
  s = line.strip()
  if not s:
    continue
  try:
    row = json.loads(s)
    ts = row.get("recorded_at") or row.get("timestamp")
    if not ts:
      continue
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if dt >= cutoff:
      kept.append(json.dumps(row, ensure_ascii=True))
  except Exception:
    continue

path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
print(f"Laura reports housekeeping: profitability history kept={len(kept)} retention={retention_days}d")
PY
fi

profitability_audit_file="$REPORTS_DIR/laura_profitability_actions_audit.jsonl"
if [[ -f "$profitability_audit_file" ]]; then
  python3 - <<PY
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

path = Path("$profitability_audit_file")
retention_days = int("$PROFITABILITY_RETENTION_DAYS")
cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

kept = []
for line in path.read_text(encoding="utf-8").splitlines():
  s = line.strip()
  if not s:
    continue
  try:
    row = json.loads(s)
    ts = row.get("timestamp")
    if not ts:
      continue
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if dt >= cutoff:
      kept.append(json.dumps(row, ensure_ascii=True))
  except Exception:
    continue

path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
print(f"Laura reports housekeeping: profitability audit kept={len(kept)} retention={retention_days}d")
PY
fi

profitability_archive_dir="$REPORTS_DIR/profitability_ingest_archive"
if [[ -d "$profitability_archive_dir" ]]; then
  find "$profitability_archive_dir" \
    -maxdepth 1 \
    -type f \
    -name "laura_profitability_events_inbox_*.csv" \
    -mtime "+$PROFITABILITY_RETENTION_DAYS" \
    -print \
    -delete
fi

webhook_ready_audit_file="$REPORTS_DIR/laura_webhook_ready_audit.jsonl"
if [[ -f "$webhook_ready_audit_file" ]]; then
  python3 - <<PY
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

path = Path("$webhook_ready_audit_file")
retention_days = int("$WEBHOOK_READY_AUDIT_RETENTION_DAYS")
cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

kept = []
for line in path.read_text(encoding="utf-8").splitlines():
  s = line.strip()
  if not s:
    continue
  try:
    row = json.loads(s)
    ts = row.get("timestamp")
    if not ts:
      continue
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if dt >= cutoff:
      kept.append(json.dumps(row, ensure_ascii=True))
  except Exception:
    continue

path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
print(f"Laura reports housekeeping: webhook readiness audit kept={len(kept)} retention={retention_days}d")
PY
fi

find "$REPORTS_DIR" \
  -maxdepth 1 \
  -type f \
  \( \
    -name "laura_metrics_audit_self_test_guard.state" -o \
    -name "laura_metrics_audit_self_test_digest_freshness_guard.state" -o \
    -name "laura_metrics_audit_self_test_digest_volume_guard.state" -o \
    -name "laura_metrics_audit_self_test_digest_schema_guard.state" -o \
    -name "laura_metrics_audit_self_test_digest_early_warning.state" -o \
    -name "laura_profitability_input_freshness_guard.state" \
  \) \
  -mtime "+$METRICS_AUDIT_SELF_TEST_DIGEST_STATE_RETENTION_DAYS" \
  -print \
  -delete

echo "Laura reports housekeeping OK: retention=${RETENTION_DAYS} days, metrics_audit_retention=${METRICS_AUDIT_RETENTION_DAYS} days, self_test_retention=${METRICS_AUDIT_SELF_TEST_RETENTION_DAYS} days, self_test_digest_retention=${METRICS_AUDIT_SELF_TEST_DIGEST_RETENTION_DAYS} days, self_test_digest_state_retention=${METRICS_AUDIT_SELF_TEST_DIGEST_STATE_RETENTION_DAYS} days, profitability_retention=${PROFITABILITY_RETENTION_DAYS} days, webhook_ready_audit_retention=${WEBHOOK_READY_AUDIT_RETENTION_DAYS} days"
