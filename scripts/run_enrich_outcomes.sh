#!/usr/bin/env bash
# Wrapper to run the enrich_outcomes worker inside the project's virtualenv

set -euo pipefail

ROOT_DIR="/home/shopee/agente"
VENV_PY="$ROOT_DIR/.venv/bin/python"
LOG_DIR="$ROOT_DIR/logs"

mkdir -p "$LOG_DIR"

if [ ! -x "$VENV_PY" ]; then
  echo "Virtualenv python not found at $VENV_PY" >&2
  exit 1
fi

ARGS=("$@")

OUT_FILE="$LOG_DIR/enrich_outcomes_run.out"
ERR_FILE="$LOG_DIR/enrich_outcomes_run.err"
MAIN_LOG="$LOG_DIR/enrich_outcomes.log"
MAIN_ERR_LOG="$LOG_DIR/enrich_outcomes.err"
STATUS_FILE="$ROOT_DIR/reports/enrich_worker_status.json"

# Recreate artifacts so old root-owned files do not block the wrapper.
rm -f "$OUT_FILE" "$ERR_FILE" "$MAIN_LOG" "$MAIN_ERR_LOG" "$STATUS_FILE"

set +e
"$VENV_PY" -m shopee_agent.enrich_outcomes "${ARGS[@]}" > "$OUT_FILE" 2> "$ERR_FILE"
EXIT_CODE=$?
set -e

# parse updated count from stdout
UPDATED=0
if grep -q "Updated outcomes:" "$OUT_FILE"; then
  UPDATED=$(grep "Updated outcomes:" "$OUT_FILE" | tail -1 | awk -F': ' '{print $2}' | tr -d '\\r' | tr -d '\\n')
fi

# create status file
mkdir -p "$(dirname "$STATUS_FILE")"
if [ $EXIT_CODE -eq 0 ]; then
  "$VENV_PY" - <<PY > "$STATUS_FILE"
import json, datetime
print(json.dumps({
  "last_run": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
  "last_success": True,
  "last_updated_count": int($UPDATED),
  "last_error": None
}))
PY
else
  ERR_CONTENT=$(tail -n 50 "$ERR_FILE" | "$VENV_PY" -c "import sys, json; print(json.dumps(sys.stdin.read()))")
  "$VENV_PY" - <<PY > "$STATUS_FILE"
import json, datetime
print(json.dumps({
  "last_run": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
  "last_success": False,
  "last_updated_count": int($UPDATED),
  "last_error": ERR_CONTENT
}))
PY
fi

# append run output to main logs for history
cat "$OUT_FILE" >> "$MAIN_LOG"
cat "$ERR_FILE" >> "$MAIN_ERR_LOG"

exit $EXIT_CODE
