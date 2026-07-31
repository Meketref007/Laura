#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
LOG_DIR="$ROOT_DIR/logs"
REPORT_DIR="$ROOT_DIR/reports"
LOG_FILE="$LOG_DIR/laura_tunnel_permanent.log"
LOCK_FILE="$LOG_DIR/laura_tunnel_permanent.lock"
LATEST_URL_FILE="$REPORT_DIR/laura_webhook_tunnel_latest.txt"
LATEST_CALLBACK_FILE="$REPORT_DIR/laura_webhook_callback_latest.txt"

mkdir -p "$LOG_DIR" "$REPORT_DIR"
cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_DIR/.env"
  set +a
fi

CLOUDFLARED_BIN="${LAURA_CLOUDFLARED_BIN:-$ROOT_DIR/tools/cloudflared}"
TUNNEL_NAME="${LAURA_CLOUDFLARE_TUNNEL_NAME:-laura}"
HOSTNAME="${LAURA_CLOUDFLARE_HOSTNAME:-}"
CALLBACK_PATH="${LAURA_WEBHOOK_PATH:-/webhook/shopee}"
PORT="${LAURA_WEBHOOK_PORT:-8765}"
TARGET_URL="http://127.0.0.1:${PORT}"
CLOUDFLARED_HOME="${LAURA_CLOUDFLARED_HOME:-$HOME/.cloudflared}"
CONFIG_FILE="${LAURA_CLOUDFLARE_CONFIG_FILE:-$CLOUDFLARED_HOME/${TUNNEL_NAME}.yml}"
ORIGIN_CERT="${LAURA_CLOUDFLARED_ORIGIN_CERT:-$CLOUDFLARED_HOME/cert.pem}"

