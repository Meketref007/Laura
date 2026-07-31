#!/bin/bash
# laura_ollama_fix.sh - Diagnosis and repair utility for Ollama LLM service
# Usage: bash scripts/laura_ollama_fix.sh [--model tinyllama|mistral|llama2] [--force-pull]

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
MODEL="${LAURA_LLM_MODEL:-tinyllama}"
FORCE_PULL="${1:---dry-run}"

# Check for --force-pull flag
if [[ "$FORCE_PULL" == "--force-pull" ]]; then
    FORCE_PULL_FLAG="--force-pull"
else
    FORCE_PULL_FLAG=""
fi

# Activate venv if available
if [[ -d .venv ]]; then
    source .venv/bin/activate
fi

# Run ollama-fix
.venv/bin/python -m shopee_agent.cli ollama-fix \
    --model "$MODEL" \
    $FORCE_PULL_FLAG

exit 0
