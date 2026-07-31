#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORT_DIR="$ROOT_DIR/reports"
CALLBACK_FILE="$REPORT_DIR/laura_webhook_callback_latest.txt"

READY_TIMEOUT_SECONDS="${LAURA_WEBHOOK_READY_TIMEOUT_SECONDS:-10}"
READY_MAX_LATENCY_SECONDS="${LAURA_WEBHOOK_READY_MAX_LATENCY_SECONDS:-3}"
READY_DNS_SERVER="${LAURA_WEBHOOK_READY_DNS_SERVER:-1.1.1.1}"
READY_RETRY_ATTEMPTS="${LAURA_WEBHOOK_READY_RETRY_ATTEMPTS:-2}"
READY_RETRY_BACKOFF_SECONDS="${LAURA_WEBHOOK_READY_RETRY_BACKOFF_SECONDS:-1}"

tmp_unsigned="$(mktemp /tmp/laura_webhook_ready_unsigned.XXXXXX)"
tmp_signed="$(mktemp /tmp/laura_webhook_ready_signed.XXXXXX)"
cleanup() {
  rm -f "$tmp_unsigned" "$tmp_signed"
}
trap cleanup EXIT


# Parse arguments
self_test_mode=0
for arg in "$@"; do
  case "$arg" in
    --self-test)
      self_test_mode=1
      ;;
  esac
done

cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_DIR/.env"
  set +a
fi

if [[ ! -f "$CALLBACK_FILE" ]]; then
  echo "status=error"
  echo "message=callback_file_missing"
  echo "hint=run /home/shopee/agente/scripts/laura_tunnel_permanent.sh ensure"
  exit 1
fi

