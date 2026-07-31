# Fase 25 — Bot Telegram Interativo

**Data de conclusao:** Mai 5, 2026 12:20 UTC  
**Status:** CONCLUIDA

---

## Objetivo

Permitir controle operacional da Laura via Telegram, sem depender de terminal, mantendo custo zero.

---

## Entregaveis Implementados

1. Comando CLI novo: `laura telegram-bot`
2. Long polling no Telegram com persistencia de offset em `reports/laura_telegram_bot_offset.state`
3. Restricao opcional por chat em `LAURA_TELEGRAM_BOT_ALLOWED_CHAT_ID`
4. Comandos interativos implementados:
- `/status`
- `/pedidos` e `/pedidos N`
- `/estoque`
- `/margem`
- `/aprovar <case_id>`
5. Auditoria de aprovacao via bot em `reports/laura_remediation_audit.jsonl`

---

## Arquivos Alterados

- `shopee_agent/telegram_bot.py` (novo)
- `shopee_agent/cli.py`
- `.env.example`
- `README.md`
- `tests/test_telegram_bot.py` (novo)

---

## Comandos de Uso

```bash
# iniciar bot em modo continuo
laura telegram-bot

# modo teste (1 ciclo)
laura telegram-bot --once
```

---

## Configuracao (.env)

```bash
LAURA_ALERT_TELEGRAM_BOT_TOKEN=...
LAURA_ALERT_TELEGRAM_CHAT_ID=...
LAURA_TELEGRAM_BOT_ALLOWED_CHAT_ID=...
LAURA_TELEGRAM_BOT_POLL_TIMEOUT_SECONDS=30
LAURA_TELEGRAM_BOT_SLEEP_SECONDS=1.0
```

---

## Resultado

- Controle via Telegram entregue com comandos operacionais prioritarios
- Fluxo de aprovacao de remediacao disponivel por chat
- Solucao mantida em custo zero (Telegram Bot API gratuita)
