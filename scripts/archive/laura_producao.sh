#!/usr/bin/env bash
# ============================================================
# LAURA — SUBIR PARA PRODUÇÃO (versão completa, 20 fases)
# Execute: bash laura_producao.sh
# ============================================================
set -euo pipefail

ROOT="/home/shopee/agente"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Cores
G="\033[0;32m"; R="\033[0;31m"; Y="\033[1;33m"; B="\033[0;34m"; N="\033[0m"
ok()   { echo -e "${G}[OK]${N} $*"; }
err()  { echo -e "${R}[ERRO]${N} $*"; }
warn() { echo -e "${Y}[AVISO]${N} $*"; }
info() { echo -e "${B}[INFO]${N} $*"; }
step() { echo -e "\n${B}════ $* ${N}"; }

ERROS=0
falhou() { err "$*"; ERROS=$((ERROS+1)); }

# ─────────────────────────────────────────────
step "1/9 — Verificar pré-requisitos"
# ─────────────────────────────────────────────

command -v python3 >/dev/null 2>&1 || { err "python3 não encontrado"; exit 1; }
PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
python3 -c "import sys; assert sys.version_info >= (3,10)" 2>/dev/null \
  && ok "Python $PYVER" \
  || { err "Python 3.10+ necessário (atual: $PYVER)"; exit 1; }

command -v ollama >/dev/null 2>&1 && ok "Ollama instalado" \
  || warn "Ollama não encontrado — análise LLM rodará em fallback"

[ -f "$ROOT/.env" ] && ok ".env existe em $ROOT" \
  || { err ".env não encontrado em $ROOT — copie o .env.example e preencha"; exit 1; }

[ -f "$ROOT/.env" ] && [ "$(stat -c %a "$ROOT/.env")" = "600" ] \
  && ok ".env com permissão 600" \
  || { chmod 600 "$ROOT/.env"; warn ".env corrigido para 600"; }

# ─────────────────────────────────────────────
step "2/10 — Instalar dependências Python"
# ─────────────────────────────────────────────

cd "$ROOT"

PY_CMD="$ROOT/.venv/bin/python"
if [ ! -x "$PY_CMD" ]; then
  PY_CMD="python3"
fi

"$PY_CMD" -m pip install --quiet --break-system-packages \
  "requests>=2.31.0" \
  "pytest>=7.4.0" \
  "pytest-cov>=4.1.0" \
  "openpyxl>=3.1.0" \
  "reportlab>=4.0.0" \
  "anthropic>=0.25.0" 2>/dev/null \
  && ok "Dependências instaladas" \
  || warn "Falha em algumas dependências — verifique manualmente"

"$PY_CMD" -m pip install --quiet --break-system-packages -e . 2>/dev/null \
  && ok "Pacote shopee-agent instalado (modo editable)" \
  || warn "pip install -e . falhou — tente manualmente"

# ─────────────────────────────────────────────
step "3/10 — Verificar variáveis essenciais do .env"
# ─────────────────────────────────────────────

set -a; source "$ROOT/.env"; set +a

VARS_OK=1
for VAR in SHOPEE_PARTNER_ID SHOPEE_PARTNER_KEY SHOPEE_DEFAULT_SHOP_ID \
           SHOPEE_DEFAULT_ACCESS_TOKEN SHOPEE_DEFAULT_REFRESH_TOKEN; do
  if [ -n "${!VAR:-}" ]; then
    ok "$VAR configurado"
  else
    falhou "$VAR ausente no .env"
    VARS_OK=0
  fi
done

# Variáveis opcionais mas recomendadas
for VAR in LAURA_ALERT_TELEGRAM_BOT_TOKEN LAURA_ALERT_TELEGRAM_CHAT_ID; do
  [ -n "${!VAR:-}" ] && ok "$VAR configurado" \
    || warn "$VAR ausente — alertas Telegram não funcionarão"
done

# Narrador Telegram (ativar automaticamente se tokens estiverem presentes)
if [ -n "${LAURA_ALERT_TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${LAURA_ALERT_TELEGRAM_CHAT_ID:-}" ]; then
  if ! grep -q "^LAURA_TELEGRAM_NARRATOR=1" "$ROOT/.env"; then
    echo "LAURA_TELEGRAM_NARRATOR=1" >> "$ROOT/.env"
    echo "LAURA_TELEGRAM_NARRATOR_LEVEL=INFO" >> "$ROOT/.env"
    ok "Narrador Telegram ativado"
  else
    ok "Narrador Telegram já ativado"
  fi
fi

