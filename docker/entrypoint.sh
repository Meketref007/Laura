#!/bin/bash
set -e

# Wait for Ollama if using local LLM
if [ -n "${LAURA_OLLAMA_HOST:-}" ]; then
    OLLAMA_URL="${LAURA_OLLAMA_HOST}:${LAURA_OLLAMA_PORT:-11434}"
    echo "Waiting for Ollama at $OLLAMA_URL..."
    for i in $(seq 1 30); do
        if curl -sf "$OLLAMA_URL/api/tags" > /dev/null 2>&1; then
            echo "Ollama is ready"
            break
        fi
        if [ "$i" -eq 30 ]; then
            echo "Warning: Ollama not reachable after 30s, continuing anyway"
        fi
        sleep 1
    done
fi

# Ensure required directories exist
mkdir -p /home/shopee/agente/logs \
         /home/shopee/agente/reports \
         /home/shopee/agente/backups

# Copy .env from mounted env/ directory (workaround for Windows bind mount locking)
if [ -f /home/shopee/agente/env/.env ]; then
    cp /home/shopee/agente/env/.env /home/shopee/agente/.env 2>/dev/null || true
fi

exec "$@"
