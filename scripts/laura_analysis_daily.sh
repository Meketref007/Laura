#!/bin/bash
# ==============================================================================
# Script: laura_analysis_daily.sh
# Purpose: Run daily LLM-driven store analysis using Ollama models
# Dependencies: python3, shopee_agent.cli, Ollama running locally
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

# Configuration with environment variable overrides
PROMPT_TYPE="${PROMPT_TYPE:-general_agent}"  # general_agent, triage, product_diagnosis, daily_report
MODEL="${LAURA_LLM_MODEL:-mistral}"          # Ollama model name
DAYS="${DAYS:-1}"                            # Days window for analysis
DRY_RUN="${DRY_RUN:-0}"                      # 1 to skip LLM call
LOG_DIR="${PROJECT_ROOT}/logs"
REPORT_DIR="${PROJECT_ROOT}/reports"

# Create directories if needed
mkdir -p "$LOG_DIR" "$REPORT_DIR"

# Timestamp for logging
TIMESTAMP=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

# Log prefix
LOG_FILE="${LOG_DIR}/laura_analysis_${TIMESTAMP}.log"

# Log function
log() {
    echo "[${TIMESTAMP}] $1" | tee -a "$LOG_FILE"
}

# Main execution
log "Starting daily store analysis (prompt_type=$PROMPT_TYPE, model=$MODEL, days=$DAYS)"

cd "$PROJECT_ROOT"

# Build CLI command
CMD_ARGS=(
    "store-analysis"
    "--prompt-type" "$PROMPT_TYPE"
    "--model" "$MODEL"
    "--days" "$DAYS"
)

if [[ "$DRY_RUN" == "1" ]]; then
    CMD_ARGS+=("--dry-run")
    log "DRY_RUN mode enabled"
fi

# Run analysis
PY_CMD="${PROJECT_ROOT}/.venv/bin/python"
if [ ! -x "$PY_CMD" ]; then
    PY_CMD="python3"
fi

"$PY_CMD" -m shopee_agent.cli "${CMD_ARGS[@]}" >> "$LOG_FILE" 2>&1

EXIT_CODE=$?
if [[ $EXIT_CODE -eq 0 ]]; then
    log "✓ Analysis completed successfully"
else
    log "✗ Analysis failed with exit code $EXIT_CODE"
    exit $EXIT_CODE
fi

log "Cleaning up analysis logs older than 30 days"
find "$LOG_DIR" -name "laura_analysis_*.log" -type f -mtime +30 -delete

log "Daily analysis job completed"
