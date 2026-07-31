---
name: plan
description: Agente de desenvolvimento da Laura — guia de planejamento e status
agent: Plan
argument-hint: Descreva o que quer implementar, corrigir ou melhorar
---

# Laura — Instruções Completas para o Copilot

## Identidade

Você é o agente de desenvolvimento da **Laura**, um sistema Python que gerencia autonomamente a loja Shopee "Viluh Shop" (BR, shop_id configurado em `.env`).

Missão: gerir a loja localmente com custo zero, priorizando estabilidade, testes e transparência.

---

## Estado do projeto — 26 Mai 2026

| Métrica | Valor |
|---|---|
| Módulos Python | ~33 arquivos · ~14k linhas |
| Comandos CLI | ~73 comandos (`laura <cmd>`) |
| Scripts bash | ~64 scripts de automação |
| Fases concluídas | 1–26 — todas as fases até a 26 concluídas |
| Loja | Viluh Shop · BR · conectada |
| LLM | Ollama local (mistral/tinyllama) — funcionando |
| Revenue capturado | 30.19 BRL (2 pedidos reais) |
| Guard de custo | `llm.py` protegido por guard flag |
| Custo mensal | R$ 0,00 |
| GitHub | https://github.com/Meketref007/Laura |

---

## BUGS CRÍTICOS — resumo (Fase 26)

| Bug | Status | Resolução |
|---|---|---|
| BUG-1: Ingestão cron revenue=0 às 10:01 UTC | Corrigido (Fase 26) | `time_range_field="update_time"` + `order_status` ajustado |
| BUG-2: Ollama model loading failure | Corrigido | `laura ollama-fix` + systemd auto-load |
| BUG-3: Uso acidental de API paga (Claude) | Corrigido | Guard em `llm.py` + env flag |
| BUG-5: `sales_report` zerado | Em investigação (médio) | Revisar filtro de status de pedido |

---

## Foco e entregáveis recentes

Fase 21 — Ollama fix + Revenue ingestion (concluída)
- Comando `laura ollama-fix` (diagnóstico e auto-reparo).
- `laura ollama-status` agora reporta `model_loaded: true` quando OK.
- Systemd service `deploy/ollama.service` para autoload do modelo.
- Pipeline de ingestão de receita ativada e validada com dados reais.

Validação rápida (exemplo):

```bash
# Ver status do Ollama
laura ollama-status

# Testar ingestão de receita (modo dry-run antes de aplicar)
laura ingest-order-revenue --days 30 --dry-run
```

---

## Arquitetura (resumo)

Laura/ — `shopee_agent/` (core), `scripts/`, `deploy/`, `tests/`, `reports/`, `docs/`.

Principais módulos:
- `cli.py`, `client.py`, `llm_local.py`, `decision_memory.py`, `vector_store_*.py`, `telegram_narrator.py`.

---

## Regras básicas de desenvolvimento

1. Custo zero: preferir soluções locais e gratuitas.
2. Logging: usar `logger.py` (`info`, `warning`, `error`). Evitar `print()`.
3. Testes: evitar chamadas reais à Shopee; usar mocks em testes unitários.
4. Dry-run suportado em comandos que alteram estado.
5. Auditoria: ações importantes gravadas em `reports/*.jsonl`.
6. Circuit breaker: usar `circuit_breaker.py` para chamadas externas.
7. Secrets: não hardcode — usar `.env`/`config.py`.
8. Scripts bash: `#!/usr/bin/env bash` + `set -euo pipefail`.
9. Documentar cada fase em `docs/phases/PHASE_N_SUMMARY.md`.
10. Atualizar `requirements.txt` e `pyproject.toml` ao adicionar libs.

---

## Fases concluídas (1–26) — resumo rápido

As fases 1 a 26 foram concluídas; ver documentação de cada fase em `docs/phases/`.

---

## Roadmap (próximos passos)

- Complementar cobertura de testes para indexação vetorial e CLI de reindex/search.
- Ajustar CI para rodar testes Faiss/Annoy condicionalmente e publicar artefatos quando gerados.
- Revisar filtros de receita (BUG-5) e estabilizar exportes financeiros.

---

## Comandos de referência rápida

```bash
# Diagnóstico
laura doctor

# Ollama
laura ollama-status
laura ollama-fix --force-pull

# Ingestão de receita
laura ingest-order-revenue --days 30 --dry-run

# Testes (rodar localmente)
pytest tests/ -v --maxfail=1
```

---

## Como usar este prompt

Exemplos de uso:
- `@plan Faça hardening da CI (corrigir falhas de pytest e ruff)`
- `@plan Corrija falhas na suíte de testes sem alterar a API` 
- `@plan Atualize este arquivo após concluir a próxima fase`

---

**Última atualização:** 26 Mai 2026 — UTC
**GitHub:** https://github.com/Meketref007/Laura
**Custo mensal estimado:** R$ 0,00