[ "$VARS_OK" = "1" ] || { err "Preencha as variáveis faltantes no .env antes de continuar"; exit 1; }

# ─────────────────────────────────────────────
step "4/10 — Criar diretórios necessários"
# ─────────────────────────────────────────────

for DIR in logs reports reports/profitability_ingest_archive backups secrets; do
  mkdir -p "$ROOT/$DIR"
  ok "Diretório: $ROOT/$DIR"
done

# ─────────────────────────────────────────────
step "5/10 — Testar conectividade com Shopee API"
# ─────────────────────────────────────────────

cd "$ROOT"
set +e
API_OUT=$(python3 -m shopee_agent.cli shop-info-default 2>&1)
API_CODE=$?
set -e

if [ $API_CODE -eq 0 ]; then
  ok "Shopee API respondendo — loja conectada"
  echo "$API_OUT" | python3 -c "
import sys, json
try:
  d = json.load(sys.stdin)
  shop = d.get('response', d)
  print(f\"  Loja: {shop.get('shop_name','?')} | Status: {shop.get('status','?')}\")
except: pass
" 2>/dev/null || true
else
  if echo "$API_OUT" | grep -qiE 'invalid_acceess_token|invalid_access_token|please have a check'; then
    info "Access token inválido detectado — tentando renovação automática"
    if "$PY_CMD" -m shopee_agent.cli token-refresh-save --env-file "$ROOT/.env" >/tmp/laura_token_refresh_auto.log 2>&1; then
      ok "Token renovado automaticamente"
      API_OUT=$(python3 -m shopee_agent.cli shop-info-default 2>&1)
      API_CODE=$?
      if [ $API_CODE -eq 0 ]; then
        ok "Shopee API respondendo — loja conectada"
        echo "$API_OUT" | python3 -c "
import sys, json
try:
  d = json.load(sys.stdin)
  shop = d.get('response', d)
  print(f\"  Loja: {shop.get('shop_name','?')} | Status: {shop.get('status','?')}\")
except: pass
" 2>/dev/null || true
      else
        falhou "Shopee API não respondeu após renovar token"
        echo "$API_OUT" | tail -5
      fi
    else
      warn "Falha na renovação automática do token"
      echo "$API_OUT" | tail -5
      warn "Verifique o token em .env ou rode: laura token-refresh-save"
    fi
  else
    falhou "Shopee API não respondeu"
    echo "$API_OUT" | tail -5
    warn "Verifique o token em .env ou rode: laura token-refresh-save"
  fi
fi

# ─────────────────────────────────────────────
step "6/10 — Verificar e iniciar Ollama"
# ─────────────────────────────────────────────

OLLAMA_OK=0
if command -v ollama >/dev/null 2>&1; then
  if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    ok "Ollama já está rodando"
    OLLAMA_OK=1
  else
    info "Iniciando Ollama em background..."
    nohup ollama serve >/dev/null 2>&1 &
    sleep 5
    if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
      ok "Ollama iniciado com sucesso"
      OLLAMA_OK=1
    else
      warn "Ollama não respondeu — análise LLM rodará em fallback"
    fi
  fi

  if [ $OLLAMA_OK -eq 1 ]; then
    MODEL="${LAURA_LLM_MODEL:-tinyllama}"
    MODELS_JSON=$(curl -sf http://127.0.0.1:11434/api/tags 2>/dev/null || echo '{"models":[]}')
    if echo "$MODELS_JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
names = [m.get('name','') for m in d.get('models',[])]
print('\n'.join(names))
" 2>/dev/null | grep -qi "$MODEL"; then
      ok "Modelo '$MODEL' disponível"
    else
      warn "Modelo '$MODEL' não encontrado — fazendo pull (pode demorar)..."
      ollama pull "$MODEL" && ok "Pull de '$MODEL' concluído" \
        || warn "Pull falhou — rode manualmente: ollama pull $MODEL"
    fi
  fi
else
  warn "Ollama não instalado — análise LLM rodará em fallback"
fi

# ─────────────────────────────────────────────
step "7/10 — Testar Narrador Telegram (opcional)"
# ─────────────────────────────────────────────

if [ -n "${LAURA_ALERT_TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${LAURA_ALERT_TELEGRAM_CHAT_ID:-}" ]; then
  info "Testando conexão Telegram..."
  if cd "$ROOT" && python3 -c "from shopee_agent.telegram_narrator import narrador; exit(0 if narrador.testar() else 1)" 2>/dev/null; then
    ok "Telegram conectado e funcionando"
  else
    warn "Telegram não responde — narração será desativada"
    sed -i 's/^LAURA_TELEGRAM_NARRATOR=1/LAURA_TELEGRAM_NARRATOR=0/' "$ROOT/.env" || true
  fi
else
  warn "Tokens Telegram não configurados — narração desativada"
fi

# ─────────────────────────────────────────────
step "8/10 — Configurar cron (health-check + autopilot + revenue ingest + stock monitor)"
# ─────────────────────────────────────────────

CRON_ATUAL=$(crontab -l 2>/dev/null || true)

adicionar_cron() {
  local JOB="$1"
  local DESC="$2"
  if echo "$CRON_ATUAL" | grep -qF "$JOB"; then
    ok "Cron já configurado: $DESC"
  else
    (echo "$CRON_ATUAL"; echo "$JOB") | crontab -
    CRON_ATUAL=$(crontab -l 2>/dev/null || true)
    ok "Cron adicionado: $DESC"
  fi
}

remover_cron() {
  local JOB="$1"
  local DESC="$2"
  if echo "$CRON_ATUAL" | grep -qF "$JOB"; then
    CRON_ATUAL="$(echo "$CRON_ATUAL" | grep -vF "$JOB" || true)"
    printf '%s\n' "$CRON_ATUAL" | crontab -
    ok "Cron removido: $DESC"
  fi
}

# Health-check na inicialização e a cada 3h
adicionar_cron "@reboot $ROOT/scripts/run_laura_healthcheck.sh >> $ROOT/logs/laura_healthcheck.log 2>&1" \
  "@reboot health-check"
adicionar_cron "0 */3 * * * $ROOT/scripts/run_laura_healthcheck.sh >> $ROOT/logs/laura_healthcheck.log 2>&1" \
  "health-check a cada 3h"

# Renovação de token diária
adicionar_cron "30 3 * * * cd $ROOT && python3 -m shopee_agent.cli token-refresh-save >> $ROOT/logs/token_refresh.log 2>&1" \
  "token refresh diário 03:30"

# Análise de lucratividade
adicionar_cron "0 4 * * * $ROOT/scripts/laura_profitability_autopilot.sh >> $ROOT/logs/laura_autopilot.log 2>&1" \
  "autopilot 04:00 diário"

# Ingestão de receita de pedidos (10:01 UTC diário)
adicionar_cron "1 10 * * * $ROOT/scripts/laura_ingest_order_revenue.sh >> $ROOT/logs/laura_ingest_revenue.log 2>&1" \
  "ingestão de receita 10:01 diário"

# Ciclo de decisão (faz o engine aprender e registrar oportunidades)
adicionar_cron "20 5 * * * cd $ROOT && source .venv/bin/activate && python3 -m shopee_agent.cli decision-cycle >> $ROOT/logs/decision_cycle.log 2>&1" \
  "decision-cycle 05:20 diário"

# Loop autônomo a cada 15 minutos
adicionar_cron "*/15 * * * * cd $ROOT && source .venv/bin/activate && python3 -m shopee_agent.cli autonomous-loop >> $ROOT/logs/laura_autonomous.log 2>&1" \
  "autonomous-loop a cada 15min"

# Polling de notificação de novos pedidos (fallback do webhook)
adicionar_cron "*/10 * * * * $ROOT/scripts/laura_orders_notify_poll.sh >> $ROOT/logs/laura_orders_notify_poll.log 2>&1" \
  "notificação de pedidos (polling) a cada 10min"

# Backfill de avaliações pendentes (não respondidas) - diário às 05:00 UTC
adicionar_cron "0 5 * * * $ROOT/scripts/laura_ratings_backfill.sh >> $ROOT/logs/laura_ratings_backfill.log 2>&1" \
  "backfill de avaliações 05:00 diário"

# Monitor de estoque (10:15 UTC diário)
adicionar_cron "15 10 * * * $ROOT/scripts/laura_inventory_monitor.sh >> $ROOT/logs/laura_inventory_monitor.log 2>&1" \
  "monitor de estoque 10:15 diário"

# Enrichment de outcomes e learning pass (Phase 35)
adicionar_cron "45 5 * * * $ROOT/scripts/run_enrich_outcomes.sh --hours 6 >> $ROOT/logs/enrich_outcomes.log 2>&1" \
  "enrichment de outcomes 05:45 diário"
adicionar_cron "0 6 * * * cd $ROOT && source .venv/bin/activate && python3 -m shopee_agent.decision_cli learn --apply-updates >> $ROOT/logs/decision_learn.log 2>&1" \
  "learning pass 06:00 diário"

# Relatório diário (usa laura_daily_report.sh)
adicionar_cron "30 4 * * * $ROOT/scripts/laura_daily_report.sh >> $ROOT/logs/laura_daily_report.log 2>&1" \
  "relatório diário 04:30"

# Watchdog a cada 15min
adicionar_cron "*/15 * * * * $ROOT/scripts/laura_watchdog.sh >> $ROOT/logs/laura_watchdog.log 2>&1" \
  "watchdog a cada 15min"

# Backup diário às 2h
adicionar_cron "0 2 * * * $ROOT/scripts/laura_backup.sh >> $ROOT/logs/laura_backup.log 2>&1" \
  "backup diário 02:00"

# Housekeeping semanal
adicionar_cron "0 1 * * 0 $ROOT/scripts/laura_housekeeping.sh >> $ROOT/logs/laura_housekeeping.log 2>&1" \
  "housekeeping dominical"

# Substituir Quick Tunnel por Tunnel permanente Cloudflare (URL fixa)
remover_cron "@reboot /home/shopee/agente/scripts/laura_webhook_tunnel_start.sh" "@reboot quick tunnel"
remover_cron "*/5 * * * * /home/shopee/agente/scripts/laura_webhook_tunnel_guard.sh" "guard quick tunnel"

adicionar_cron "@reboot $ROOT/scripts/laura_tunnel_permanent.sh ensure >> $ROOT/logs/laura_tunnel_permanent.log 2>&1" \
  "@reboot tunnel permanente Cloudflare"
adicionar_cron "*/5 * * * * $ROOT/scripts/laura_tunnel_permanent.sh ensure >> $ROOT/logs/laura_tunnel_permanent.log 2>&1" \
  "guard tunnel permanente a cada 5min"

# ─────────────────────────────────────────────
step "9/10 — Instalar serviços systemd (se disponível)"
# ─────────────────────────────────────────────

install_systemd_user_units() {
  local user_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  mkdir -p "$user_dir"

  for unit in "$ROOT/deploy/"*.service "$ROOT/deploy/"*.timer; do
    [ -f "$unit" ] || continue
    local name
    name="$(basename "$unit")"

    if [[ "$name" == *.service ]]; then
      sed -E \
        -e '/^(User|Group)=/d' \
        -e '/^(After|Wants)=network-online\.target$/d' \
        -e 's/^WantedBy=multi-user\.target$/WantedBy=default.target/' \
        "$unit" > "$user_dir/$name"
    else
      cp "$unit" "$user_dir/$name"
    fi
  done

  systemctl --user daemon-reload

  for unit in "$user_dir"/*.service "$user_dir"/*.timer; do
    [ -f "$unit" ] || continue
    systemctl --user enable --now "$(basename "$unit")" >/dev/null 2>&1 || true
  done
}

if [ -d "$ROOT/deploy" ] && command -v systemctl >/dev/null 2>&1; then
  if [ -w /etc/systemd/system ]; then
    cp "$ROOT/deploy/"*.service "$ROOT/deploy/"*.timer /etc/systemd/system/ 2>/dev/null || true
    systemctl daemon-reload

    # Enable Ollama service (LLM local)
    if [ -f "/etc/systemd/system/ollama.service" ]; then
      systemctl enable ollama.service --quiet
      systemctl start ollama.service --quiet
      ok "Systemd: ollama.service ativo"
    fi

    # Enable Laura timers
    for TIMER in laura_analysis.timer laura_reports.timer; do
      if [ -f "/etc/systemd/system/$TIMER" ]; then
        systemctl enable "$TIMER" --quiet
        systemctl start "$TIMER"
        ok "Systemd: $TIMER ativo"
      fi
    done
  elif systemctl --user show-environment >/dev/null 2>&1; then
    install_systemd_user_units
    ok "Systemd: unidades instaladas no modo usuario (sem necessidade de root)"
  else
    warn "Systemd indisponivel — usando apenas cron"
  fi
else
  warn "Systemd indisponivel — usando apenas cron"
fi

# ─────────────────────────────────────────────
step "10/10 — Testes finais de validação"
# ─────────────────────────────────────────────

cd "$ROOT"

# Teste de status geral
set +e
HEALTH_OUT=$(bash scripts/laura_status.sh 2>&1)
HEALTH_CODE=$?
set -e

if [ $HEALTH_CODE -eq 0 ]; then
  ok "laura_status.sh passou"
else
  warn "laura_status.sh retornou avisos (não crítico)"
fi

# Testes CLI essenciais + novos comandos
for CMD in "product-list --dry-run" "alerts config" "refunds stats" "doctor" "ollama-status" "ingest-order-revenue --dry-run" "inventory-monitor --dry-run" "orders-notify-poll --dry-run" "ratings-backfill --dry-run" "decision-status" "decision-cycle"; do
  set +e
  python3 -m shopee_agent.cli $CMD >/dev/null 2>&1
  CODE=$?
  set -e
  if [ $CODE -eq 0 ]; then
    ok "CLI: laura $CMD"
  else
    warn "CLI: laura $CMD retornou código $CODE (verificar manualmente)"
  fi
done

# Verificações de módulos/CLI das fases recentes
for CHECK in \
  "python3 -c 'from shopee_agent.predictive_analytics import PredictiveAnalytics; from shopee_agent.supply_chain_planner import SupplyChainPlanner; from shopee_agent.agent_orchestrator import AgentOrchestrator; from shopee_agent.strategic_planner import StrategicPlanner; print(\"ok\")'" \
  "python3 -m shopee_agent.decision_cli learn --help"; do
  set +e
  bash -lc "$CHECK" >/dev/null 2>&1
  CODE=$?
  set -e
  if [ $CODE -eq 0 ]; then
    ok "Validação: $CHECK"
  else
    warn "Validação falhou: $CHECK"
  fi
done

echo ""
echo "═══════════════════════════════════════════════════════════════"
if [ $ERROS -eq 0 ]; then
  echo -e "${G}✅ PRODUÇÃO PRONTA PARA INICIAR${N}"
  echo ""
  echo "Laura está configurada com:"
  echo "  • Análise de lucratividade: 04:00 UTC diário"
  echo "  • Ingestão de receita: 10:01 UTC diário"
  echo "  • Ciclo de decisão: 05:20 UTC diário"
  echo "  • Enrichment outcomes: 05:45 UTC diário"
  echo "  • Learning pass: 06:00 UTC diário"
  echo "  • Health-check: @reboot + a cada 3h"
  echo "  • Renovação de token: 03:30 UTC diário"
  echo "  • Relatório diário: 04:30 UTC"
  echo "  • Backfill de avaliações: 05:00 UTC diário"
  echo "  • Notificação de pedidos (polling): a cada 10min"
  echo "  • Monitor de estoque: 10:15 UTC diário"
  echo "  • Watchdog: a cada 15 minutos"
  echo "  • Backup: 02:00 UTC diário"
  echo ""
  echo "Monitorar:"
  echo "  • Logs: tail -f logs/laura_*.log"
  echo "  • Status: python3 -m shopee_agent.cli activity"
  echo "  • Ollama: python3 -m shopee_agent.cli ollama-status"
  if [ -n "${LAURA_TELEGRAM_NARRATOR:-}" ] && [ "${LAURA_TELEGRAM_NARRATOR}" = "1" ]; then
    echo "  • Telegram: Narração ativada (mensagens em tempo real)"
  fi
  echo ""
  echo -e "${G}🚀 LAURA ESTÁ PRONTA PARA PRODUÇÃO!${N}"
else
  echo -e "${R}⚠️  $ERROS erro(s) encontrado(s)${N}"
  echo "Corrija os problemas acima antes de ativar em produção."
  exit 1
fi
echo "═══════════════════════════════════════════════════════════════"

# ─────────────────────────────────────────────
echo ""
echo -e "${B}════════════════════════════════════════${N}"
if [ $ERROS -eq 0 ]; then
  echo -e "${G}✓  LAURA EM PRODUÇÃO${N}"
  echo ""
  echo "  Loja    : Viluh Shop (BR)"
  echo "  Modelo  : ${LAURA_LLM_MODEL:-mistral}"
  echo "  Cron    : health 3h | token 03:30 | decision 05:20 | enrich 05:45 | learn 06:00 | autopilot 04:00 | análise 04:30"
  echo ""
  echo "  Comandos úteis:"
  echo "    laura doctor                   # diagnóstico rápido"
  echo "    laura shop-info-default        # status da loja"
  echo "    laura llm-analyze              # análise LLM"
  echo "    bash scripts/laura_status.sh   # status completo"
  echo "    crontab -l                     # ver todos os crons"
  echo "    tail -f logs/laura_healthcheck.log"
else
  echo -e "${R}✗  LAURA COM $ERROS ERRO(S) — revise acima${N}"
  exit 1
fi
echo -e "${B}════════════════════════════════════════${N}"
