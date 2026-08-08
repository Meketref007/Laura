# Changelog

Todas as mudanças relevantes do projeto são documentadas aqui.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto adota [SemVer](https://semver.org/lang/pt-BR/).

## [3.4.0] - 2026-08-08

### Adicionado
- **Camadas CEO conectadas ao ciclo principal** — o `AutonomousLoop` agora instancia e
  injeta no `DecisionIntegrator` o `EconomicBrain`, `SupplyChainPlanner`,
  `AutonomousStrategyLayer`, `Planner`, `GoalManager` e `PriorityEngine` (antes só
  rodavam via CLI/workers). Todos os snapshots aparecem no `decision_cycle_summary` do log.
- **Fallback robusto sem Ollama** (`llm_local.py`) — se o Ollama não está rodando, o
  `LauraOllamaAnalyzer` entra em modo offline e cai no fallback heurístico em vez de
  levantar `RuntimeError` (não tenta mais baixar o modelo offline).
- **CLI `laura` no PATH do usuário** — `install.ps1` cria `%LOCALAPPDATA%\Laura\bin\laura.cmd`
  e o adiciona ao PATH do usuário (botão `laura status`, `laura doctor` em qualquer terminal);
  `uninstall.ps1` remove o PATH.
- **Smoke test E2E real opt-in** contra a Shopee Open Platform
  (`tests/integration/test_e2e_shopee_real.py`) — só roda com `LAURA_E2E_REAL=1` e
  credenciais via secrets; novo job `e2e-real` no CI (pré-requisito da release).
- **Roadmap atualizado** (`docs/LAURA_ROADMAP.md`) — marca fases 35-42 como implementadas
  e define as próximas (43+: hardening, dashboard, multi-loja, marketplace de skills).

### Corrigido
- **Bug `OrchestrationWorker failed | Decision.__init__() missing 6 required positional
  arguments`** — `workers.py` e `autonomous_loop.py` construíam `Decision` sem
  `rule_id`/`recommended_action`/`impact_score`/`risk_score`/`confidence_score`/`signal`:
  agora `_execute_action` mapeia `AgentAction` → `Decision` completo (testes de regressão).
- Target de cobertura do CI elevado de 30% para 38% (a suíte cobre 43% hoje).

## [3.3.0] - 2026-08-02

### Adicionado
- **Restauração de backup** (`scripts/laura-restore.ps1`) — restaura o backup diário
  mais recente (ou um específico com `-From`), reinicia os serviços e valida a saúde
  do webhook. Botão "Restaurar" no painel.
- **Forecasting avançado** no `predictive_analytics.py` — suavização exponencial de
  Holt e detecção de sazonalidade (fins de semana, etc.); o melhor método é escolhido
  automaticamente pelo menor erro (holdout RMSE) e reportado em `details.method`.
- **Orquestração multi-agente no ciclo principal** — `AgentOrchestrator` agora é
  instanciado pelo `AutonomousLoop` e passa a alimentar o `DecisionIntegrator`;
  em CEO mode, ações aprovadas do plano (preço/anúncios/estoque) viram decisões
  executáveis (campo `orchestration_executed` no log).
- **Branding & Growth no ciclo** (Fase 42) — `BrandingGrowthAnalyzer` integrado ao
  loop; snapshot aparece no log (`branding_growth`). Docs: `docs/PHASE_37_41.md`
  agora cobre até a fase 42.
- **Job `install-e2e` no CI** — instalação real em runner Windows limpo: venv,
  dependências, `.env`, cloudflared, serviços no ar e health check do webhook.
  Passou a ser pré-requisito da release.
- **Painel**: botão "Restaurar" e link "Config (.env)" (abre o `.env` para edição).

### Corrigido
- **Bug estrutural do backup**: `Copy-Item` sem destino pré-criado achata a pasta
  `reports/` na raiz do stamp; backup agora preserva `reports/ data/ secrets/ logs/`.
- **Fator sazonal do forecast**: a previsão sazonal dividia pela média errada,
  inflando os fatores; agora usa a média global da série.
- Painel: import de `urllib` faltando (botão "Nova versão?" quebrava).

## [3.2.0] - 2026-08-02

### Adicionado
- **Rodar sem login**: `install.ps1 -AsService` (admin) cria tarefas ONSTART
  "Laura Services" e "Laura Update Boot" — webhook, telegram, daemon e watchdog
  sobem no boot mesmo sem ninguém fazer login.
- **Job de testes de integração no CI** (`pytest -m integration`, 107 testes)
  — os testes e2e agora rodam em job separado; o job principal usa `-m "not integration"`.
- **Testes e2e das camadas estratégicas** (`tests/integration/test_e2e_strategic_layers.py`)
  — fases 37-41 validadas de ponta a ponta (orquestrador, planner, analytics, intel competitiva, supply chain).
- **CHANGELOG público** (`CHANGELOG.md`, formato Keep a Changelog).
- **Docs das fases 37-41** (`docs/PHASE_37_41.md`) — multi-agente, strategic planning,
  predictive analytics, competitive intelligence e supply chain v2.
- Badges do README atualizados com métricas reais (1229 testes, 44% cobertura).

### Corrigido
- Mark `integration` registrado no `pyproject.toml` (elimina o aviso de unknown mark).

## [3.1.0] - 2026-08-02

### Adicionado
- Projeto **open source (MIT)** — repositório público.
- **Instalador Windows** (`Setup.exe`, Inno Setup, per-user) com painel desktop Tkinter.
- **Atualização automática**: git pull a cada boot + 1x/dia (03:00) + manual pelo painel.
- **Backup diário** (03:30) com retenção de 7 dias (`scripts/laura-backup.ps1`).
- **CI completo**: jobs de teste (pytest), lint (ruff), typecheck (mypy), Pester (scripts PowerShell), build do Setup e release automática em tag `v*`.
- **Release automática**: a cada tag `vX.Y.Z`, gera `Laura-Setup-X.Y.Z.exe` + `SHA256SUMS.txt` no GitHub Releases.
- **Extras de máquina nova**: modelos Ollama (moondream, llama3.2:3b), Playwright chromium e cloudflared (opcional, opt-in).
- **Alerta via Telegram** no watchdog em caso de crash loop.
- Scripts utilitários: `laura-services.ps1`, `laura-extra-setup.ps1`.
- Documentação: `docs/SKILLS.md`, badges de release/instalador/licença no README.

### Corrigido
- Updater: `$range` do git diff tratado como string (operador range do PowerShell).
- Updater: arquivos locais não rastreados colidindo com o repo (ex.: `laura_icon.ico`) quebravam o pull — agora são removidos se existirem no remoto.
- Updater: `core.autocrlf=true` causava falsos "modified" por CRLF — agora desativa e normaliza antes de puxar (dados locais gitignorados ficam intactos).
- Watchdog: adotava daemon existente (evita 2 daemons ao subir com `laura-services`).
- Watchdog: não abre navegador sem opt-in (`-CdpAutoLaunch`), no máximo 1x/sessão.
- Setup: URL do Inno Setup via GitHub (download.php do jrsoftware estava quebrado), `InstallDir` explícito no `[Run]`, `RunOnceId` no uninstall.

## [3.0.0] - 2026-07-29

### Adicionado
- Instalador de linha de comando (`installer/install.ps1`) com migração automática de dados, agendamento e atalho de boot.
- `laura-update.ps1` com lock anti-concorrência e reinstalação de dependências quando `pyproject.toml` muda.
- `laura_watchdog.ps1` browser-agnóstico (Brave → Chrome → Edge, ou `LAURA_CDP_BROWSER_PATH`).

### Corrigido
- Watchdog com janelas escondidas e sem loop de abertura do Brave.
- Portabilidade: caminhos relativos, sem dependência do OneDrive.

---

## Histórico anterior (pré-3.0.0)

Antes do 3.0.0 o repositório foi reiniciado com histórico limpo (commit `99c87f1`).
As funcionalidades anteriores a essa data estão resumidas abaixo:

- **Agente autônomo Shopee**: loop contínuo, skills modulares, GOAP planner (A*), decision engine com regras adaptativas.
- **EventBus assíncrono** com WAL journal, dead-letter queue, circuit breaker e self-healing.
- **Telegram**: bot interativo (comandos remotos) + narrador de notificações.
- **Chat automático** com compradores, auto-reply e aprovação humana.
- **Flash sale recommender** e gerenciamento de campanhas.
- **Predictive analytics**: previsão de vendas (30 dias), detecção de anomalias, previsão de reembolsos.
- **Inteligência competitiva**: monitoramento de ofertas de concorrentes.
- **Supply chain v2**: supplier scoring, auto-PO, multi-warehouse.
- **Multi-agente (fase 37)**: orquestração com negociação e consenso.
- **Strategic planner (fase 38)**: planos multi-fase com gates e rollback.
- **Dashboard web** (FastAPI + frontend) com métricas, aprovações e WebSocket.
- **A/B testing**, canary deploy, federated learning, multi-tenant.
- **CEO mode** (`LAURA_CEO_MODE=1`): autonomia total com guardrails.
- **Docker compose** (`make up`) com Laura + Ollama.

[Unreleased]: https://github.com/Meketref007/Laura/compare/v3.2.0...HEAD
[3.2.0]: https://github.com/Meketref007/Laura/releases/tag/v3.2.0
[3.1.0]: https://github.com/Meketref007/Laura/releases/tag/v3.1.0
