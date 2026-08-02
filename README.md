# Laura — Agente Autônomo para Shopee

[![CI](https://github.com/Meketref007/Laura/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Meketref007/Laura/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue?logo=python)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-1327%20passing-brightgreen)]()
[![Coverage](https://img.shields.io/badge/coverage-43%25-yellow)]()
[![Docs](https://img.shields.io/badge/docs-mkdocs-blue.svg)](https://meketref007.github.io/Laura/)
[![Release](https://img.shields.io/badge/release-v3.0.0-blue.svg)](pyproject.toml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Laura é um agente de IA autônomo para vendedores Shopee.  Funciona **100% local** (sem custos de API),
integrando-se à API Shopee Open Platform, ao Seller Center via browser, e ao Telegram para notificações
e comando remoto.

| Característica | Valor |
|---|---|
| Custo operacional | **R$ 0,00/mês** (Ollama local) |
| Stack | Python 3.12, Ollama, FastAPI, Playwright |
| Modelos LLM | llama3.2:3b (padrão), DeepHat, TinyLlama, Qwen 2.5, Mistral, Llama 2 |
| APIs integradas | Shopee Open API v2, Seller Center (cookie), Telegram Bot |
| Automação | GOAP Planner, Decision Engine, Skills modulares |

---

## Sumário

- [Arquitetura](#arquitetura)
- [Instalação Rápida](#instalação-rapida)
- [Configuração](#configuração)
- [CLI — Todos os Comandos](#cli)
- [Dashboard Web](#dashboard-web)
- [Extensão para Navegador](#extensão-navegador)
- [Funcionalidades](#funcionalidades)
- [Exemplos de Uso](#exemplos-de-uso)
- [Docker](#docker)
- [Testes](#testes)
- [Variáveis de Ambiente](#variáveis-de-ambiente)
- [APIs REST](#apis-rest)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)

---

## Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                    Interface / CLI                           │
│  laura shell | laura daemon | laura skill-run | dashboard   │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                Orquestração Central                          │
│  AutonomousLoop · DecisionIntegrator · SkillOrchestrator     │
│  GOAPPlanner · StrategicPlanner · AgentOrchestrator         │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│              Decisão & Planejamento                          │
│  DecisionEngine · PriorityEngine · GoalManager              │
│  Planner · GOAP (A*) · EconomicBrain                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│              Execução (Skills + API)                         │
│  DecisionExecutor · SkillRegistry · Sandbox                 │
│  ShopeeClient · TelegramBot · WebhookServer                 │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│              Infra-estrutura                                 │
│  EventBus (async) · CircuitBreaker · SelfHealing             │
│  WAL Journal · DLQ · GracefulShutdown                       │
└─────────────────────────────────────────────────────────────┘
```

### Camadas

1. **CLI / Interface** — `laura` com 140+ subcomandos, shell interativo, dashboard web
2. **Orquestração** — `AutonomousLoop` coordena ciclo contínuo; `SkillOrchestrator` gerencia skills
3. **Decisão** — `DecisionEngine` com regras adaptativas, `GOAPPlanner` (A*) para planejamento
4. **Execução** — Skills modulares (preço, estoque, chat, etc.), `ShopeeClient` para API, sandbox
5. **Infra** — EventBus assíncrono, circuit breakers, self-healing, graceful shutdown

### Ciclo do Daemon

```
[Setup] → [Auto-login thread] → [LLM thread] → loop:
  ├─ _cycle() → AutonomousLoop.run_cycle()
  │   ├─ DecisionEngine avalia regras
  │   ├─ Skills executam ações
  │   ├─ GOAP planeja próximos passos
  │   └─ Resultados → EventBus → Telegram
  ├─ health_check() a cada 30 min
  └─ dorme CYCLE_INTERVAL (padrão 5 min)
```

---

## Instalação Rápida

### Linux / WSL

```bash
git clone <repo>
cd laura/agente
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -e ".[dev]"   # desenvolvimento
```

### Windows

```powershell
git clone <repo>
cd laura/agente
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
pip install -e ".[dev]"
```

### Seller Center + Playwright (opcional)

```bash
playwright install chromium
```

Para auto-login via CDP, execute Brave/Chrome com:
```bash
brave --remote-debugging-port=9222 &
```

---

## Configuração

Crie um arquivo `.env` na raiz do projeto:

```bash
cp .env.example .env
```

### Mínimo obrigatório

```env
SHOPEE_PARTNER_ID=seu_partner_id
SHOPEE_PARTNER_KEY=sua_chave_parceiro
SHOPEE_REDIRECT_URL=http://localhost:8080/callback
```

### Tokens padrão (após autorização OAuth)

```env
SHOPEE_DEFAULT_SHOP_ID=123456789
SHOPEE_DEFAULT_ACCESS_TOKEN=seu_access_token
SHOPEE_DEFAULT_REFRESH_TOKEN=seu_refresh_token
```

### Telegram (para notificações e comandos remotos)

```env
LAURA_ALERT_TELEGRAM_BOT_TOKEN=1234567890:AA...
LAURA_ALERT_TELEGRAM_CHAT_ID=123456789
LAURA_TELEGRAM_NARRATOR=1
LAURA_TELEGRAM_BOT_ALLOWED_CHAT_ID=123456789
```

### Fluxo de autorização OAuth

```bash
laura auth-url                # 1. Gera URL de autorização
laura token-get --code <CODE> --shop-id <ID>   # 2. Troca code por token
laura token-refresh-save      # 3. Renova e salva no .env
laura health-check            # 4. Valida tudo
```

---

## CLI

Todos os comandos usam `laura <comando> [args]`.  Mais de 140 comandos organizados
por categoria.

### Autenticação & Setup

| Comando | Descrição |
|---|---|
| `laura setup` | Wizard interativo de primeira configuração |
| `laura setup --quick` | Setup automático via env vars |
| `laura setup --check` | Verifica pré-requisitos |
| `laura auth-url` | Gera URL de autorização OAuth |
| `laura token-get` | Troca code por access_token |
| `laura token-refresh` | Renova token manualmente |
| `laura token-refresh-save` | Renova e salva no .env automaticamente |
| `laura shop-info` | Info da loja por token explícito |
| `laura shop-info-default` | Info usando tokens do .env |
| `laura doctor` | Diagnóstico rápido do ambiente |
| `laura health-check` | Valida tokens + conectividade |

### API Gateway

| Comando | Descrição |
|---|---|
| `laura api-call` | Chama qualquer endpoint Shopee com assinatura |
| `laura api-endpoints` | Lista endpoints catalogados |
| `laura api-families` | Lista famílias de API |
| `laura api-serve` | Sobe API FastAPI central |

### Produtos

| Comando | Descrição |
|---|---|
| `laura product-list` | Lista produtos |
| `laura product-item-detail` | Detalhe completo do produto |
| `laura product-item-base-info` | Informações básicas |
| `laura product-item-variations` | Variações/SKUs |

### Pedidos

| Comando | Descrição |
|---|---|
| `laura order-list` | Lista pedidos |
| `laura order-detail` | Detalhe do pedido |
| `laura order-ship` | Marca pedido como enviado |
| `laura refunds list` | Lista reembolsos |
| `laura refunds approve` | Aprova reembolso |
| `laura refunds reject` | Rejeita reembolso |
| `laura refunds auto-evaluate` | Avaliação automática |

### Logística

| Comando | Descrição |
|---|---|
| `laura logistics-channel-list` | Canais logísticos |
| `laura logistics-info` | Info logística do pedido |
| `laura logistics-tracking-number` | Código de rastreio |

### Financeiro

| Comando | Descrição |
|---|---|
| `laura payment-escrow-detail` | Detalhe financeiro do pedido |
| `laura economic-brain-summary` | Resumo financeiro + forecast |

### Promoções

| Comando | Descrição |
|---|---|
| `laura discount-list` | Campanhas de desconto |
| `laura voucher-list` | Vouchers |
| `laura bundle-deal-list` | Bundle deals |
| `laura add-on-deal-list` | Add-on deals |
| `laura flash-sale-recommend` | Sugestão de flash sales |
| `laura flash-sale-exec` | Executa flash sales |
| `laura campaign list` | Campanhas ativas |
| `laura campaign bundle` | Cria bundle deal |
| `laura campaign voucher` | Cria voucher |
| `laura campaign auto` | Sugestão automática |

### Mídia

| Comando | Descrição |
|---|---|
| `laura media-video-init-upload` | Inicia upload de vídeo |
| `laura media-video-upload-part` | Envia parte do vídeo |
| `laura media-video-complete-upload` | Finaliza upload |
| `laura media-video-upload-result` | Resultado do upload |
| `laura media-video-wait-completion` | Aguarda processamento |
| `laura vision` | Análise de imagens |
| `laura visual-analysis` | Análise visual com IA |

### LLM Local (Ollama)

| Comando | Descrição |
|---|---|
| `laura llm-prompts` | Lista system prompts |
| `laura llm-analyze` | Análise de rentabilidade |
| `laura ollama-status` | Status do Ollama |
| `laura ollama-fix` | Diagnostica e repara Ollama |

### Automação & Agente

| Comando | Descrição |
|---|---|
| `laura daemon` | Inicia daemon em loop contínuo |
| `laura start` | Inicia Laura completa |
| `laura autonomous-loop` | Executa um ciclo autônomo |
| `laura activity` | Atividade recente |
| `laura shell` | Shell interativo com auto-complete |
| `laura skill-list` | Skills registradas |
| `laura skill-run` | Invoca skill pelo nome |
| `laura skill-register` | Registra skill manualmente |
| `laura skill-test` | Testa skill em sandbox |
| `laura skill-create` | Cria scaffolding de skill |
| `laura skill-generate` | Gera skill de descrição NL |
| `laura skill-goap-plan` | Testa GOAP manualmente |
| `laura skill-goap-explain` | Explica ações do plano |
| `laura skill-history` | Histórico de execução |
| `laura skill-reload` | Hot-reload de skills |
| `laura skill-profile` | Profile de recursos |
| `laura skill-anomaly` | Detecta anomalias |
| `laura skill-version` | Gerencia versões |
| `laura skill-market` | Marketplace de skills |
| `laura skill-approve` | Aprova skill de alto risco |
| `laura skill-reject` | Rejeita skill |
| `laura skill-approval-list` | Aprovações pendentes |
| `laura skill-rollback-learning` | Rollback aprendizado |
| `laura learning-stats` | Estatísticas de aprendizado |
| `laura skill-simulate` | What-if simulation |
| `laura ab-test-start` | Inicia teste A/B |
| `laura ab-test-status` | Status dos testes A/B |
| `laura ab-auto-promote` | Auto-promoção com significância |
| `laura canary-start` | Inicia canary deploy |
| `laura canary-status` | Status dos canaries |
| `laura canary-promote` | Promove canary |
| `laura canary-rollback` | Rollback de canary |

### Planejamento GOAP

| Comando | Descrição |
|---|---|
| `laura goal-synthesize` | Infere goal de KPIs |
| `laura goal-nl` | Traduz linguagem natural para goal |
| `laura goal-library` | Gerencia biblioteca de metas |
| `laura plan-viz` | Diagrama Mermaid do plano |
| `laura plan-diff` | Compara dois planos |
| `laura plan-export` | Exporta plano como JSON |
| `laura plan-import` | Importa plano de JSON |
| `laura plan-batch` | Executa múltiplos planos |
| `laura plan-schedule` | Agenda execução de planos |
| `laura plan-optimize` | Sugere otimizações |
| `laura plan-store` | Gerencia planos persistidos |
| `laura plan-heal` | Executa com auto-repair |
| `laura plan-explain` | Explica plano em português |
| `laura plan-conform` | Verifica conformidade |
| `laura plan-template` | Templates de planos |
| `laura planners-alerts` | Alertas do planner |
| `laura proactive-goals` | Metas proativas |
| `laura cost-predict` | Prevê custo do plano |
| `laura multi-approve` | Workflow multi-aprovador |

### Decision Engine

| Comando | Descrição |
|---|---|
| `laura decision-status` | Decisões pendentes |
| `laura decision-history` | Histórico de decisões |
| `laura decision-detail` | Detalhes da decisão |
| `laura decision-cycle` | Ciclo completo de avaliação |
| `laura decision-metrics` | Métricas de qualidade |
| `laura decision-outcomes` | Outcomes registrados |
| `laura decision-learn` | Aprende com outcomes |
| `laura decision-effectiveness` | Effectiveness scores |
| `laura decision-similar` | Busca decisões similares |
| `laura decision-reindex-backend` | Reindexa memória vetorial |

### Metas (Goal Management)

| Comando | Descrição |
|---|---|
| `laura goal-summary` | Resumo e ranking de metas |
| `laura goal-list` | Lista metas |
| `laura goal-add` | Registra nova meta |
| `laura goal-top` | Meta com maior prioridade |
| `laura goal-complete` | Marca meta concluída |

### Análises & Relatórios

| Comando | Descrição |
|---|---|
| `laura analytics-trends` | Tendências e anomalias |
| `laura anomaly-detect` | Detecta anomalias |
| `laura predict-refunds` | Previsão de devoluções |
| `laura charts` | Gráficos interativos (Chart.js) |
| `laura chart-dashboard` | Dashboard visual completo |
| `laura performance-report` | Relatório de performance |
| `laura export-report` | Exporta relatório (JSON/CSV/PDF/Excel) |
| `laura schedule-report` | Agenda relatórios |
| `laura realtime-config` | Configura atualizações WebSocket |
| `laura insights-trend` | Tendência com explicação IA |
| `laura insights-anomaly` | Explica anomalias com IA |
| `laura insights-recommendations` | Recomendações inteligentes |
| `laura insights-summary` | Resumo executivo com IA |
| `laura competitive-intel-summary` | Inteligência competitiva |
| `laura branding-growth-summary` | Branding e growth |
| `laura dashboard-cli` | Dashboard estático |

### Webhook

| Comando | Descrição |
|---|---|
| `laura webhook-start` | Inicia servidor webhook |
| `laura webhook-drain` | Drena fila do webhook |

### Seller Center

| Comando | Descrição |
|---|---|
| `laura sc products` | Lista produtos via Seller Center |
| `laura sc product <id>` | Detalhe do produto |
| `laura sc orders` | Lista pedidos |
| `laura sc ship <sn>` | Envia pedido |
| `laura sc pending` | Envios pendentes |
| `laura sc balance` | Saldo da conta |
| `laura sc campaigns` | Campanhas ativas |
| `laura sc perf` | Performance da loja |
| `laura sc violations` | Violações de listing |
| `laura sc bulk-price` | Atualiza preços em lote |
| `laura sc bulk-stock` | Atualiza estoque em lote |
| `laura sc export` | Exporta produtos para CSV |

### Chat & Comunicação

| Comando | Descrição |
|---|---|
| `laura chat list` | Lista conversas |
| `laura chat auto-reply` | Configura auto-resposta |
| `laura chat send` | Envia mensagem |
| `laura chat history` | Histórico do chat |
| `laura telegram-bot` | Inicia bot Telegram interativo |
| `laura cross-sell recommend` | Recomendação de cross-sell |
| `laura cross-sell top-pairs` | Pares mais vendidos |
| `laura cross-sell bundle` | Recomenda para carrinho |

### Infraestrutura

| Comando | Descrição |
|---|---|
| `laura queue status` | Status do EventBus |
| `laura queue dlq` | Dead-letter queue |
| `laura queue retry` | Reenfileira DLQ |
| `laura metrics-export` | Métricas Prometheus |
| `laura metrics-dashboard` | Dashboard de métricas |
| `laura trace` | Tracing distribuído |
| `laura agent-orchestration` | Orquestração multi-agente |
| `laura strategic-plan` | Strategic Planner |
| `laura browser-run` | Automação via browser |
| `laura supply-chain` | Supply chain v2 |
| `laura federated` | Aprendizado federado |
| `laura federated-v2` | Federated learning v2 |
| `laura tenant` | Multi-tenant management |
| `laura sandbox-test` | Testa sandbox Shopee |
| `laura benchmark` | Benchmarks de performance |
| `laura completion` | Auto-complete para shell |

### Sistema & Manutenção

| Comando | Descrição |
|---|---|
| `laura store-list` | Lojas registradas |
| `laura store-init` | Inicializa loja |
| `laura store-summary` | Resumo da loja |
| `laura workers list` | Lista workers |
| `laura workers status` | Status do worker |
| `laura workers pause` | Pausa worker |
| `laura workers resume` | Retoma worker |
| `laura workers stats` | Estatísticas da fila |
| `laura export` | Exporta dados |
| `laura cleanup` | Limpeza de dados |
| `laura health` | Verificação de saúde |
| `laura dashboard` | Dashboard web |

---

## Onboarding Wizard

Na primeira execução, Laura oferece um assistente interativo:

```bash
laura setup
```

O wizard guia por:
1. Verificação de pré-requisitos (Python, Ollama, espaço em disco)
2. Configuração da Shopee (Partner ID, Key, Token, Shop ID)
3. Escolha do provedor LLM (Ollama local, ChatGPT ou Claude)
4. Configuração opcional do Telegram
5. Configuração do Dashboard (porta, API key)
6. Teste de conexão com a Shopee
7. Geração automática do arquivo `.env`

Use `laura setup --quick` para configurar via variáveis de ambiente já existentes,
ou `laura setup --check` para apenas verificar o ambiente.

---

## Dashboard Web

```bash
laura dashboard                      # http://127.0.0.1:8888
laura dashboard --port 8080          # Porta customizada
laura dashboard --build-frontend     # Compila frontend antes
```

### Endpoints do Dashboard

| Rota | Descrição |
|---|---|
| `/` | Página principal |
| `/api/health` | Health check |
| `/api/status` | Status consolidado |
| `/api/dashboard/metrics` | Métricas da loja |
| `/api/dashboard/recent-events` | Eventos recentes |
| `/api/profitability` | Rentabilidade |
| `/api/skills` | Skills registradas |
| `/api/skill-health` | Saúde das skills |
| `/api/goap-graph` | Grafo GOAP |
| `/api/goap-timeline` | Timeline do plano |
| `/api/goap-cost-history` | Histórico de custos |
| `/api/goal-synthesize` | Síntese de metas |
| `/api/ab-tests` | Testes A/B |
| `/api/ab-tests/stats` | Estatísticas A/B |
| `/api/approve/rating/{idx}` | Aprova resposta |
| `/api/reject/rating/{idx}` | Rejeita resposta |
| `/api/approve/chat/{idx}` | Aprova chat |
| `/api/reject/chat/{idx}` | Rejeita chat |
| `/api/push/subscribe` | Inscrição PWA |
| `/api/push/send` | Envio de push |
| `/api/ws-token` | Token WebSocket |
| `/ws/stream` | WebSocket streaming |
| `/metrics` | Métricas Prometheus |
| `/summary` | Resumo executivo |
| `/ab-testing` | Painel A/B |
| `/goap` | Visualização GOAP |
| `/skill-health` | Saúde das skills |

---

## Funcionalidades

| Funcionalidade | Descrição |
|---|---|
| 🤖 **AutonomousLoop** | Ciclo contínuo de coleta, análise e execução |
| 🧠 **LLM Local (Ollama)** | Análise de rentabilidade, sentimento, insights |
| 🎯 **GOAP Planner** | Planejamento automático com A* |
| ⚙️ **Decision Engine** | Regras adaptativas com aprendizado por reforço |
| 📦 **Skills Modulares** | Plugins independentes para cada funcionalidade |
| 🔄 **EventBus** | Barramento de eventos assíncrono com WAL e DLQ |
| 🛡️ **Circuit Breaker** | Proteção contra falhas em cascata |
| 🔧 **Self-Healing** | Auto-recuperação de componentes com falha |
| 📊 **Dashboard** | Interface web com métricas, gráficos e aprovações |
| 📱 **Telegram Bot** | Comandos remotos pelo celular |
| 🔔 **Telegram Narrator** | Notificações operacionais em tempo real |
| 💬 **Chat Automático** | Atendimento ao cliente automatizado |
| 💰 **Profitability Autopilot** | Gestão automática de rentabilidade |
| 📈 **Predictive Analytics** | Previsão de vendas com 30 dias de horizonte |
| 🏪 **Competitive Intelligence** | Monitoramento de preços da concorrência |
| ⚡ **Flash Sale Recommender** | Sugestão automática de promoções relâmpago |
| 🚚 **Supply Chain Planner** | Gestão de estoque e fornecedores |
| 🔄 **Federated Learning** | Aprendizado colaborativo entre lojas |
| 🧪 **A/B Testing** | Testes controlados entre versões de skills |
| 🐦 **Canary Deploy** | Rollout gradual de novas skills |
| 🔐 **Multi-Step Approval** | Workflow de aprovação para ações de alto risco |
| 💾 **Backup Automático** | Backup de configurações e estado |
| 📋 **Relatório Semanal** | PDF com performance da loja |
| 📊 **Exportação Multi-formato** | JSON, CSV, PDF, Excel |

---

## Exemplos de Uso

### Operação Diária

```bash
# Verificar saúde do sistema
laura doctor
laura health-check

# Pedidos pendentes
laura order-list --order-status READY_TO_SHIP
laura sc pending

# Rentabilidade
laura llm-analyze
laura economic-brain-summary

# Concorrência
laura competitive-intel-summary
```

### Automação com Daemon

```bash
# Iniciar daemon (loop contínuo)
laura daemon

# Ver atividade recente
laura activity --limit 20

# Aprovar ações pendentes
laura decision-status --priority critical
laura skill-approval-list
```

### Planejamento com GOAP

```bash
# Sintetizar meta a partir de KPIs
laura goal-synthesize --margin-pct 18 --low-stock 3

# Planejar ações
laura skill-goap-plan \
  --current-state '{"margin_protected":false,"stock_checked":false}' \
  --goal-state '{"margin_protected":true,"stock_checked":true}'

# Visualizar plano
laura plan-viz --format gantt --output plano.md
```

### Webhook

```bash
# Iniciar servidor webhook
laura webhook-start \
  --host 127.0.0.1 --port 8766 \
  --secret-key "$LAURA_WEBHOOK_SECRET"

# Verificar readiness
./scripts/laura_webhook_shopee_ready.sh
```

### Skills

```bash
# Listar skills disponíveis
laura skill-list

# Executar skill específica
laura skill-run inventory_skill

# Criar nova skill
laura skill-create monitor_preco \
  --preconditions '{"preco_verificado":false}' \
  --effects '{"concorrente_verificado":true}'
```

### Testes A/B e Canary

```bash
# Iniciar teste A/B
laura ab-test-start pricing_skill \
  shopee_agent.skills.pricing_skill_v1 PricingSkillV1 \
  shopee_agent.skills.pricing_skill_v2 PricingSkillV2

# Canary deploy
laura canary-start pricing_skill \
  shopee_agent.skills.pricing_skill_v3 PricingSkillV3 \
  --initial-pct 10

# Auto-promover se significativo
laura ab-auto-promote --test-id pricing_skill
```

---

## Docker

```bash
# Inicia Laura + Ollama (build e sobe em background)
make up

# Parar / logs / status
make down
make logs
make ps

# Atualizar modelos Ollama dentro do stack
make pull
```

O Compose inicia:
- Laura com daemon, webhook (:8766) e dashboard (:8888)
- Ollama com o modelo definido em `LAURA_LLM_MODEL` (padrão `llama3.2:3b`)
- Redis (opcional — `docker compose --profile redis up -d`)

Variáveis principais no `.env` (lidas automaticamente pelo Compose):
`SHOPEE_PARTNER_ID`, `SHOPEE_PARTNER_KEY_SHA256`, `SHOPEE_DEFAULT_ACCESS_TOKEN`,
`SHOPEE_DEFAULT_SHOP_ID`, `LAURA_ALERT_TELEGRAM_BOT_TOKEN`, `LAURA_ALERT_TELEGRAM_CHAT_ID`,
`LAURA_LLM_MODEL`, `LAURA_CEO_MODE`, `DASHBOARD_API_KEY`.

---

## Modo CEO (autonomia total)

Por padrão, toda ação executada por Laura exige **aprovação humana** (via Telegram,
dashboard ou CLI). Com `LAURA_CEO_MODE=1` no `.env`, Laura opera de forma autônoma:

- **Auto-aprova decisões** geradas pelo decision engine (todas as prioridades)
- **Executa skills de alta prioridade** (HIGH/CRITICAL) sem intervenção
- **Envia pedidos prontos** automaticamente (equivalente a `/enviar_<order_sn>`)
- **Responde chat de compradores** sem aprovação manual (chat_auto)

```bash
# .env
LAURA_CEO_MODE=1
```

Cada ação executada continua registrada em `reports/pending_decisions_*.jsonl`
e é notificada no Telegram com o prefixo *CEO Mode*. Apenas decisões com
risco baixo (`risk_score <= 0.6`) e confiança alta (`confidence >= 0.6`) são
auto-aprovadas; as demais continuam exigindo aprovação humana.

**Atenção:** com CEO mode ativo, `SELLER_CENTER_DRY_RUN` é desconsiderado —
ações do Seller Center (perfil, envio, etc.) são executadas de verdade.

---

## Testes

```bash
# Todos os testes
make test
# ou
python -m pytest tests/ -v

# Com cobertura
python -m pytest tests/ --cov=shopee_agent

# Faiss tests
make test-faiss

# Lint
make lint        # ruff
make typecheck   # mypy
```

---

## Variáveis de Ambiente

### Shopee Open API

| Variável | Obrigatória | Padrão | Descrição |
|---|---|---|---|
| `SHOPEE_PARTNER_ID` | Sim | — | Partner ID do app Shopee |
| `SHOPEE_PARTNER_KEY` | Sim | — | Partner Key (chave privada) |
| `SHOPEE_BASE_URL` | Não | `https://partner.shopeemobile.com` | Base URL da API |
| `SHOPEE_REDIRECT_URL` | Sim | — | URL de redirect OAuth |
| `SHOPEE_DEFAULT_SHOP_ID` | Não | — | Shop ID padrão |
| `SHOPEE_DEFAULT_ACCESS_TOKEN` | Não | — | Access token padrão |
| `SHOPEE_DEFAULT_REFRESH_TOKEN` | Não | — | Refresh token padrão |

### Webhook

| Variável | Padrão | Descrição |
|---|---|---|
| `LAURA_WEBHOOK_HOST` | `127.0.0.1` | Host do webhook |
| `LAURA_WEBHOOK_PORT` | `8765` | Porta do webhook |
| `LAURA_WEBHOOK_PATH` | `/webhook/shopee` | Path do callback |
| `LAURA_WEBHOOK_PUBLIC_BASE_URL` | — | URL pública HTTPS |
| `LAURA_WEBHOOK_SECRET` | — | Live Push Partner Key |
| `LAURA_WEBHOOK_ALLOW_UNVERIFIED_ACK` | `0` | Aceita verify sem assinatura |
| `LAURA_WEBHOOK_READY_TIMEOUT_SECONDS` | `10` | Timeout readiness check |
| `LAURA_WEBHOOK_READY_MAX_LATENCY_SECONDS` | `3` | Latência máxima |
| `LAURA_WEBHOOK_READY_RETRY_ATTEMPTS` | `2` | Tentativas de retry |
| `LAURA_WEBHOOK_READY_GUARD_ENABLED` | `1` | Guardião de readiness |
| `LAURA_WEBHOOK_READY_ALERT_STREAK` | `2` | Streak para alerta |
| `LAURA_WEBHOOK_READY_AUTO_HEAL` | `1` | Auto-recuperação |
| `LAURA_WEBHOOK_READY_AUDIT_ENABLED` | `1` | Auditoria |
| `LAURA_WEBHOOK_READY_DIGEST_ENABLED` | `1` | Digest diário |

### LLM / Ollama

| Variável | Padrão | Descrição |
|---|---|---|
| `LAURA_LLM_MODEL` | `llama3.2:3b` | Modelo Ollama |
| `LAURA_VISION_MODEL` | `moondream` | Modelo de visão (imagens) |
| `LAURA_OLLAMA_HOST` | `127.0.0.1` | Host do Ollama |
| `LAURA_OLLAMA_PORT` | `11434` | Porta do Ollama |
| `LAURA_CEO_MODE` | `0` | `1` = Modo CEO: autonomia total (auto-aprova decisões, executa skills de alta prioridade e envia pedidos prontos sem aprovação humana) |
| `LAURA_LLM_ENABLED` | `1` | Habilita LLM local |
| `LAURA_LLM_REQUEST_TIMEOUT_SECONDS` | `30` | Timeout das requisições |
| `LAURA_ALLOW_PAID_LLM` | `0` | Bloqueia APIs pagas |

### Telegram

| Variável | Descrição |
|---|---|
| `LAURA_ALERT_TELEGRAM_BOT_TOKEN` | Token do bot para alertas |
| `LAURA_ALERT_TELEGRAM_CHAT_ID` | Chat ID para alertas |
| `LAURA_TELEGRAM_LIVE_NOTIFICATIONS` | Notificações em tempo real |
| `LAURA_TELEGRAM_NOTIFY_LEVEL` | Nível mínimo (`INFO`, `WARNING`, `ERROR`) |
| `LAURA_TELEGRAM_NARRATOR` | Narrador de milestones |
| `LAURA_TELEGRAM_NARRATOR_LEVEL` | Nível do narrador |
| `LAURA_TELEGRAM_BOT_ALLOWED_CHAT_ID` | Restringe comandos a um chat |
| `LAURA_TELEGRAM_BOT_POLL_TIMEOUT_SECONDS` | Timeout do long polling (30) |
| `LAURA_TELEGRAM_BOT_SLEEP_SECONDS` | Sleep entre ciclos (1.0) |

### Daemon

| Variável | Padrão | Descrição |
|---|---|---|
| `VILU_DAEMON_INTERVAL` | `300` | Intervalo do ciclo (segundos) |
| `VILU_BACKUP_INTERVAL` | `86400` | Intervalo de backup (24h) |
| `LAURA_AUTO_LOGIN_INTERVAL` | `21600` | Intervalo auto-login (6h) |
| `PRICING_CYCLE_INTERVAL` | `5` | Ciclos entre análises de preço |

### Autenticação / Seller Center

| Variável | Descrição |
|---|---|
| `GMAIL_CREDENTIALS_FILE` | Caminho para credentials.json do Gmail |
| `GMAIL_TOKEN_FILE` | Caminho para token.json do Gmail |
| `SELLER_CENTER_CREDENTIALS_FILE` | Credenciais do Seller Center |
| `SELLER_CENTER_COOKIES_FILE` | Cookies persistentes |
| `CDP_WS_URL` | WebSocket do Chrome DevTools Protocol |

### Profitability Autopilot

| Variável | Padrão | Descrição |
|---|---|---|
| `LAURA_PROFITABILITY_ENABLED` | `1` | Habilita autopilot |
| `LAURA_PROFITABILITY_EXECUTE_ENABLED` | `0` | Habilita execução real |
| `LAURA_PROFITABILITY_COOLDOWN_MINUTES` | `120` | Cooldown entre ações |
| `LAURA_PROFITABILITY_MIN_MARGIN_PCT` | `12` | Margem mínima segura |
| `LAURA_PROFITABILITY_MAX_REFUND_RATE_PCT` | `6` | Taxa de reembolso máxima |
| `LAURA_PROFITABILITY_MIN_ROAS` | `3` | ROAS mínimo |
| `LAURA_PROFITABILITY_MIN_ORDERS_FOR_SCALE` | `20` | Pedidos mínimos para scaling |
| `LAURA_PROFITABILITY_EXEC_KILL_SWITCH` | `1` | Kill switch de execução |
| `LAURA_PROFITABILITY_EXEC_ALLOWED_ACTIONS` | `scale_winners` | Ações permitidas |

### Métricas & Auditoria

| Variável | Padrão | Descrição |
|---|---|---|
| `LAURA_METRICS_RETENTION_DAYS` | `30` | Retenção de métricas |
| `LAURA_METRICS_DIGEST_ENABLED` | `1` | Digest diário |
| `LAURA_METRICS_DIGEST_WINDOW_HOURS` | `24` | Janela do digest |
| `LAURA_METRICS_SCORE_WEIGHT_API` | `25` | Peso API no health score |
| `LAURA_METRICS_SCORE_WEIGHT_CRON` | `25` | Peso Cron no health score |
| `LAURA_METRICS_SCORE_WEIGHT_BACKUP` | `25` | Peso Backup no health score |
| `LAURA_METRICS_SCORE_WEIGHT_FULL` | `25` | Peso Full no health score |
| `LAURA_METRICS_GUARD_WINDOW_HOURS` | `24` | Janela do guardião |
| `LAURA_METRICS_GUARD_MIN_SUCCESS_PCT` | `90` | % sucesso mínimo |
| `LAURA_METRICS_GUARD_MIN_SAMPLES` | `6` | Amostras mínimas |
| `LAURA_METRICS_AUTO_REMEDIATE_ENABLED` | `0` | Auto-remediação |
| `LAURA_METRICS_WEEKLY_REPORT_ENABLED` | `1` | Relatório semanal |
| `LAURA_METRICS_AUDIT_RETENTION_DAYS` | `30` | Retenção da auditoria |

### Health Check & Segurança

| Variável | Padrão | Descrição |
|---|---|---|
| `LAURA_HEALTHCHECK_MAX_LOG_BYTES` | `5242880` | Tamanho máximo do log (5MB) |
| `LAURA_HEALTHCHECK_MAX_LOG_BACKUPS` | `1` | Backups do log |
| `LAURA_HEALTHCHECK_MAX_BACKUP_AGE_DAYS` | `7` | Idade máxima dos backups |
| `LAURA_SUCCESS_GUARD_MAX_AGE_SECONDS` | `14400` | Idade máxima do último sucesso |
| `LAURA_WATCHDOG_MAX_AGE_SECONDS` | `14400` | Idade máxima watchdog |
| `LAURA_CRON_GUARD_AUTO_HEAL` | `1` | Auto-correção de cron |
| `LAURA_SECURITY_GUARD_NOTIFY_ON_FIX` | `1` | Notifica correção de permissão |
| `LAURA_SECURITY_REMINDER_ENABLED` | `1` | Lembrete mensal de segurança |

### Backup & Retenção

| Variável | Padrão | Descrição |
|---|---|---|
| `LAURA_BACKUP_RETENTION_DAYS` | `14` | Retenção de backups |
| `LAURA_VERIFY_BACKUP_MAX_AGE_HOURS` | `48` | Idade máxima para verificação |
| `LAURA_RESTORE_DRILL_MAX_AGE_HOURS` | `72` | Idade máxima para drill |
| `LAURA_ENV_SNAPSHOT_RETENTION_DAYS` | `30` | Retenção de snapshots .env |
| `LAURA_REPORT_RETENTION_DAYS` | `14` | Retenção de relatórios |

---

## APIs REST

### API Central (FastAPI)

Iniciar:
```bash
laura api-serve --host 127.0.0.1 --port 8000
```

Documentação automática em `/docs` (Swagger) e `/redoc`.

### Webhook Server

Iniciar:
```bash
laura webhook-start --host 127.0.0.1 --port 8766
```

Endpoints:

| Rota | Descrição |
|---|---|
| `/health` | Health check |
| `/webhook/shopee` | Callback Shopee Set Push |
| `/webhook/mediaspace` | Callback MediaSpace |

### Dashboard API (versionada)

O dashboard web (porta 8888) expõe dezenas de endpoints REST + WebSocket
com versionamento via `/api/v1/` e `/api/v2/`.

| Rota | Descrição |
|---|---|
| `GET /api/version` | Versões disponíveis |
| `GET /api/v1/version` | Detalhes da versão v1 |
| `GET /api/v2/version` | Detalhes da versão v2 |
| `GET /api/v1/status` | Status do sistema (v1) |
| `GET /api/v2/health` | Health check completo (v2) |

Endpoints legados em `/api/*` são redirecionados automaticamente para `/api/v1/*`
com header `X-API-Deprecated: true`.

Veja [Dashboard Web](#dashboard-web) para a lista completa.

---

## Troubleshooting

### "Ollama não está respondendo"

```bash
# Verificar status
laura ollama-status

# Diagnóstico e reparo automático
laura ollama-fix

# Manual: iniciar Ollama
ollama serve

# Verificar modelo
ollama list
ollama run llama3.2:3b
```

### "Erro de assinatura Shopee"

```bash
# Verificar partner_key
laura doctor

# Re-autorizar
laura auth-url
laura token-get --code <CODE> --shop-id <ID>
laura health-check
```

### "Webhook não recebe notificações"

```bash
# Testar readiness
./scripts/laura_webhook_shopee_ready.sh

# Verificar diagnóstico
./scripts/laura_webhook_doctor.sh

# Tunnel Cloudflare
./scripts/laura_webhook_tunnel_start.sh
cat reports/laura_webhook_tunnel_latest.txt
```

### "Daemon não inicia"

```bash
# Verificar logs
tail -f logs/laura_operations.log
tail -f logs/laura_errors.log

# Verificar PID file
cat laura_daemon.pid

# Verificar processos
ps aux | grep laura
```

### "Tokens expirados"

O daemon renova automaticamente a cada 3 horas.  Para renovação manual:

```bash
laura token-refresh-save
```

### "Seller Center session inválida"

O daemon tenta renovar cookies automaticamente via CDP.
Para renovação manual:

```bash
# Verificar sessão
laura sc products --page-size 1

# Renovar cookies
./scripts/laura_auto_login.sh
```

### "EventBus com erros"

```bash
# Verificar dead-letter queue
laura queue dlq --max 50

# Reenfileirar eventos
laura queue retry --max 50

# Verificar status
laura queue status
```

### "Backup não está funcionando"

```bash
# Executar manualmente
./scripts/laura_backup.sh

# Verificar integridade
./scripts/laura_verify_backup.sh

# Testar restauração
./scripts/laura_restore_drill.sh
```

### Logs

| Arquivo | Descrição |
|---|---|
| `logs/laura_operations.log` | Log operacional completo (JSON) |
| `logs/laura_errors.log` | Apenas warnings e erros |
| `logs/laura_healthcheck.log` | Log do health-check |
| `reports/laura_alerts_history.jsonl` | Histórico de alertas |
| `reports/laura_profitability_latest.json` | Última análise de rentabilidade |
| `reports/laura_metrics.jsonl` | Snapshot de métricas |

---

## FAQ

### Quanto custa para usar Laura?

**Zero.** Laura roda 100% local com Ollama.  Não há custos de API LLM.
A única conta necessária é o Partner ID gratuito da Shopee Open Platform.

### Preciso de GPU?

Não. llama3.2:3b e TinyLlama rodam bem em CPU.  Para modelos maiores (Mistral, Qwen 2.5:7b),
uma GPU com 4-8 GB VRAM ajuda, mas não é obrigatória.

### Laura funciona no Windows?

Sim.  Use PowerShell e siga a [instalação Windows](#windows).
Playwright e CDP funcionam com Chrome/Brave no Windows.

### Laura acessa meus dados da Shopee?

Sim, via API oficial da Shopee Open Platform.  Laura nunca armazena senhas.
Cookies do Seller Center são armazenados localmente em `secrets/`.

### Como atualizar Laura?

```bash
git pull
pip install -e .
```

### Posso usar Laura em múltiplas lojas?

Sim.  Use o sistema multi-tenant:
```bash
laura tenant register loja2 --shop-id 987654321
laura store-summary loja2
```

### Laura funciona sem internet?

Sim.  LLM local (Ollama) funciona offline.  Apenas chamadas à API Shopee
precisam de internet.

### Como contribuir?

1. Fork o repositório
2. Crie um branch (`git checkout -b feature/nova-func`)
3. Commit (`git commit -am 'feat: adiciona nova funcionalidade'`)
4. Push (`git push origin feature/nova-func`)
5. Abra um Pull Request
