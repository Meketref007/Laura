#!/usr/bin/env bash

tg_narrar() {
  local tipo="${1:-info}"
  local texto="${2:-}"
  local detalhe="${3:-}"

  if [[ "${LAURA_TELEGRAM_NARRATOR:-0}" != "1" ]]; then
    return 0
  fi
  if [[ -z "${LAURA_ALERT_TELEGRAM_BOT_TOKEN:-}" || -z "${LAURA_ALERT_TELEGRAM_CHAT_ID:-}" ]]; then
    return 0
  fi

    python3 - "$tipo" "$texto" "$detalhe" <<'PY' || true
import json
import os
import sys
from datetime import datetime, timezone

import requests

tipo = sys.argv[1]
texto = sys.argv[2]
detalhe = sys.argv[3]
token = os.getenv("LAURA_ALERT_TELEGRAM_BOT_TOKEN", "").strip()
chat_id = os.getenv("LAURA_ALERT_TELEGRAM_CHAT_ID", "").strip()
if not token or not chat_id:
    raise SystemExit(0)

emoji = {
    "pensando": "🧠",
    "fazendo": "⚙️",
    "feito": "✅",
    "alerta": "⚠️",
    "decisao": "🎯",
    "critico": "🚨",
    "info": "ℹ️",
    "inicio": "🚀",
    "fim": "🏁",
    "pedido": "📦",
    "llm": "🤖",
    "webhook": "🔔",
    "backup": "💾",
    "cron": "⏰",
    "dinheiro": "💰",
}.get(tipo, "ℹ️")

msg = f"{emoji} *Laura* `{datetime.now(timezone.utc).strftime('%H:%M UTC')}`\n{texto}"
if detalhe:
    msg += f"\n{detalhe}"

try:
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        },
        timeout=8,
    )
except Exception:
    pass
PY
}


tg_enviar_resumo_autopilot() {
    # Args: 1=action_key 2=reason 3=revenue 4=margin_pct 5=orders 6=roas
    local action_key="${1:-monitor_only}"
    local reason="${2:-}"
    local revenue="${3:-0}"
    local margin_pct="${4:-0}"
    local orders="${5:-0}"
    local roas="${6:-N/A}"

    if [[ "${LAURA_TELEGRAM_NARRATOR:-0}" != "1" ]]; then
        return 0
    fi
    if [[ -z "${LAURA_ALERT_TELEGRAM_BOT_TOKEN:-}" || -z "${LAURA_ALERT_TELEGRAM_CHAT_ID:-}" ]]; then
        return 0
    fi

    python3 - <<PY || true
import os,sys
from datetime import datetime,timezone
token=os.getenv('LAURA_ALERT_TELEGRAM_BOT_TOKEN','').strip()
chat=os.getenv('LAURA_ALERT_TELEGRAM_CHAT_ID','').strip()
if not token or not chat:
        raise SystemExit(0)
action=sys.argv[1]
reason=sys.argv[2]
revenue=sys.argv[3]
margin=sys.argv[4]
orders=sys.argv[5]
roas=sys.argv[6]
msg = f"🏪 Viluh Shop · {datetime.now(timezone.utc).strftime('%H:%M UTC')}\n\nDecisão: {action}\n💭 {reason}\n\n💰 Receita: R$ {revenue}  |  📦 Pedidos: {orders}\n📈 Margem: {margin}%  |  📣 ROAS: {roas}"
import requests
try:
        requests.post(f'https://api.telegram.org/bot{token}/sendMessage', json={'chat_id': chat, 'text': msg, 'parse_mode': 'Markdown'}, timeout=8)
except Exception:
        pass
PY
}