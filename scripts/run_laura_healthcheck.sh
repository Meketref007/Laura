#!/usr/bin/env bash
set -euo pipefail

cd /home/shopee/agente
PY_CMD="/home/shopee/agente/.venv/bin/python"
if [[ ! -x "$PY_CMD" ]]; then
	PY_CMD="python3"
fi

exec "$PY_CMD" -m shopee_agent.healthcheck_service
