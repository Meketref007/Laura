#!/usr/bin/env bash
# laura_reports_cron.sh
# Runs daily sales report and keeps recent reports for a retention window.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# Load .env if present
if [ -f ".env" ]; then
  # shellcheck disable=SC1091
  . .env
fi

DAYS=${DAYS:-1}
PAGE_SIZE=${PAGE_SIZE:-50}
RETENTION_DAYS=${RETENTION_DAYS:-90}
DRY_RUN=${DRY_RUN:-0}

# Prefer virtualenv python if present
PY_CMD="${ROOT_DIR}/.venv/bin/python"
if [ ! -x "$PY_CMD" ]; then
  PY_CMD="python3"
fi

REPORT_CMD=("$PY_CMD" -m shopee_agent.cli report-sales --days "$DAYS" --page-size "$PAGE_SIZE")

if [ "$DRY_RUN" = "1" ] || [ "$DRY_RUN" = "true" ]; then
  echo "DRY RUN: would run: ${REPORT_CMD[*]}"
  exec "${REPORT_CMD[@]}" --dry-run
else
  echo "Running sales report: ${REPORT_CMD[*]}"
  "${REPORT_CMD[@]}"
fi

# Prune old reports
find reports -name 'sales_report_*.json' -type f -mtime +${RETENTION_DAYS} -print -delete || true

echo "Report run complete. Retention: ${RETENTION_DAYS} days"
