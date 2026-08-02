# Changelog

Todas as mudanças relevantes do projeto são documentadas aqui.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto adota [SemVer](https://semver.org/lang/pt-BR/).

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