if ! [[ "$READY_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]]; then
  READY_TIMEOUT_SECONDS=10
fi
if (( READY_TIMEOUT_SECONDS < 1 )); then
  READY_TIMEOUT_SECONDS=10
fi

if ! [[ "$READY_MAX_LATENCY_SECONDS" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  READY_MAX_LATENCY_SECONDS=3
fi

if ! [[ "$READY_RETRY_ATTEMPTS" =~ ^[0-9]+$ ]]; then
  READY_RETRY_ATTEMPTS=2
fi
if (( READY_RETRY_ATTEMPTS < 1 )); then
  READY_RETRY_ATTEMPTS=1
fi
if (( READY_RETRY_ATTEMPTS > 5 )); then
  READY_RETRY_ATTEMPTS=5
fi

if ! [[ "$READY_RETRY_BACKOFF_SECONDS" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  READY_RETRY_BACKOFF_SECONDS=1
fi

callback_url="$(head -n 1 "$CALLBACK_FILE" | tr -d '[:space:]')"
if [[ -z "$callback_url" ]]; then
  echo "status=error"
  echo "message=callback_url_empty"
  exit 1
fi

scheme="$(printf '%s' "$callback_url" | sed -nE 's#^(https?)://.*#\1#p')"
authority="$(printf '%s' "$callback_url" | sed -nE 's#^https?://([^/]+).*$#\1#p')"
if [[ -z "$scheme" || -z "$authority" ]]; then
  echo "status=error"
  echo "message=callback_url_invalid"
  echo "callback_url=$callback_url"
  exit 1
fi

authority_no_user="${authority##*@}"
host="$authority_no_user"
port=""
if [[ "$authority_no_user" =~ ^([^:]+):([0-9]+)$ ]]; then
  host="${BASH_REMATCH[1]}"
  port="${BASH_REMATCH[2]}"
fi

if [[ -z "$host" ]]; then
  echo "status=error"
  echo "message=callback_host_invalid"
  echo "callback_url=$callback_url"
  exit 1
fi

if [[ -z "$port" ]]; then
  if [[ "$scheme" == "https" ]]; then
    port="443"
  else
    port="80"
  fi
fi

resolved_ip=""
resolver_source="none"
if [[ "$host" =~ ^([0-9]{1,3}[.]){3}[0-9]{1,3}$ ]]; then
  resolved_ip="$host"
  resolver_source="host_literal"
else
  if command -v nslookup >/dev/null 2>&1; then
    resolved_ip="$(nslookup "$host" "$READY_DNS_SERVER" 2>/dev/null | awk '/^Address: /{print $2}' | awk '!/:/' | head -n 1 || true)"
    if [[ -n "$resolved_ip" ]]; then
      resolver_source="nslookup_external"
    fi
  fi

  if [[ -z "$resolved_ip" ]] && command -v getent >/dev/null 2>&1; then
    resolved_ip="$(getent ahostsv4 "$host" 2>/dev/null | awk 'NR==1{print $1}' || true)"
    if [[ -n "$resolved_ip" ]]; then
      resolver_source="getent_local"
    fi
  fi

  if [[ -z "$resolved_ip" ]] && command -v nslookup >/dev/null 2>&1; then
    resolved_ip="$(nslookup "$host" 2>/dev/null | awk '/^Address: /{print $2}' | awk '!/:/' | head -n 1 || true)"
    if [[ -n "$resolved_ip" ]]; then
      resolver_source="nslookup_local"
    fi
  fi

  if [[ -z "$resolved_ip" ]] && command -v host >/dev/null 2>&1; then
    resolved_ip="$(host -t A "$host" "$READY_DNS_SERVER" 2>/dev/null | awk '/has address/{print $NF}' | head -n 1 || true)"
    if [[ -n "$resolved_ip" ]]; then
      resolver_source="host_external"
    fi
  fi
fi

if [[ -z "$resolved_ip" ]]; then
  echo "status=error"
  echo "message=dns_resolution_failed"
  echo "callback_url=$callback_url"
  echo "host=$host"
  echo "dns_server=$READY_DNS_SERVER"
  exit 1
fi

resolve_args=()
if [[ "$resolver_source" != "host_literal" ]]; then
  resolve_args=(--resolve "${host}:${port}:${resolved_ip}")
fi

should_retry_code() {
  local code="${1:-}"
  case "$code" in
    000|429|500|502|503|504)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

run_probe() {
  local output_file="$1"
  shift

  local attempt=1
  local meta=""
  local code=""
  local latency=""

  while true; do
    meta="$(curl -s -m "$READY_TIMEOUT_SECONDS" "${resolve_args[@]}" -o "$output_file" -w '%{http_code} %{time_total}' "$@" "$callback_url" || true)"
    code="$(printf '%s' "$meta" | awk '{print $1}')"
    latency="$(printf '%s' "$meta" | awk '{print $2}')"

    if (( attempt >= READY_RETRY_ATTEMPTS )); then
      break
    fi
    if ! should_retry_code "$code"; then
      break
    fi

    attempt=$((attempt + 1))
    sleep "$READY_RETRY_BACKOFF_SECONDS"
  done

  PROBE_META="$meta"
  PROBE_CODE="$code"
  PROBE_LATENCY="$latency"
  PROBE_ATTEMPTS="$attempt"
}

run_probe "$tmp_unsigned" -X POST -H 'Content-Type: application/json' -d '{"verify":true}'
unsigned_meta="$PROBE_META"
unsigned_code="$PROBE_CODE"
unsigned_latency_seconds="$PROBE_LATENCY"
unsigned_attempts="$PROBE_ATTEMPTS"

signed_code="skip"
signed_latency_seconds="skip"
signed_attempts="0"
if [[ -n "${LAURA_WEBHOOK_SECRET:-}" ]]; then
  body='{"event_type":"shopee_updates","source":"shopee","data":{"ready_check":1}}'
  sig="$(printf '%s' "$body" | openssl dgst -sha256 -hmac "$LAURA_WEBHOOK_SECRET" | awk '{print $2}')"
  run_probe "$tmp_signed" -X POST -H 'Content-Type: application/json' -H "X-Webhook-Signature: $sig" -d "$body"
  signed_meta="$PROBE_META"
  signed_code="$PROBE_CODE"
  signed_latency_seconds="$PROBE_LATENCY"
  signed_attempts="$PROBE_ATTEMPTS"
fi

echo "status=ok"
echo "callback_url=$callback_url"
echo "callback_scheme=$scheme"
echo "callback_host=$host"
echo "callback_port=$port"
echo "resolved_ip=$resolved_ip"
echo "resolver_source=$resolver_source"
echo "dns_server=$READY_DNS_SERVER"
echo "timeout_seconds=$READY_TIMEOUT_SECONDS"
echo "retry_attempts_max=$READY_RETRY_ATTEMPTS"
echo "retry_backoff_seconds=$READY_RETRY_BACKOFF_SECONDS"
echo "max_latency_seconds=$READY_MAX_LATENCY_SECONDS"
echo "unsigned_code=$unsigned_code"
echo "unsigned_latency_seconds=$unsigned_latency_seconds"
echo "unsigned_attempts=$unsigned_attempts"
echo "signed_code=$signed_code"
echo "signed_latency_seconds=$signed_latency_seconds"
echo "signed_attempts=$signed_attempts"

if [[ "$unsigned_code" != "200" && "$unsigned_code" != "202" ]]; then
  echo "message=unsigned_non_2xx"
  echo "result=fail"
  exit 1
fi

if ! awk -v v="$unsigned_latency_seconds" -v max="$READY_MAX_LATENCY_SECONDS" 'BEGIN {exit !(v+0 <= max+0)}'; then
  echo "message=unsigned_latency_exceeded"
  echo "result=fail"
  exit 1
fi

if [[ "$signed_code" != "skip" && "$signed_code" != "200" && "$signed_code" != "202" ]]; then
  echo "message=signed_non_2xx"
  echo "result=fail"
  exit 1
fi

if [[ "$signed_latency_seconds" != "skip" ]]; then
  if ! awk -v v="$signed_latency_seconds" -v max="$READY_MAX_LATENCY_SECONDS" 'BEGIN {exit !(v+0 <= max+0)}'; then
    echo "message=signed_latency_exceeded"
    echo "result=fail"
    exit 1
  fi
fi


echo "result=ready_for_shopee_verify"

# Self-test output mode
if (( self_test_mode )); then
  self_test_status="ok"
  self_test_reason=""
  if [[ "$unsigned_code" != "200" && "$unsigned_code" != "202" ]]; then
    self_test_status="fail"
    self_test_reason="unsigned_non_2xx"
  elif ! awk -v v="$unsigned_latency_seconds" -v max="$READY_MAX_LATENCY_SECONDS" 'BEGIN {exit !(v+0 <= max+0)}'; then
    self_test_status="fail"
    self_test_reason="unsigned_latency_exceeded"
  elif [[ "$signed_code" != "skip" && "$signed_code" != "200" && "$signed_code" != "202" ]]; then
    self_test_status="fail"
    self_test_reason="signed_non_2xx"
  elif [[ "$signed_latency_seconds" != "skip" ]]; then
    if ! awk -v v="$signed_latency_seconds" -v max="$READY_MAX_LATENCY_SECONDS" 'BEGIN {exit !(v+0 <= max+0)}'; then
      self_test_status="fail"
      self_test_reason="signed_latency_exceeded"
    fi
  fi
  echo "self_test_status=$self_test_status"
  echo "self_test_reason=$self_test_reason"
  echo "self_test_time_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
fi
