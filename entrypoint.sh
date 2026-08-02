#!/bin/bash
set -e

echo "=== Laura Agent Startup ==="

OLLAMA_HOST="${LAURA_OLLAMA_HOST:-http://localhost:11434}"

# Wait for Ollama
echo "Waiting for Ollama at $OLLAMA_HOST..."
until curl -s "${OLLAMA_HOST}/api/tags" > /dev/null 2>&1; do
    sleep 2
done
echo "Ollama ready!"

# Download models (LLM + vision)
MODEL="${LAURA_LLM_MODEL:-llama3.2:3b}"
echo "Checking models (LAURA_LLM_MODEL=${MODEL})..."
python -m shopee_agent.llm_manager

if [ "${LAURA_CEO_MODE}" = "1" ]; then
    echo "🚀 CEO MODE ATIVO — acoes executadas sem aprovacao humana"
else
    echo "Modo padrao: aprovacao humana obrigatoria (LAURA_CEO_MODE=1 para autonomia total)"
fi

# Start webhook server in background
echo "Starting webhook on :8766..."
python -m shopee_agent.cli webhook-start --host 0.0.0.0 --port 8766 &
WEBHOOK_PID=$!

# Start telegram bot in background
echo "Starting telegram bot..."
python -m shopee_agent.cli telegram-bot &
TELEGRAM_PID=$!

# Start daemon
echo "Starting daemon..."
python -m shopee_agent.laura_daemon

# Cleanup on exit
kill $WEBHOOK_PID $TELEGRAM_PID 2>/dev/null
echo "Laura stopped"
