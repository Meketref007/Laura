#!/bin/bash
# ==============================================================================
# Script: laura_alerts_dispatcher.sh
# Purpose: Run analysis + evaluate alerts + dispatch to webhooks
# ==============================================================================

set -e

# Load environment from .env
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -o allexport
    source "$PROJECT_ROOT/.env"
    set +o allexport
fi

# Configuration
PROMPT_TYPE="${PROMPT_TYPE:-general_agent}"
MODEL="${LAURA_LLM_MODEL:-mistral}"
DAYS="${DAYS:-1}"
DRY_RUN="${DRY_RUN:-0}"
WEBHOOK_SLACK="${WEBHOOK_SLACK:-}"
WEBHOOK_DISCORD="${WEBHOOK_DISCORD:-}"

TIMESTAMP=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
LOG_DIR="${PROJECT_ROOT}/logs"
REPORT_DIR="${PROJECT_ROOT}/reports"

mkdir -p "$LOG_DIR" "$REPORT_DIR"

LOG_FILE="${LOG_DIR}/laura_alerts_dispatcher_${TIMESTAMP}.log"

log() {
    echo "[${TIMESTAMP}] $1" | tee -a "$LOG_FILE"
}

# Main execution
log "Starting alerts dispatcher (prompt_type=$PROMPT_TYPE, model=$MODEL)"

cd "$PROJECT_ROOT"

# 1. Run store analysis
log "Running store analysis..."
ANALYSIS_CMD=(
    "python3" "-m" "shopee_agent.cli" "store-analysis"
    "--prompt-type" "$PROMPT_TYPE"
    "--model" "$MODEL"
    "--days" "$DAYS"
)

if [[ "$DRY_RUN" == "1" ]]; then
    ANALYSIS_CMD+=("--dry-run")
    log "DRY_RUN mode enabled"
fi

if ! "${ANALYSIS_CMD[@]}" >> "$LOG_FILE" 2>&1; then
    log "✗ Analysis failed"
    exit 1
fi

log "✓ Analysis completed"

# 2. Generate alerts (if webhooks configured)
if [[ -z "$WEBHOOK_SLACK" ]] && [[ -z "$WEBHOOK_DISCORD" ]]; then
    log "No webhooks configured; skipping alert dispatch"
    exit 0
fi

log "Generating alerts..."
python3 << 'PYTHON_SCRIPT'
import json
import sys
import os
from datetime import datetime
from pathlib import Path

# Find latest analysis file
report_dir = Path("reports")
analysis_files = sorted(report_dir.glob(f"store_analysis_*.json"))
if not analysis_files:
    print("No analysis file found", file=sys.stderr)
    sys.exit(1)

latest_analysis = analysis_files[-1]
with open(latest_analysis) as f:
    data = json.load(f)

analysis = data.get("analysis", {})

# Extract metrics
metrics = {
    "margin_pct": analysis.get("metrics", {}).get("margin_pct", 0),
    "roas": analysis.get("metrics", {}).get("roas", 0),
    "refund_rate_pct": analysis.get("metrics", {}).get("refund_rate_pct", 0),
    "order_volume": analysis.get("metrics", {}).get("order_volume", 0),
    "model": analysis.get("model", "unknown"),
}

# Check for fallback mode
if "fallback" in metrics["model"]:
    metrics["ollama_error"] = True

# Generate alerts
from shopee_agent.alerts import create_alerts_engine, get_default_alert_config

engine = create_alerts_engine()
config = get_default_alert_config()
alerts_list = engine.evaluate(metrics, config)

print(json.dumps({
    "alerts_count": len(alerts_list),
    "alerts": [{
        "rule": a.rule.value,
        "severity": a.severity.value,
        "title": a.title,
        "message": a.message,
    } for a in alerts_list],
}))

PYTHON_SCRIPT

log "Alert generation completed"

exit 0
