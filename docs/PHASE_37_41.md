# Fases 37–41: Multi-Agente, Estratégia, Analytics, Inteligência Competitiva e Supply Chain

**Status**: Implementado ✅ (docs do roadmap `LAURA_ROADMAP.md` — "AI COO → AI CEO")

Estas fases transformam a Laura de um agente operacional (monitorar, alertar,
auditar, automatizar) em um sistema estratégico: coordenação multi-agente,
planos de longo prazo, previsão de demanda, monitoramento de concorrência e
gestão da cadeia de suprimentos. Tudo 100% local e open source (MIT).

---

## Fase 37 — Multi-Agent Orchestration

**Módulo**: `shopee_agent/agent_orchestrator.py`
**Testes**: `tests/test_agent_orchestrator.py`
**CLI**: `laura agent-orchestration`

Agentes especializados propõem ações para objetivos concorrentes (preço,
anúncios, estoque, receita), e o orquestrador detecta conflitos e negocia um
consenso em rodadas.

### Componentes

- `AgentAction` / `AgentProposal` — ações e propostas por agente (direção, magnitude, prioridade).
- `AgentConfig` — configuração de objetivos, restrições e guardrails de cada agente.
- `LauraAgent` — interface de agente (`plan` / `execute` / `negotiate`).
- `PricingAgent`, `AdsAgent`, `InventoryAgent`, `RevenueAgent` — agentes especializados.
- `NegotiationRound` — detecta conflitos entre propostas e resolve por voto ponderado.
- `AgentOrchestrator` — roda o ciclo: propostas → conflitos → negociação → plano de execução.

### Fluxo

```
coordinate_cycle(context)
  1. cada agente gera propostas (preco: "subir 5%", estoque: "repor SKU X")
  2. detecta conflitos (preco sobe × estoque queima)
  3. negocia por prioridade de negocio
  4. retorna ExecutionPlan com acoes aprovadas + tradeoffs
```

O orquestrador é usado por `PlanningWorker` (workers.py) e pelo
`StrategicPlanner` (fase 38), e pode rodar de forma independente via
`laura agent-orchestration`.

---

## Fase 38 — Strategic Planning

**Módulo**: `shopee_agent/strategic_planner.py`
**Testes**: `tests/test_strategic_planner.py`
**CLI**: `laura strategic-plan`, `laura plan-*` (create/list/detail/progress/rollback)

Transforma metas de longo prazo em planos multi-fase com gates de aprovação,
monitoramento de KPI e rollback automático.

### Componentes

- `Goal` — meta com métricas-alvo, orçamento, duração e prioridade.
- `Gate` — ponto de aprovação: só avança se a métrica atingir o alvo.
- `PlanStatus` — `planned | active | at_risk | completed | rolled_back`.
- `StrategicPlan` / `PlanPhase` — plano multi-fase com ações e dependências.
- `PlanAssessment` / `PlanTimeline` — avaliação de risco e cronograma.
- `GoalStack` — hierarquia de metas (trimestral → mensal → diário).
- `StrategicPlanner` — decomposição de metas, execução, monitoramento e rollback.

### Integração

- `AutonomousLoop` instancia `StrategicPlanner()` no boot (`autonomous_loop.py:88`).
- `AutonomousStrategyLayer` (fase "CEO") usa o planner para gerar o snapshot estratégico.
- `PlanningWorker` (workers.py:362) roda planos em worker dedicado.

---

## Fase 39 — Predictive Analytics

**Módulo**: `shopee_agent/predictive_analytics.py`
**Testes**: `tests/test_predictive_analytics.py`
**CLI**: `laura economic-brain-summary`, `laura predict-refunds`, `laura analytics-trends`

Previsão de demanda (30 dias), detecção de anomalias e previsão de reembolsos
com métodos estatísticos puros (sem dependências pesadas).

### Componentes

- `ForecastSeries` — série temporal com método (`linear_trend`), horizonte e confiança.
- `ForecastResult` — previsão com intervalo de confiança.
- `PredictiveSnapshot` — visão consolidada da previsão.
- `PredictiveAnalytics` — treinamento/ajuste em séries reais, projeção e detecção de anomalias (desvio padrão / z-score).

### Integração

- `AutonomousLoop` instancia `PredictiveAnalytics(reports_dir=...)` no boot.
- `AutonomousStrategyLayer` usa o snapshot preditivo no `StrategySignal`.
- `StockPredictor` / `CostPredictor` complementam com previsão de estoque e custo.

---

## Fase 40 — Competitive Intelligence

**Módulo**: `shopee_agent/competitive_intelligence.py`
**Testes**: `tests/test_competitive_intelligence.py`
**CLI**: `laura competitive-intel-summary`

Monitora ofertas de concorrentes (preço, frete, posição no ranking), calcula
vantagem/desvantagem e gera sinais acionáveis com prioridade.

### Componentes

- `CompetitorOffer` — oferta observada (concorrente, item, preço, fonte, observações).
- `CompetitiveSignal` — sinal: item em risco, vantagem nossa, preço fora do padrão etc.
- `CompetitiveIntelligence` — registro de ofertas (`reports/competitive_offers.jsonl`), detecção de sinais e resumo executivo.

### Integração

- `AutonomousLoop` instancia `CompetitiveIntelligence(path=...)` no boot.
- `laura competitive-intel-summary` gera o resumo via LLM local (Ollama).

---

## Fase 41 — Supply Chain v2

**Módulo**: `shopee_agent/supply_chain_planner_v2.py`
**Testes**: `tests/test_supply_chain_planner_v2.py`
**CLI**: `laura supply-chain`

Supplier scoring, geração automática de ordens de compra (auto-PO) e
balanceamento multi-warehouse.

### Componentes

- `SupplierScorer` — pontua fornecedores por dimensões (preço, prazo, confiabilidade) e classifica em tiers.
- `AutoPurchaseOrderGenerator` — gera POs com base em previsão de demanda e estoque.
- `MultiWarehouseBalancer` — redistribui estoque entre warehouses para evitar ruptura/encalhe.
- `SupplyChainPlannerV2` — orquestra: score → PO → balanceamento → recomendação final.

---

## Como validar

```bash
# Testes das fases 37-41
python -m pytest tests/test_agent_orchestrator.py tests/test_strategic_planner.py \
  tests/test_predictive_analytics.py tests/test_competitive_intelligence.py \
  tests/test_supply_chain_planner_v2.py tests/test_economic_brain.py -q

# CLI
laura agent-orchestration
laura strategic-plan --goal "Crescer margem para 20%"
laura economic-brain-summary
laura competitive-intel-summary
laura supply-chain
```

Todas as fases rodam localmente com custo zero (LLM via Ollama) e são
exigidas pelo job `test` do CI.
