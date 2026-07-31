#!/bin/bash
set -e

echo "=== Laura Agent Startup ==="

# Wait for Ollama
echo "Waiting for Ollama..."
until curl -s http://${OLLAMA_HOST:-localhost:11434}/api/tags > /dev/null 2>&1; do
    sleep 2
done
echo "Ollama ready!"

# Download models
echo "Checking models..."
python -m shopee_agent.llm_manager

# Start webhook server in background
echo "Starting webhook..."
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