if [[ "$CALLBACK_PATH" != /* ]]; then
  CALLBACK_PATH="/$CALLBACK_PATH"
fi

ensure_cloudflared() {
  if [[ ! -x "$CLOUDFLARED_BIN" ]]; then
    if command -v cloudflared >/dev/null 2>&1; then
      CLOUDFLARED_BIN="$(command -v cloudflared)"
    else
      echo "[ERROR] cloudflared nao encontrado. Instale ou defina LAURA_CLOUDFLARED_BIN." >&2
      exit 1
    fi
  fi
}

ensure_origin_cert() {
  if [[ ! -f "$ORIGIN_CERT" ]]; then
    cat >&2 <<EOF
[ERROR] Nao foi encontrado cert.pem do Cloudflare.
Rode 'cloudflared tunnel login' uma vez e depois ajuste LAURA_CLOUDFLARED_ORIGIN_CERT se o arquivo ficar em outro caminho.
Esperado em: $ORIGIN_CERT
EOF
    exit 1
  fi
}

get_tunnel_id() {
  TUNNEL_ORIGIN_CERT="$ORIGIN_CERT" "$CLOUDFLARED_BIN" tunnel list --output json 2>/dev/null | python3 -c 'import json,sys
name = sys.argv[1]
try:
  data = json.load(sys.stdin)
except Exception:
  print("")
  raise SystemExit(0)
if not isinstance(data, list):
  print("")
  raise SystemExit(0)
for row in data:
  if str(row.get("name", "")).strip() == name:
    print(str(row.get("id", "")).strip())
    raise SystemExit(0)
print("")' "$TUNNEL_NAME"
}

write_config_file() {
  local tunnel_id="$1"
  local creds_file="$CLOUDFLARED_HOME/${tunnel_id}.json"
  mkdir -p "$CLOUDFLARED_HOME"

  if [[ -z "$HOSTNAME" ]]; then
    echo "[WARN] LAURA_CLOUDFLARE_HOSTNAME vazio. Defina para URL fixa (ex: webhook.seudominio.com)." >&2
  fi

  cat > "$CONFIG_FILE" <<EOF
tunnel: ${tunnel_id}
credentials-file: ${creds_file}
ingress:
  - hostname: ${HOSTNAME}
    service: ${TARGET_URL}
  - service: http_status:404
EOF
}

update_callback_files() {
  if [[ -n "$HOSTNAME" ]]; then
    local base="https://${HOSTNAME}"
    printf '%s\n' "$base" > "$LATEST_URL_FILE"
    printf '%s\n' "${base}${CALLBACK_PATH}" > "$LATEST_CALLBACK_FILE"
  fi
}

cmd_setup() {
  ensure_cloudflared
  ensure_origin_cert
  mkdir -p "$CLOUDFLARED_HOME"

  local tunnel_id
  tunnel_id="$(get_tunnel_id)"
  if [[ -z "$tunnel_id" ]]; then
    echo "[INFO] Criando tunnel permanente: $TUNNEL_NAME"
    TUNNEL_ORIGIN_CERT="$ORIGIN_CERT" "$CLOUDFLARED_BIN" tunnel create "$TUNNEL_NAME" >> "$LOG_FILE" 2>&1 || {
      echo "[ERROR] Falha ao criar tunnel. Rode 'cloudflared tunnel login' primeiro." >&2
      exit 1
    }
    tunnel_id="$(get_tunnel_id)"
  fi

  if [[ -z "$tunnel_id" ]]; then
    echo "[ERROR] Nao foi possivel obter tunnel_id para $TUNNEL_NAME" >&2
    exit 1
  fi

  write_config_file "$tunnel_id"

  if [[ -n "$HOSTNAME" ]]; then
    TUNNEL_ORIGIN_CERT="$ORIGIN_CERT" "$CLOUDFLARED_BIN" tunnel route dns "$TUNNEL_NAME" "$HOSTNAME" >> "$LOG_FILE" 2>&1 || true
  fi

  update_callback_files

  echo "[OK] Tunnel permanente configurado: name=$TUNNEL_NAME id=$tunnel_id"
  if [[ -n "$HOSTNAME" ]]; then
    echo "[OK] Callback fixa: https://${HOSTNAME}${CALLBACK_PATH}"
  fi
}

cmd_run() {
  ensure_cloudflared
  ensure_origin_cert

  if [[ ! -f "$CONFIG_FILE" ]]; then
    cmd_setup
  fi

  # Ensure local webhook is up before exposing through Cloudflare.
  if ! curl -sSf "$TARGET_URL/health" >/dev/null 2>&1; then
    nohup "$ROOT_DIR/scripts/laura_webhook_start.sh" >/dev/null 2>&1 &
    for _ in $(seq 1 10); do
      if curl -sSf "$TARGET_URL/health" >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done
  fi

  if ! curl -sSf "$TARGET_URL/health" >/dev/null 2>&1; then
    echo "[ERROR] webhook local indisponivel em $TARGET_URL" >&2
    exit 1
  fi

  update_callback_files

  {
    date -Is
    echo "[INFO] Iniciando tunnel permanente ($TUNNEL_NAME) com config=$CONFIG_FILE"
  } >> "$LOG_FILE"

  TUNNEL_ORIGIN_CERT="$ORIGIN_CERT" exec "$CLOUDFLARED_BIN" tunnel --config "$CONFIG_FILE" --no-autoupdate run
}

cmd_ensure() {
  ensure_cloudflared
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    exit 0
  fi

  if pgrep -f "cloudflared tunnel --config ${CONFIG_FILE} --no-autoupdate run" >/dev/null 2>&1; then
  nohup bash "$0" run >> "$LOG_FILE" 2>&1 &
    exit 0
  fi

  {
    date -Is
    echo "[WARN] Tunnel permanente down. Reiniciando..."
  } >> "$LOG_FILE"

  nohup "$0" run >> "$LOG_FILE" 2>&1 &
}

cmd_status() {
  if pgrep -f "cloudflared tunnel --config ${CONFIG_FILE} --no-autoupdate run" >/dev/null 2>&1; then
    echo "status=running"
  else
    echo "status=stopped"
  fi
  if [[ -f "$LATEST_CALLBACK_FILE" ]]; then
    echo "callback=$(head -n 1 "$LATEST_CALLBACK_FILE")"
  fi
}

usage() {
  cat <<EOF
Uso: $0 <setup|run|ensure|status>

Comandos:
  setup   Cria/valida tunnel permanente (cloudflared tunnel create ${TUNNEL_NAME})
  run     Executa tunnel permanente em foreground
  ensure  Garante tunnel ativo (reinicia em background se cair)
  status  Mostra status do processo e callback atual

Variaveis relevantes (.env):
  LAURA_CLOUDFLARE_TUNNEL_NAME=laura
  LAURA_CLOUDFLARE_HOSTNAME=webhook.seudominio.com
  LAURA_CLOUDFLARE_CONFIG_FILE=$CONFIG_FILE
  LAURA_CLOUDFLARED_BIN=/usr/bin/cloudflared
EOF
}

cmd="${1:-}"
case "$cmd" in
  setup) cmd_setup ;;
  run) cmd_run ;;
  ensure) cmd_ensure ;;
  status) cmd_status ;;
  *) usage; exit 1 ;;
esac
