#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORT_DIR="$ROOT_DIR/reports"
BASE_URL_FILE="$REPORT_DIR/laura_webhook_tunnel_latest.txt"
CALLBACK_URL_FILE="$REPORT_DIR/laura_webhook_callback_latest.txt"

cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_DIR/.env"
  set +a
fi

CALLBACK_PATH="${LAURA_WEBHOOK_PATH:-/webhook/shopee}"
if [[ -z "$CALLBACK_PATH" ]]; then
  CALLBACK_PATH="/webhook/shopee"
fi
if [[ "$CALLBACK_PATH" != /* ]]; then
  CALLBACK_PATH="/$CALLBACK_PATH"
fi

base_url=""
if [[ -f "$BASE_URL_FILE" ]]; then
  base_url="$(head -n 1 "$BASE_URL_FILE" || true)"
fi

callback_url=""
if [[ -f "$CALLBACK_URL_FILE" ]]; then
  callback_url="$(head -n 1 "$CALLBACK_URL_FILE" || true)"
fi

if [[ -z "$callback_url" && -n "$base_url" ]]; then
  callback_url="${base_url}${CALLBACK_PATH}"
fi

if [[ -z "$callback_url" ]]; then
  echo "status=error"
  echo "message=callback_url_not_available"
  echo "hint=run /home/shopee/agente/scripts/laura_tunnel_permanent.sh ensure"
  exit 1
fi

health_code_local="$(curl -s -m 10 -o /tmp/laura_webhook_health.out -w '%{http_code}' "${base_url}/health" || true)"

host="$(printf '%s' "$base_url" | sed -E 's#https?://([^/]+)/?.*#\1#')"
resolved_ip=""
if command -v nslookup >/dev/null 2>&1; then
  resolved_ip="$(nslookup "$host" 1.1.1.1 2>/dev/null | awk '/^Address: /{print $2}' | awk '!/:/' | head -n 1)"
fi

health_code_resolve=""
if [[ -n "$resolved_ip" ]]; then
  health_code_resolve="$(curl -s -m 10 --resolve "${host}:443:${resolved_ip}" -o /tmp/laura_webhook_health_resolve.out -w '%{http_code}' "${base_url}/health" || true)"
fi

echo "status=ok"
echo "base_url=${base_url}"
echo "callback_url=${callback_url}"
echo "health_http_code_local=${health_code_local}"
echo "dns_resolve_ip_1_1_1_1=${resolved_ip}"
echo "health_http_code_resolve=${health_code_resolve}"

if [[ "$health_code_local" == "000" && "$health_code_resolve" == "200" ]]; then
  echo "dns_local_resolver_issue=true"
fi
