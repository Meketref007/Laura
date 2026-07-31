#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
DIGEST_LATEST_FILE="$REPORTS_DIR/laura_metrics_audit_self_test_digest_latest.json"
HISTORY_FILE="$REPORTS_DIR/laura_metrics_audit_self_test_history.jsonl"
DIGEST_HISTORY_FILE="$REPORTS_DIR/laura_metrics_audit_self_test_digest_history.jsonl"
STATE_FILES=(
  "$REPORTS_DIR/laura_metrics_audit_self_test_guard.state"
  "$REPORTS_DIR/laura_metrics_audit_self_test_digest_freshness_guard.state"
  "$REPORTS_DIR/laura_metrics_audit_self_test_digest_volume_guard.state"
  "$REPORTS_DIR/laura_metrics_audit_self_test_digest_schema_guard.state"
  "$REPORTS_DIR/laura_metrics_audit_self_test_digest_early_warning.state"
)

cd "$ROOT_DIR"
set -a
source "$ROOT_DIR/.env"
set +a

python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

root = Path("$ROOT_DIR")
reports = root / "reports"

files = {
    "digest_latest": reports / "laura_metrics_audit_self_test_digest_latest.json",
    "self_test_history": reports / "laura_metrics_audit_self_test_history.jsonl",
    "digest_history": reports / "laura_metrics_audit_self_test_digest_history.jsonl",
}
state_files = [Path(p) for p in [
    "$REPORTS_DIR/laura_metrics_audit_self_test_guard.state",
    "$REPORTS_DIR/laura_metrics_audit_self_test_digest_freshness_guard.state",
    "$REPORTS_DIR/laura_metrics_audit_self_test_digest_volume_guard.state",
    "$REPORTS_DIR/laura_metrics_audit_self_test_digest_schema_guard.state",
    "$REPORTS_DIR/laura_metrics_audit_self_test_digest_early_warning.state",
]]

def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None

def age_minutes_from_ts(value):
    dt = parse_ts(value)
    if dt is None:
        return None
    return int((datetime.now(timezone.utc) - dt).total_seconds() // 60)

def latest_json(path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def jsonl_stats(path):
    if not path.exists():
        return {"count": 0, "latest_ts": None, "oldest_ts": None, "invalid": 0}
    count = 0
    invalid = 0
    latest = None
    oldest = None
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            row = json.loads(s)
            ts = row.get("timestamp")
            dt = parse_ts(ts)
            if dt is None:
                invalid += 1
                continue
            count += 1
            if latest is None or dt > latest:
                latest = dt
            if oldest is None or dt < oldest:
                oldest = dt
        except Exception:
            invalid += 1
    return {
        "count": count,
        "latest_ts": latest.isoformat() if latest else None,
        "oldest_ts": oldest.isoformat() if oldest else None,
        "invalid": invalid,
    }

latest = latest_json(files["digest_latest"])
self_test_stats = jsonl_stats(files["self_test_history"])
digest_stats = jsonl_stats(files["digest_history"])

print(f"Laura self-test digest status for host: {Path('/etc/hostname').read_text(encoding='utf-8').strip() if Path('/etc/hostname').exists() else 'unknown'}")
print(f"Digest latest file: {files['digest_latest']}")
if latest is None:
    print("Digest latest: missing or invalid")
else:
    timestamp = latest.get("timestamp", "N/A")
    age_minutes = age_minutes_from_ts(timestamp)
    print(f"Digest latest timestamp: {timestamp}")
    print(f"Digest latest age_min: {age_minutes if age_minutes is not None else 'unknown'}")
    print(f"Digest trend: {latest.get('trend', 'unknown')}")
    current = latest.get("current", {}) if isinstance(latest.get("current"), dict) else {}
    previous = latest.get("previous", {}) if isinstance(latest.get("previous"), dict) else {}
    print(f"Current runs/failures: {current.get('total_runs', 0)}/{current.get('failed_runs', 0)}")
    print(f"Current failed rate pct: {current.get('failed_rate_pct', 0)}")
    print(f"Previous failed rate pct: {previous.get('failed_rate_pct', 0)}")
    print(f"Failed rate delta pct: {latest.get('failed_rate_delta_pct', 0)}")

print(f"Self-test history rows: {self_test_stats['count']}")
print(f"Self-test history latest_ts: {self_test_stats['latest_ts'] or 'N/A'}")
print(f"Self-test digest history rows: {digest_stats['count']}")
print(f"Self-test digest history latest_ts: {digest_stats['latest_ts'] or 'N/A'}")

for state_path in state_files:
    if not state_path.exists():
        print(f"State: {state_path.name} missing")
        continue
    try:
        raw = state_path.read_text(encoding='utf-8').strip()
    except Exception:
        raw = '<unreadable>'
    mtime = datetime.fromtimestamp(state_path.stat().st_mtime, timezone.utc).isoformat()
    age_min = int((datetime.now(timezone.utc) - datetime.fromtimestamp(state_path.stat().st_mtime, timezone.utc)).total_seconds() // 60)
    print(f"State: {state_path.name} age_min={age_min} mtime={mtime} raw={raw}")

print("Status: OK")
PY
