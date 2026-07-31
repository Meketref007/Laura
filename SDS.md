# Laura â€” Software Design Specification (SDS)

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-07-30 | Laura Team | Initial complete specification |

---

## 1. Introduction

### 1.1 Purpose

This Software Design Specification (SDS) defines the complete architecture, component specifications, data design, interfaces, security model, and deployment strategy for **Laura** â€” an autonomous AI-powered agent for Shopee e-commerce sellers. Laura operates 100% locally with zero API costs, integrating with the Shopee Open Platform API, Seller Center via browser automation, and Telegram for remote notifications and commands. This document serves as the authoritative reference for developers, maintainers, and system integrators working on the Laura platform.

### 1.2 Scope

The scope encompasses:

- **Core Agent System**: Autonomous loop, daemon, CLI, dashboard web server
- **AI/ML Components**: LLM providers (local + cloud), GOAP planner, decision engine, adaptive learning, cognitive memory, vector stores
- **E-commerce Integration**: Shopee Open API v2 client, Seller Center browser automation, OAuth2 token management
- **Communication**: Telegram bot + narrator, email (SMTP/Gmail), webhook server, Slack/Discord integration
- **Automation**: Skills plugin system, pricing autopilot, campaign manager, flash sale executor, supply chain planner, cross-selling
- **Infrastructure**: Event bus with WAL + DLQ, circuit breakers, rate limiters, retry logic, distributed tracing, health monitoring, backup/restore, graceful shutdown
- **DevOps**: Docker deployment, CI/CD (GitHub Actions), pre-commit hooks, mypy/ruff quality gates
- **Business Intelligence**: Predictive analytics, competitive intelligence, branding/growth analysis, weekly PDF reports, multi-format export

### 1.3 Definitions, Acronyms, and Abbreviations

| Term | Definition |
|------|-----------|
| GOAP | Goal-Oriented Action Planning â€” AI planning technique using A* search |
| LLM | Large Language Model |
| WAL | Write-Ahead Log â€” durable event journal before processing |
| DLQ | Dead-Letter Queue â€” storage for failed events |
| CDP | Chrome DevTools Protocol â€” browser automation protocol |
| ROAS | Return on Ad Spend |
| DAG | Directed Acyclic Graph |
| ANN | Approximate Nearest Neighbors |
| PWA | Progressive Web Application |
| HMAC | Hash-based Message Authentication Code |
| FSM | Finite State Machine |
| FTS5 | Full-Text Search version 5 (SQLite) |

### 1.4 References

| Reference | Description |
|-----------|-------------|
| Shopee Open Platform API v2 | https://open.shopee.com/documents |
| Ollama API | https://github.com/ollama/ollama |
| Telegram Bot API | https://core.telegram.org/bots/api |
| FastAPI | https://fastapi.tiangolo.com/ |
| Playwright | https://playwright.dev/python/ |
| Python 3.12+ | https://docs.python.org/3.12/ |
| SQLite | https://sqlite.org/docs.html |
| Annoy | https://github.com/spotify/annoy |
| FAISS | https://github.com/facebookresearch/faiss |

### 1.5 Document Overview

- **Section 2**: System overview, goals, key design decisions, technology stack
- **Section 3**: System architecture with layer diagrams and module dependency graph
- **Section 4**: Detailed component specifications for all modules
- **Section 5**: Data design â€” SQLite schema, vector store, cache, filesystem layout
- **Section 6**: External interface design â€” Shopee API, LLM providers, Telegram, email, dashboard
- **Section 7**: Security design â€” auth, secrets, API security, audit logging
- **Section 8**: Quality assurance â€” testing strategy, CI/CD, code quality
- **Section 9**: Deployment â€” Docker, systemd, Nginx, monitoring, backup
- **Section 10**: Appendix â€” CLI reference, env vars, REST API, WebSocket events, hooks, error codes

---

## 2. System Overview

### 2.1 System Context

Laura is an autonomous agent operating within a Shopee seller's ecosystem providing continuous monitoring, autonomous decision-making via GOAP planning and adaptive rules, action execution through Shopee Open API and Seller Center browser automation, learning and adaptation via outcome feedback loops and cognitive memory, and user interaction via CLI, web dashboard, Telegram bot, and plugins.

### 2.2 System Goals

1. **Zero Operating Cost**: Run entirely on local infrastructure using Ollama for LLM inference
2. **Full Autonomy**: Execute complete sell-side e-commerce workflow without human intervention
3. **Intelligent Planning**: Use GOAP with A* search to compose optimal action sequences from modular skills
4. **Adaptive Learning**: Continuously improve decision quality through reinforcement from outcome feedback
5. **Resilient Operations**: Survive network failures, API rate limits, token expirations, and component crashes
6. **Extensible Architecture**: Support third-party plugins, custom skills, and multi-tenant deployments
7. **Privacy-First**: All sensitive data remains local; no data leaves the seller's infrastructure
8. **Multi-Channel Interaction**: CLI, web dashboard, Telegram, email, and webhooks

### 2.3 Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Ollama as primary LLM | Zero cost, runs on CPU, fully offline capable, supports multiple open models |
| SQLite for persistence | Single-file database, zero configuration, ACID compliant |
| GOAP over rule-based planning | Dynamic action composition handles novel situations better |
| Event-driven architecture | Decouples components, enables async processing, provides audit trail via WAL |
| Plugin system with Python files | Lowest barrier for third-party extensions, leverage full Python ecosystem |
| Playwright for Seller Center | Access Seller Center operations not exposed by Shopee Open API |
| JSONL for log/event storage | Append-only, human-readable, grep-friendly, easy to rotate and archive |
| Annoy/FAISS for vector search | Lightweight approximate nearest neighbor search for semantic memory |
| Circuit breaker + retry patterns | Prevent cascading failures, handle transient API issues gracefully |
| Multi-provider LLM abstraction | Ollama primary with OpenAI/Anthropic fallback for complex reasoning tasks |

### 2.4 Technology Stack

| Layer | Technology | Version | Purpose |
|-------|-----------|---------|---------|
| Language | Python | 3.12+ | Primary development language |
| CLI Framework | argparse + Click | 8.1+ | Command-line interface with 140+ commands |
| Web Framework | FastAPI | 0.115+ | REST API + WebSocket server for dashboard |
| ASGI Server | Uvicorn | 0.30+ | Production ASGI server |
| Database | SQLite | 3.x | Primary data store |
| Vector Store | Annoy / FAISS | 1.17+ / cpu | Semantic memory search |
| Cache | Filesystem JSON / Redis | â€” | API response caching |
| LLM Runtime | Ollama | latest | Local LLM inference |
| Browser Automation | Playwright | 1.40+ | Seller Center interaction |
| HTTP Client | requests | 2.31+ | Shopee API communication |
| PDF Generation | ReportLab | 4.0+ | Weekly report generation |
| Spreadsheets | openpyxl | 3.1+ | Excel export |
| Image Processing | Pillow + OpenCV | 10.0+ / 4.8+ | Vision analysis |
| OCR | pytesseract | 0.3+ | Text extraction from images |
| Testing | pytest | 7.4+ | Unit/integration/E2E tests |
| Code Quality | mypy + ruff | 1.8+ / 0.4+ | Type checking + linting |
| Containerization | Docker + docker-compose | latest | Deployment packaging |
| Monitoring | Prometheus metrics | â€” | Operational visibility |

---

## 3. System Architecture

### 3.1 High-Level Architecture

```
+====================================================================+
|                    LAURA SYSTEM ARCHITECTURE                        |
+====================================================================+

  +------------------+  +------------------+  +------------------+
  | CLI (argparse)   |  | Web Dashboard    |  | Telegram Bot     |
  | 140+ commands    |  | FastAPI :8888    |  | Long-polling     |
  | shell, daemon    |  | Chart.js, PWA    |  | Inline keyboard  |
  +--------+---------+  +--------+---------+  +--------+---------+
           |                     |                      |
  +--------+---------------------+----------------------+---------+
  |                    PRESENTATION LAYER                            |
  +------------------------------------------------------------------+
           |                     |                      |
  +--------+---------------------+----------------------+---------+
  |                    API / GATEWAY LAYER                           |
  |  +----------+  +-----------+  +----------+  +----------+       |
  |  | REST API |  | WebSocket |  | Webhooks |  | Auth Gw  |       |
  |  +----------+  +-----------+  +----------+  +----------+       |
  +------------------------------------------------------------------+
           |                     |                      |
  +--------+---------------------+----------------------+---------+
  |                    CORE / ORCHESTRATION LAYER                     |
  |                                                                  |
  |  +------------------+  +-----------------+  +--------------+    |
  |  | AutonomousLoop   |  | DecisionEngine  |  | GOAPPlanner  |    |
  |  | Cycle manager    |  | Rule evaluator  |  | A* search    |    |
  |  +------------------+  +--------+--------+  +------+-------+    |
  |                                |                   |             |
  |  +------------------+  +--------+--------+  +------+-------+    |
  |  | AdaptiveEngine   |  | DecisionIntegr. |  | PlanExecutor |    |
  |  | Learning rules   |  | Signal aggreg.  |  | Task DAG     |    |
  |  +------------------+  +-----------------+  +--------------+    |
  |                                                                  |
  |  +------------------+  +-----------------+  +--------------+    |
  |  | LearningSystem   |  | CognitiveMemory  |  | GoalManager  |    |
  |  | Feedback cycles  |  | SQLite + vectors |  | Goal library |    |
  |  +------------------+  +-----------------+  +--------------+    |
  |                                                                  |
  +------------------------------------------------------------------+
           |                     |                      |
  +--------+---------------------+----------------------+---------+
  |                    EXECUTION / SKILLS LAYER                      |
  |                                                                  |
  |  +------------------+  +-----------------+  +-------------+     |
  |  | SkillRegistry    |  | SkillOrchestr.  |  | Sandbox     |     |
  |  | Module registry  |  | DAG execution   |  | Isolated run|     |
  |  +------------------+  +-----------------+  +-------------+     |
  |  +----------+ +----------+ +----------+ +----------+            |
  |  | Pricing  | |Inventory | | Order    | | Chat     |            |
  |  +----------+ +----------+ +----------+ +----------+            |
  |  +----------+ +----------+ +----------+ +----------+            |
  |  | FlashSale| |Campaign  | |SupplyChn | |Cross-Sell|            |
  |  +----------+ +----------+ +----------+ +----------+            |
  |  +----------+ +----------+ +----------+ +----------+            |
  |  | Browser  | |Support   | | Vision   | | Scraper  |            |
  |  +----------+ +----------+ +----------+ +----------+            |
  |                                                                  |
  +------------------------------------------------------------------+
           |                     |                      |
  +--------+---------------------+----------------------+---------+
  |                    INTEGRATION / ADAPTER LAYER                   |
  |                                                                  |
  |  +------------------+  +-----------------+  +-------------+     |
  |  | ShopeeClient     |  | SellerCenter    |  | TeleBot     |     |
  |  | Signed requests  |  | Playwright CDP  |  | Polling bot |     |
  |  +------------------+  +-----------------+  +-------------+     |
  |  +------------------+  +-----------------+  +-------------+     |
  |  | LLM Providers    |  | Webhook Server  |  | Slack/Disc  |     |
  |  | Ollama/OpenAI/An |  | HTTP callback   |  | Webhooks    |     |
  |  +------------------+  +-----------------+  +-------------+     |
  |                                                                  |
  +------------------------------------------------------------------+
           |                     |                      |
  +--------+---------------------+----------------------+---------+
  |                    INFRASTRUCTURE LAYER                          |
  |                                                                  |
  |  +------------------+  +-----------------+  +-------------+     |
  |  | EventBus         |  | CircuitBreaker  |  | RateLimiter |     |
  |  | WAL + DLQ        |  | FSM states     |  | Token bucket|     |
  |  +------------------+  +-----------------+  +-------------+     |
  |  +------------------+  +-----------------+  +-------------+     |
  |  | GracefulShutdown |  | SelfHealing     |  | HealthCheck |     |
  |  | Signal handlers  |  | Auto-recovery   |  | Monitor     |     |
  |  +------------------+  +-----------------+  +-------------+     |
  |  +------------------+  +-----------------+  +-------------+     |
  |  | Backup Manager   |  | Security Audit  |  | Secrets Rot |     |
  |  | Zip archives     |  | Permission chk  |  | Token life  |     |
  |  +------------------+  +-----------------+  +-------------+     |
  |                                                                  |
  +------------------------------------------------------------------+
           |                     |                      |
  +--------+---------------------+----------------------+---------+
  |                    PERSISTENCE LAYER                             |
  |                                                                  |
  |  +------------------+  +-----------------+  +-------------+     |
  |  | SQLite DBs       |  | Vector Store    |  | API Cache   |     |
  |  | goap_learning    |  | Annoy/FAISS/Mem |  | File/Redis  |     |
  |  | plan_store       |  | Cosine sim      |  | 30-day TTL  |     |
  |  +------------------+  +-----------------+  +-------------+     |
  |  +------------------+  +-----------------+  +-------------+     |
  |  | Event Journal    |  | JSONL files     |  | Filesystem  |     |
  |  | (WAL)            |  | Append-only     |  | reports/    |     |
  |  +------------------+  +-----------------+  +-------------+     |
  |                                                                  |
  +------------------------------------------------------------------+
```

### 3.2 Layer Architecture

The architecture is organized into seven distinct layers:

1. **Presentation Layer** â€” CLI (140+ commands), Web Dashboard (FastAPI + Chart.js), Telegram Bot (long-polling), Telegram Narrator (push notifications), Chrome Extension (planned)
2. **API/Gateway Layer** â€” REST API (FastAPI), WebSocket (realtime streaming), Webhook Server (Shopee callbacks), Auth Gateway (OAuth + API keys)
3. **Core/Orchestration Layer** â€” AutonomousLoop (cycle manager), DecisionEngine (rule evaluation), GOAPPlanner (A* search), AdaptiveEngine (self-tuning rules), LearningSystem (feedback cycles), CognitiveMemory (semantic memory), GoalManager
4. **Execution/Skills Layer** â€” SkillRegistry (module discovery), SkillOrchestrator (DAG execution), Sandbox (isolated testing), modular skills (Pricing, Inventory, Order, Chat, FlashSale, Campaign, SupplyChain, CrossSell, Browser, Support, Vision)
5. **Integration/Adapter Layer** â€” ShopeeClient (signed HTTP), SellerCenter (Playwright/CDP automation), Telegram Bot (polling), LLM Providers (Ollama/OpenAI/Anthropic), Webhook Server, Slack/Discord webhooks
6. **Infrastructure Layer** â€” EventBus (WAL + DLQ), CircuitBreaker (FSM), RateLimiter (token bucket), Retry (backoff + jitter), GracefulShutdown (signal handlers), SelfHealing (auto-recovery), BackupManager, SecurityAudit, SecretsRotation
7. **Persistence Layer** â€” SQLite databases, Vector Store (Annoy/FAISS/in-memory), API Cache (file/Redis), Event Journal (JSONL), reports filesystem

### 3.3 Daemon Cycle

```
[Setup] -> [Auto-login thread] -> [LLM thread] -> loop:
  +- _cycle() -> AutonomousLoop.run_cycle()
  |   +- DecisionEngine evaluates rules
  |   +- Skills execute actions
  |   +- GOAP plans next steps
  |   +- Results -> EventBus -> Telegram
  +- health_check() every 30 min
  +- sleeps CYCLE_INTERVAL (default 5 min)
```

### 3.4 Key Architectural Patterns

**Plugin Architecture**: Python-based plugin system discovered from plugins/ directory. Each plugin inherits Plugin base class with 20+ lifecycle hooks.

**GOAP Planner**: A* heuristic search on state space defined by skill preconditions/effects. Actions costs auto-adjust from outcome history.

**Event-Driven Architecture**: Async publish-subscribe via EventBus with typed events, WAL journaling, DLQ, and retry with backoff.

**Multi-Provider LLM**: Unified interface across Ollama (default), OpenAI, Anthropic with automatic fallback and cost controls.

**Adaptive Decision Engine**: Self-tuning rules with outcome-based weight adjustment, pattern detection, automatic pruning.

---

## 4. Component Specifications

### 4.1 CLI (cli.py + cli_commands/)

**Purpose**: Entry point for all Laura operations. 140+ subcommands across 15+ categories.

**Dependencies**: All major modules â€” ShopeeClient, Config, Auth, LLM, DecisionEngine, GOAPPlanner, EventBus, Workers, Dashboard, Skills.

**Key Classes/Functions**:
- `main()` â€” Argument parser entry point, dispatches to handler functions
- `_serve_api()` â€” Starts FastAPI Uvicorn server
- `_print_json()` â€” Utility for JSON-formatted CLI output
- CLI command handlers in cli_commands/: auth_shop_cmd, order_cmd, product_cmd, health_cmd, chat_cmd, export_cmd, seller_cmd, report_cmd, monitor_cmd, cache_cmd, cleanup_cmd, email_cmd, watchdog_cmd

**Data Flow**: User Input > argparse parser > handler function > module API > JSON/formatted output

### 4.2 Daemon (laura_daemon.py)

**Purpose**: Continuous background loop orchestrating all autonomous operations. 5-minute cycle (configurable).

**Dependencies**: AutonomousLoop, ShopeeClient, SellerCenterClient, EventBus, Workers, ChatMonitor, GracefulShutdown, Backup, LLMManager.

**Key Classes**:
- `LauraDaemon` â€” Main daemon with cycle loop, health checks, backup scheduling
- `run()` â€” Infinite loop: setup > auto-login > LLM check > _cycle() > sleep
- `_cycle()` â€” Delegates to AutonomousLoop.run_cycle()

**Configuration**: VILU_DAEMON_INTERVAL (300s), VILU_BACKUP_INTERVAL (86400s), LAURA_AUTO_LOGIN_INTERVAL (21600s)

### 4.3 Config (config.py)

**Purpose**: Centralized configuration loading from environment variables and .env file. Type-safe dataclass.

**Key Classes**:
- `ShopeeConfig` â€” Frozen dataclass: base_url, partner_id, partner_key, redirect_url, default_shop_id, tokens, vector_backend, annoy/faiss paths
- `load_config()` â€” Reads env vars, returns ShopeeConfig
- `_load_env_file_if_present()` â€” Loads .env with setdefault semantics

### 4.4 Paths (paths.py)

**Purpose**: Centralized absolute path management for all filesystem locations.

**Key Path Groups**:
- Directories: REPORTS_DIR, LOGS_DIR, SECRETS_DIR, BACKUPS_DIR, DATA_DIR, SKILLS_DIR
- Reports: 50+ paths (PROFITABILITY_LATEST, HEALTH_LATEST, DECISION_LOG, GOAP_LEARNING, ANNOY_INDEX, FAISS_INDEX, etc.)
- Logs: OPERATIONS_LOG (JSON structured)
- Secrets: SELLER_CENTER_CREDENTIALS, GMAIL_CREDENTIALS, TELEGRAM_SETUP
- System: CLOUDFLARED_CONFIG, WATCHDOG_PID, DAEMON_PID

### 4.5 Logger (logger.py, structured_logger.py)

**Purpose**: Centralized structured JSON logging with rotating file handlers.

**Key Classes**:
- `StructuredLogger` â€” Wraps Python logger with JSON output, rotating file (10MB, 5 backups)
- Module-level functions: info(), debug(), warning(), error()

### 4.6 Event Bus (event_bus.py)

**Purpose**: Async event-driven communication backbone with typed events, WAL journal, and DLQ.

**Key Classes**:
- `Event` â€” Base dataclass: event_type, timestamp, source
- Typed Events: DecisionSignalEvent, DecisionExecutedEvent, OutcomeRecordedEvent, GOAPPlanExecutedEvent, CycleCompleteEvent, AlertEvent, MetricUpdateEvent
- `AsyncEventBus` â€” start/stop, emit/emit_async, subscribe, WAL journaling, DLQ management

**Data Flow**: Publisher > emit(event) > WAL journal > thread pool > handlers > on failure > retry (3x, backoff) > DLQ

### 4.7 LLM Providers (llm_providers.py, llm_local.py, llm_manager.py)

**Purpose**: Unified LLM abstraction supporting Ollama, OpenAI, and Anthropic with auto-detection and fallback.

**Key Classes**:
- `LLMConfig` â€” provider, model, temperature, max_tokens, timeout
- `LLMResponse` â€” text, model, provider, tokens_used, latency_ms, success
- `LLMInterface` (ABC) â€” generate(), analyze(), count_tokens()
  - OllamaProvider (default, local, free)
  - OpenAIProvider (ChatGPT, paid fallback, requires LAURA_ALLOW_PAID_LLM=1)
  - AnthropicProvider (Claude, paid fallback)
- `LLMManager` â€” Model lifecycle: check running, start if needed, download models
- `LauraOllamaAnalyzer` â€” Profitability analysis using local LLM

### 4.8 GOAP Planner (goap_planner.py, planner.py)

**Purpose**: Goal-Oriented Action Planning using A* search with learning.

**Key Classes**:
- `GOAPAction` â€” name, cost, preconditions, effects, priority, version, sub_skills
  - is_valid(state), apply_effects(state), inverse_effects()
  - Comparison operators: gt_, lt_, gte_, lte_, ne_, in_
- `GOAPPlanner` â€” plan(state, goals, actions), heuristic(), learn_from_outcome()
- `PlanTask` â€” task_id, name, action, dependencies, rollback
- `PlanExecution` â€” plan_id, status, task_results, ordered_task_ids

**A* Algorithm**: State space search, heuristic = estimated remaining cost, action cost learning from success/failure history.

### 4.9 Decision Engine (decision_engine.py, decision_adaptive.py)

**Purpose**: Central autonomous decision-making with rule evaluation, guardrails, risk scoring, and auditability.

**Key Classes**:
- `DecisionType` â€” PRICING, ADS, INVENTORY, CUSTOMER_SERVICE, ALERTS, EXPERIMENTS, METADATA
- `DecisionPriority` â€” CRITICAL(1), HIGH(2), NORMAL(3), LOW(4)
- `DecisionStatus` â€” PENDING, APPROVED, REJECTED, EXECUTED, REVERTED
- `RiskLevel` â€” NEGLIGIBLE(0) through CRITICAL(4)
- `DecisionEngine` â€” evaluate_signals(), _evaluate_rule(), _apply_guardrails(), _prioritize_decisions()
- `AdaptiveRule` â€” Self-tuning rule with weight adjustment from outcomes
- `AdaptiveRuleEngine` â€” evaluate(), _calculate_weight_adjustment(), _prune_rules()
- `FeedbackLoop` â€” process_result(), adapt() (adjust > detect > suggest > prune)

### 4.10 Dashboard (dashboard.py)

**Purpose**: Web-based administration dashboard (FastAPI + Chart.js) with 30+ REST endpoints and WebSocket streaming.

**Endpoints**: /api/health, /api/status, /api/dashboard/metrics, /api/goap-graph, /api/profitability, /api/skills, /api/ab-tests, /ws/stream, /metrics (Prometheus)

### 4.11 Skills System (skills/)

**Purpose**: Modular plugin architecture. Each skill is an autonomous capability with preconditions/effects for GOAP planning.

**Key Files**:
- registry.py â€” Skill base class + SkillRegistry with DAG resolution
- orchestrator.py â€” SkillOrchestrator for DAG-scheduled execution
- sandbox.py â€” Isolated execution environment
- loader.py â€” Dynamic skill loading
- marketplace.py â€” Community skill marketplace
- ab_testing.py â€” A/B test framework for skill variants
- canary.py â€” Gradual rollout deployment

**Built-in Skills**: pricing_skill, inventory_skill, order_skill, browser_skill, support_skill, goal_synthesizer, goal_nl

### 4.12 Plugin System (plugin_system.py, plugin_marketplace.py, plugin_sdk.py)

**Purpose**: Third-party extension framework with 20+ lifecycle hooks.

**Key Classes**:
- `PluginManifest` â€” name, version, description, author, dependencies, hooks, permissions
- `Plugin` (ABC) â€” on_load, on_unload, on_cycle_start, on_decision, on_skill_executed, plus 15+ more hooks
- `PluginManager` â€” discover, load_all, call_hook, install_plugin, uninstall_plugin

### 4.13 Workers (workers.py, workers_management.py)

**Purpose**: Event-driven worker framework implementing actor pattern.

**Key Classes**:
- `BaseWorker` (ABC) â€” subscribe(), on_start(), on_stop(), handle(event)
- `DecisionWorker` â€” Processes DecisionSignalEvent
- `OutcomeWorker` â€” Records OutcomeRecordedEvent
- `MetricWorker` â€” Processes MetricUpdateEvent
- `NotificationWorker` â€” Handles AlertEvent dispatch

### 4.14 Shopee Integration

**ShopeeClient (client.py)**: Complete HTTP client with HMAC-SHA256 signing, rate limiting, circuit breaking, retry, distributed tracing, token lifecycle management. Covers all Shopee Open Platform v2 endpoints.

**Endpoint Catalog (endpoints.py)**: 120+ endpoints across 12 families (Auth, Shop, Product, Order, Logistics, Payment, Promotion, Media, Push, Returns, ShopCategory, GlobalProduct).

**SellerCenter (seller_center_full.py)**: Browser automation for operations not available through Open API. Unified wrapper around Playwright and CDP. Supports product listing, order shipping, bulk price/stock updates, performance monitoring.

**Auth (auth.py)**: HMAC-SHA256 request signing, OAuth authorization URL generation, code-to-token exchange.

### 4.15 Pricing (pricing_automation.py)

**Purpose**: ML-based dynamic pricing engine with scikit-learn gradient boosting regression and rule-based fallback. 27 engineered features including price ratios, demand trends, margins, stock levels, competitor data.

### 4.16 Campaign Manager (campaign_manager.py)

**Purpose**: CRUD for Shopee promotional campaigns â€” bundle deals, vouchers, add-on deals.

### 4.17 Chat (chat_auto.py)

**Purpose**: Automated customer chat with sentiment analysis, template replies, LLM enhancement, and cross-sell injection.

### 4.18 Telegram (telegram_bot.py, telegram_narrator.py)

**Purpose**: Remote control via Telegram commands + push notifications.

**Bot Commands**: /start, /status, /orders, /products, /profit, /decision, /approve, /reject, /skill, /backup, /health, /activity. Inline keyboards for approval workflows.

### 4.19 Vision (vision.py, vision_analysis.py)

**Purpose**: Computer vision â€” OCR, product image quality assessment, visual attribute detection using Pillow + OpenCV.

### 4.20 Reporting (reporting.py, weekly_report.py)

**Purpose**: Multi-format report generation (JSON, CSV, PDF, Excel) with weekly executive summaries.

### 4.21 Backup (backup.py)

**Purpose**: Compressed ZIP backups of config, secrets, reports, databases. Configurable retention, integrity verification, restore drill.

### 4.22 Webhook (webhook_server.py, webhook_handlers.py, webhooks.py)

**Purpose**: HTTP webhook server for Shopee Set Push and MediaSpace callbacks with HMAC verification, readiness guard, auto-heal, digest mode.

### 4.23 Monitoring (monitoring.py, healthcheck_monitor.py, alerts.py)

**Purpose**: Rolling window metrics, health checks (Ollama, Shopee API, Seller Center, disk space, tokens, backups), alert generation and dispatch.

### 4.24 Security (security_audit.py, secrets_rotation.py)

**Purpose**: Environment auditing, token lifecycle management, secret scanning, file permission checks, dependency vulnerability scanning.

### 4.25 Memory/Learning (cognitive_memory.py, learning_system.py)

**Purpose**: SQLite-backed outcome storage, long-term memory with reflections, vector-based semantic search, learning reports with pattern detection.

### 4.26 Vector Store (vector_store.py, vector_store_annoy.py, vector_store_faiss.py)

**Purpose**: Semantic search over decision history. Three backends with common interface: InMemory (default), Annoy (persistent ANN), FAISS (GPU-accelerated).

### 4.27 Cache (api_cache.py, api_cache_redis.py)

**Purpose**: File-based API caching with configurable TTL (30 days default). Optional Redis backend.

### 4.28 Supporting Components

**Schema Migrations**: Versioned SQLite schema migration with rollback support. 10+ migrations covering all tables.

**Graceful Shutdown**: Signal handler with ordered cleanup callbacks and per-service timeout.

**Circuit Breaker**: FSM (CLOSED > OPEN > HALF_OPEN > CLOSED) with configurable thresholds.

**Rate Limiter**: Token bucket algorithm per endpoint family.

**Retry**: Exponential backoff with jitter, configurable attempts and delays.

**Multi-Tenant**: Thread-isolated store contexts with TenantConfig and TenantManager.

**i18n**: Internationalization with en_US and pt_BR locales (200+ keys each).

**CLI Completion**: Shell autocomplete generation (bash/zsh).

**Self-Healing**: Auto-recovery for Ollama, cookies, failed operations, circuit breakers.

---

## 5. Data Design

### 5.1 Database Schema (SQLite)

#### memory_outcomes table (cognitive_memory.db / goap_learning.db)

```sql
CREATE TABLE IF NOT EXISTS memory_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL,
    rule_id TEXT NOT NULL DEFAULT '',
    executed_at TEXT NOT NULL,
    outcome_type TEXT NOT NULL DEFAULT 'unknown',
    impact_realized REAL,
    margin_change REAL,
    revenue_change REAL,
    satisfaction_change REAL,
    reversals INTEGER DEFAULT 0,
    feedback TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '{}'
);
CREATE INDEX idx_outcomes_executed_at ON memory_outcomes(executed_at);
CREATE INDEX idx_outcomes_rule_id ON memory_outcomes(rule_id);
CREATE INDEX idx_outcomes_decision_id ON memory_outcomes(decision_id);
```

#### costs table (goap_learning.db)

```sql
CREATE TABLE IF NOT EXISTS costs (
    action_name TEXT PRIMARY KEY,
    current_cost REAL NOT NULL DEFAULT 1.0,
    base_cost REAL NOT NULL DEFAULT 1.0,
    executions INTEGER NOT NULL DEFAULT 0,
    successes INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    last_updated TEXT NOT NULL DEFAULT ''
);
```

#### cost_history table

```sql
CREATE TABLE IF NOT EXISTS cost_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_name TEXT NOT NULL,
    old_cost REAL NOT NULL,
    new_cost REAL NOT NULL,
    success INTEGER NOT NULL,
    timestamp TEXT NOT NULL
);
```

#### action_outcomes table

```sql
CREATE TABLE IF NOT EXISTS action_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_name TEXT NOT NULL,
    success INTEGER NOT NULL,
    cost REAL NOT NULL,
    elapsed_ms REAL NOT NULL DEFAULT 0,
    timestamp TEXT NOT NULL
);
```

#### notes table (long-term memory)

```sql
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

#### schema_migrations table

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    checksum TEXT NOT NULL DEFAULT '',
    duration_ms REAL DEFAULT 0
);
```

#### plan_store tables (plan_store.db)

```sql
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    state_json TEXT NOT NULL,
    goals_json TEXT NOT NULL,
    actions_json TEXT NOT NULL,
    total_cost REAL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT DEFAULT 'draft',
    tags TEXT DEFAULT '',
    version INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS plan_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    goals_json TEXT NOT NULL,
    action_sequence TEXT NOT NULL,
    category TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plan_executions (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT,
    finished_at TEXT,
    result_json TEXT DEFAULT '{}',
    error TEXT DEFAULT ''
);
```

#### decisions and decision_outcomes tables

```sql
CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    priority TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    risk_level TEXT DEFAULT 'low',
    rule_id TEXT,
    context_json TEXT,
    reasoning TEXT,
    created_at TEXT NOT NULL,
    executed_at TEXT,
    reverted_at TEXT
);
CREATE TABLE IF NOT EXISTS decision_outcomes (
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL,
    outcome_type TEXT NOT NULL,
    impact_value REAL,
    confidence REAL DEFAULT 1.0,
    metadata_json TEXT DEFAULT '{}',
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (decision_id) REFERENCES decisions(id)
);
CREATE TABLE IF NOT EXISTS decision_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_type TEXT NOT NULL,
    total_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    avg_impact REAL DEFAULT 0,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL
);
```

#### event_store table

```sql
CREATE TABLE IF NOT EXISTS event_store (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    data_json TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL,
    processed_at TEXT
);
CREATE INDEX idx_events_type ON event_store(event_type);
CREATE INDEX idx_events_status ON event_store(status);
CREATE INDEX idx_events_created ON event_store(created_at);
```

#### conversations and messages tables

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    customer_name TEXT DEFAULT '',
    status TEXT DEFAULT 'active',
    source TEXT DEFAULT 'shopee_chat',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sentiment TEXT DEFAULT 'neutral',
    is_auto_reply INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);
```

#### plugin_registry table

```sql
CREATE TABLE IF NOT EXISTS plugin_registry (
    name TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    description TEXT DEFAULT '',
    author TEXT DEFAULT '',
    enabled INTEGER DEFAULT 1,
    hooks TEXT DEFAULT '[]',
    dependencies TEXT DEFAULT '[]',
    installed_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

#### backup_log table

```sql
CREATE TABLE IF NOT EXISTS backup_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backup_name TEXT NOT NULL,
    size_bytes INTEGER DEFAULT 0,
    file_count INTEGER DEFAULT 0,
    checksum TEXT,
    status TEXT DEFAULT 'completed',
    created_at TEXT NOT NULL,
    error_details TEXT DEFAULT ''
);
```

### 5.2 Vector Store Schema

Each indexed item: doc_id (string), vector (128-dimensional float array), metadata (JSON with decision_id, rule_id, decision_type, outcome_type, impact_realized, timestamp, tags).

### 5.3 Cache Schema

Files stored as JSON in reports/api_cache/: {_cached_at (timestamp), _ttl_days, _cached_at_iso, data (original response)}.

### 5.4 Filesystem Layout

```
agente/
+-- .env (secrets, excluded from git)
+-- .env.example (template)
+-- pyproject.toml (project metadata)
+-- docker-compose.yml (Docker deployment)
+-- Dockerfile
+-- shopee_agent/ (main package, 137+ files)
|   +-- cli.py (3913 lines, main CLI entry)
|   +-- laura_daemon.py (1146 lines, daemon)
|   +-- client.py (2970 lines, Shopee API client)
|   +-- dashboard.py (1913 lines, web dashboard)
|   +-- telegram_bot.py (2461 lines, Telegram)
|   +-- endpoints.py (1264 lines, API catalog)
|   +-- event_bus.py (468 lines, async events)
|   +-- goap_planner.py (474 lines, GOAP planner)
|   +-- decision_engine.py (817 lines, decision engine)
|   +-- decision_adaptive.py (624 lines, adaptive rules)
|   +-- seller_center_full.py (1509 lines, SC automation)
|   +-- pricing_automation.py (683 lines, ML pricing)
|   +-- cognitive_memory.py (557 lines, memory system)
|   +-- plugin_system.py (498 lines, plugin framework)
|   +-- workers.py (573 lines, event workers)
|   +-- llm_providers.py (593 lines, LLM abstraction)
|   +-- autonomous_loop.py (562 lines, autonomous cycle)
|   +-- skills/ (25 files, skill system)
|   +-- cli_commands/ (17 files, CLI handlers)
|   +-- 50+ additional module files
+-- tests/ (108 test files)
+-- logs/ (auto-created, rotating logs)
+-- reports/ (auto-created, 50+ report files)
+-- secrets/ (auto-created, encrypted credentials)
+-- backups/ (auto-created, ZIP archives)
+-- data/ (auto-created, SQLite databases)
+-- plugins/ (third-party extensions)
+-- frontend/dist/ (dashboard frontend)
```

### 5.5 Configuration Schema (.env)

70+ environment variables across 12 categories:

| Category | Count | Key Variables |
|----------|-------|---------------|
| Shopee API | 6 | PARTNER_ID, PARTNER_KEY, REDIRECT_URL, BASE_URL, SHOP_ID, TOKENS |
| LLM/Ollama | 6 | ENABLED, MODEL, HOST, PORT, TIMEOUT, ALLOW_PAID |
| Daemon | 4 | INTERVAL, BACKUP_INTERVAL, AUTO_LOGIN_INTERVAL, PRICING_CYCLE |
| Telegram | 8 | BOT_TOKEN, CHAT_ID, NARRATOR, LEVEL, ALLOWED_CHAT, POLL/SLEEP |
| Profitability | 10 | ENABLED, EXECUTE, COOLDOWN, MARGIN, REFUND_RATE, ROAS, KILL_SWITCH |
| Webhook | 15 | HOST, PORT, PATH, SECRET, TIMEOUT, RETRY, GUARD, HEAL, AUDIT |
| Metrics | 14 | RETENTION, DIGEST, SCORE_WEIGHTS, GUARD, AUTO_REMEDIATE, WEEKLY |
| Backup | 5 | RETENTION, VERIFY_AGE, RESTORE_AGE, SNAPSHOT, REPORT |
| Health | 7 | MAX_LOG, BACKUPS, SUCCESS_AGE, WATCHDOG, AUTO_HEAL, NOTIFY |
| Vector Store | 8 | BACKEND, DIM, ANNOY_PATH, FAISS_PATH, BACKGROUND_BUILD, INTERVAL |
| Directories | 7 | REPORTS, LOGS, SECRETS, BACKUPS, DATA, SKILLS, VISION |
| Seller Center | 5 | GMAIL_CREDS, GMAIL_TOKEN, SC_CREDS, SC_COOKIES, CDP_WS_URL |

---

## 6. External Interface Design

### 6.1 Shopee API Integration

Base URL: https://partner.shopeemobile.com. Authentication via HMAC-SHA256 signing with Partner ID + Key + OAuth2 access token. Rate limiting via token bucket per endpoint family. 120+ endpoints across 12 families. Token auto-refresh every 3 hours.

### 6.2 LLM Provider Interfaces

Common interface (generate, analyze, count_tokens). Providers: Ollama (default, HTTP to localhost:11434), OpenAI (ChatGPT API), Anthropic (Claude API). Auto-detected at startup with fallback chain.

### 6.3 Telegram Bot API

Long-polling with getUpdates. 12 bot commands with inline keyboard callbacks. Configurable polling timeout (30s), sleep interval (1s), allowed chat ID whitelist.

### 6.4 Email (SMTP/Gmail)

Gmail OAuth2 with auto-refreshing tokens. Generic SMTP support. HTML/plain text composition with PDF/CSV attachments.

### 6.5 Web Dashboard (REST + WebSocket)

30+ REST endpoints at port 8888. WebSocket at /ws/stream for real-time events. Prometheus metrics at /metrics. PWA push notifications with subscription management.

---

## 7. Security Design

### 7.1 Authentication & Authorization

Shopee API: HMAC-SHA256 + OAuth2 tokens with 3-hour refresh cycle. Dashboard: optional API key, localhost binding. Telegram: bot token + chat ID whitelist. Plugins: manifest-declared permissions with enforcement.

### 7.2 Secrets Management

Secrets stored in secrets/ directory as JSON files. Token lifecycle management with status tracking (ACTIVE > EXPIRING_SOON > EXPIRED > REFRESHING > REFRESH_FAILED). Automatic refresh before expiration. Thread-safe operations with reentrant lock.

### 7.3 API Security

HMAC-SHA256 request signing for all Shopee calls. Webhook HMAC-SHA256 signature verification. Rate limiting, circuit breaking, input validation.

### 7.4 Data Protection

All data stored locally. HTTPS for all external API calls. File permission verification via security audit. Configurable retention policies with automatic pruning.

### 7.5 Audit Logging

Decision audit to decision_log.jsonl (full decision lifecycle). EventBus WAL journaling. Security audit reports with secret scanning, permission checks, dependency vulnerability scanning.

---

## 8. Quality Assurance

### 8.1 Testing Strategy

Multi-layer: unit tests (mocked dependencies), integration tests (real SQLite/JSONL), E2E tests (simulated Shopee API), regression tests, performance benchmarks.

### 8.2 Test Categories

108 test files covering: core modules (45+), decision engine (12+), GOAP planner (15+), event bus (5+), skills (8+), vector store (5+), integration (15+), E2E (5+), regression (10+), benchmark (3+).

### 8.3 CI/CD Pipeline

GitHub Actions: CI (python setup, test, coverage) and Lint (ruff, mypy, pre-commit). Test config: pytest with -x -q --tb=short, asyncio support, coverage reporting.

### 8.4 Code Quality

Ruff: line-length=120, target py312, select E/F/W/I/N/UP/B/SIM. Mypy: strict optional checks, skip untyped defs, exclude generated code. Pre-commit: ruff, mypy, whitespace, EOF, YAML/JSON validation.

### 8.5 Performance Benchmarks

GOAP planning < 500ms, decision evaluation > 100 rules/sec, vector search p99 < 50ms, HTTP client < 200ms, event bus > 1000 events/sec, dashboard p95 < 100ms, SQLite < 10ms, memory < 500MB RSS.

---

## 9. Deployment

### 9.1 Production Architecture

```
Internet > Cloudflare Tunnel (optional) > Nginx Reverse Proxy (port 80/443)
  > Laura Daemon (cycle loop) + Laura Dashboard (FastAPI :8888) + Webhook Server (:8765)
  > Ollama Server (:11434) + SQLite DBs + Filesystem (reports/, logs/)
Optional: Redis Cache (:6379), Ollama GPU Node (remote)
```

### 9.2 System Requirements

Minimum: 2-core CPU, 4GB RAM, 1GB storage, Python 3.12+. Recommended: 4+ cores, 8GB RAM, 10GB storage, NVIDIA GPU 4GB+ VRAM.

### 9.3 Installation Methods

1. pip install: git clone > venv > pip install -e ".[dev]"
2. Docker Compose: docker-compose up --build (Laura + Ollama + optional Redis)
3. Systemd service unit with after=network.target ollama.service

### 9.4 Docker Deployment

Three services: laura (build ., ports 8888, volumes reports/plugins/data), ollama (image ollama/ollama, port 11434, volume ollama_data), redis (image redis:7-alpine, port 6379, volume redis_data, profile redis).

### 9.5 Systemd Service

[Unit] Description=Laura Autonomous Shopee Agent, After=network.target ollama.service. [Service] Type=simple, ExecStart=laura daemon, Restart=on-failure. [Install] WantedBy=multi-user.target.

### 9.6 Nginx Reverse Proxy

Proxy / to localhost:8888 with WebSocket upgrade for /ws/stream. Proxy /metrics for Prometheus scraping.

### 9.7 Monitoring & Alerting

Internal: rolling window metrics, health score (0-100), watchdog process. Prometheus: 10+ metrics (health, cycles, decisions, skills, events, API latency, memory). Alerts: Telegram, Slack/Discord webhooks, email.

### 9.8 Backup & Recovery

Automatic ZIP backups every 24h. Sources: .env, secrets/, reports/, data/. Retention: 14 days. Integrity verification with checksums. Restore drill automation.

### 9.9 Upgrade Procedures

git pull > pip install -e ".[all]" > laura schema migrate > systemctl restart laura. Rollback: git revert > pip install > laura schema rollback > restart.

---

## 10. Appendix

### 10.1 Full CLI Command Reference

140+ commands organized in categories: Authentication & Setup (8), API Gateway (4), Products (4), Orders (8), Logistics (3), Finance (2), Promotions (10), Media (6), LLM/Ollama (4), Daemon & Automation (5), Skills (20), A/B Testing & Canary (7), GOAP Planning (17), Decision Engine (10), Goal Management (5), Analytics & Reports (15), Webhook (2), Seller Center (10), Chat & Communication (8), Infrastructure (12), System & Maintenance (10).

### 10.2 Environment Variables Reference

Complete reference of 70+ variables in Section 5.5. Summary by category with counts and key variables.

### 10.3 REST API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/health | System health check |
| GET | /api/status | Consolidated status |
| GET | /api/dashboard/metrics | Shop metrics overview |
| GET | /api/dashboard/recent-events | Recent events |
| GET | /api/profitability | Profitability analysis |
| GET | /api/skills | Registered skills |
| GET | /api/skill-health | Skills health |
| GET | /api/goap-graph | GOAP plan graph |
| GET | /api/goap-timeline | Plan timeline |
| GET | /api/goap-cost-history | Plan cost history |
| GET | /api/goal-synthesize | Goal synthesis |
| GET | /api/ab-tests | A/B test list |
| GET | /api/ab-tests/stats | A/B test stats |
| POST | /api/approve/rating/{idx} | Approve rating reply |
| POST | /api/reject/rating/{idx} | Reject rating reply |
| POST | /api/approve/chat/{idx} | Approve chat reply |
| POST | /api/reject/chat/{idx} | Reject chat reply |
| POST | /api/push/subscribe | PWA subscription |
| POST | /api/push/send | Send push |
| GET | /api/ws-token | WebSocket token |
| GET | /ws/stream | WebSocket stream |
| GET | /metrics | Prometheus metrics |

### 10.4 WebSocket Event Reference

Events streamed via /ws/stream: metric_update, decision_alert, cycle_complete, skill_executed, error_occurred, backup_completed, health_change.

### 10.5 Hook Reference (Plugin System)

20+ hooks: on_load, on_unload, on_cycle_start, on_cycle_end, on_decision, on_decision_executed, on_skill_executed, on_skill_register, on_telegram_command, on_telegram_message, on_webhook_event, on_alert, on_metric_update, on_startup, on_shutdown, on_backup, on_restore, on_plugin_load, on_plugin_unload, on_error.

### 10.6 Error Codes

| Code | Description |
|------|-------------|
| E001 | Configuration error (missing env var) |
| E002 | Authentication failure (invalid token) |
| E003 | API rate limit exceeded |
| E004 | Circuit breaker open |
| E005 | LLM provider unavailable |
| E006 | Database migration required |
| E007 | Backup integrity check failed |
| E008 | Plugin load failure |
| E009 | Event bus capacity exceeded |
| E010 | Graceful shutdown timeout |

### 10.7 Glossary

| Term | Definition |
|------|-----------|
| Agent | Autonomous software entity that perceives environment and takes actions |
| Skill | Modular capability with preconditions, effects, and execution logic |
| Plan | Ordered sequence of actions to achieve goals |
| Goal | Desired state expressed as key-value conditions |
| Cycle | Single iteration of the autonomous loop |
| Provider | External service (LLM, API, webhook) integrated via adapter |
| Tenant | Isolated store configuration in multi-store deployments |
| Autopilot | Fully automated decision execution without human approval |
| Canary | Gradual rollout of new skill versions to subset of operations |
| Sandbox | Isolated environment for skill testing without production impact |
---

## Expanded Component Specifications (Detailed)

### 4.29 Autonomous Loop (autonomous_loop.py)

**Purpose**: Central orchestrator that runs the autonomous decision-execution-learn cycle. Called by LauraDaemon every cycle interval.

**Dependencies**: ShopeeClient, DecisionIntegrator, DecisionEngine, analytics modules (optional).

**Key Classes**:
- AutonomousLoop — Main cycle orchestrator
  - un_cycle() — Collect context, evaluate decisions, execute actions, run GOAP, record outcomes, learn
  - _collect_context() — Gather metrics from orders, products, analytics, competitor data
  - _evaluate_decisions(context) — Feed context through DecisionEngine
  - _execute_decisions(decisions) — Execute priority-ordered decisions
  - _run_goap_planning(context) — Synthesize goals and run GOAP planner
  - _run_learning_cycle() — Trigger learning system evaluation
  - _generate_report() — Generate cycle summary for EventBus and Telegram

**Cycle Flow**:
`
run_cycle():
  1. context = _collect_context()
     - Orders, products, financials, analytics, competitor data, inventory
  2. decisions = _evaluate_decisions(context)
     - DecisionEngine.process_signals(context)
  3. _execute_decisions(decisions)
     - SkillOrchestrator.execute(decision.action)
  4. goals = _synthesize_goals(context)
     - GoalManager.synthesize_from_kpis(context)
  5. plan = GOAPPlanner.plan(current_state, goals, available_skills)
  6. _execute_plan(plan)
     - Execute each action, record outcomes
  7. _run_learning_cycle()
     - LearningSystem.process_outcomes(outcomes)
  8. _generate_report()
     - Cycle summary output
`

### 4.30 Strategic Planner (strategic_planner.py)

**Purpose**: High-level strategic planning for long-term goals beyond individual GOAP plans.

**Dependencies**: GoalManager, EconomicBrain, CompetitiveIntelligence, PredictiveAnalytics.

**Key Classes**:
- Goal — name, type (strategic/tactical/operational), target_value, current_value, deadline, priority, progress
- StrategicPlan — plan_id, goals, strategy, timeline, resource_allocation, risk_assessment
- StrategicPlanner — Multi-cycle strategic planning
  - nalyze_market_position() — SWOT analysis
  - define_strategic_goals() — Long-term goals (30-day horizon)
  - create_strategic_plan(goals) — Phased plan with milestones
  - evaluate_progress() — Progress tracking against strategic KPIs

### 4.31 Economic Brain (economic_brain.py)

**Purpose**: Financial analysis and profitability engine. Computes real-time P&L, forecasts revenue.

**Dependencies**: ShopeeClient, pricing_automation, predictive_analytics.

**Key Classes**:
- FinancialSnapshot — Revenue, costs (product/shipping/fees/ads), profit, margin
- ProfitabilityAnalysis — Per-product profitability with contribution margin
- Forecast — Revenue forecast for 7/14/30 day horizons
- EconomicBrain — Main financial analysis
  - compute_snapshot() — Real-time P&L
  - orecast_revenue(days) — Time-series forecasting
  - get_profitability_report() — Full breakdown by product
  - identify_loss_leaders() — Products with negative margin
  - suggest_optimizations() — Financial optimization recommendations

### 4.32 Predictive Analytics (predictive_analytics.py)

**Purpose**: ML-based sales forecasting with 30-day horizon.

**Dependencies**: numpy, scikit-learn (optional).

**Key Features**:
- Daily, weekly, monthly sales forecasts
- Seasonal decomposition (trend, weekly pattern, residual)
- Confidence intervals for predictions
- Anomaly detection in sales patterns

### 4.33 Competitive Intelligence (competitive_intelligence.py)

**Purpose**: Monitor competitor pricing, products, market trends.

**Dependencies**: ShopeeClient, site_scraper, shopee_search_scraper.

**Key Classes**:
- CompetitiveIntelligence — Competitor monitoring
  - scan_competitors(shop_ids) — Scrape competitor data
  - compare_pricing(my_products) — Price comparison matrix
  - detect_price_changes() — Alert on price movements
  - generate_summary() — Competitive landscape report

### 4.34 A/B Test Automator (ab_test_automator.py)

**Purpose**: Statistical A/B testing for comparing skill variants.

**Dependencies**: scipy (optional), skills/ab_testing.py.

**Key Classes**:
- ABTestConfig — name, control, treatment, traffic_split, metrics, min_sample_size, significance_level
- ABTestResult — status, metrics, p_value, effect_size, recommendation
- ABTestAutomator — Test lifecycle: start, record_observation, analyze, auto_promote, rollback

### 4.35 Agent Orchestrator (agent_orchestrator.py)

**Purpose**: Multi-agent coordination for complex tasks.

**Dependencies**: AutonomousLoop, SkillOrchestrator, EventBus.

**Key Classes**:
- Agent — role, capabilities, task_queue, state
- AgentOrchestrator — decompose_task, assign_agents, monitor_progress, reconcile_results, handle_failure

### 4.36 Plan Store (plan_store.py)

**Purpose**: Persistent GOAP plan storage with full lifecycle management.

**Dependencies**: SQLite, json.

**Key Classes**:
- PlanStore — save_plan, load_plan, list_plans, delete_plan, compare_plans, export_plan, import_plan

### 4.37 Plan Templates (plan_templates.py)

**Purpose**: Pre-built templates for common scenarios.

**Key Classes**:
- PlanTemplate — name, description, goals, action_sequence, category
- TemplateLibrary — Built-in and user-defined templates
- plan_from_template(name, context) — Instantiate with current state

### 4.38 Plan Visualizer (plan_viz.py)

**Purpose**: Generate Mermaid diagrams and Gantt charts.

**Key Functions**:
- 	o_mermaid(plan), 	o_gantt(plan), 	o_json(plan), export_format(plan, format)

### 4.39 Self-Healing (self_healing.py)

**Purpose**: Automatic failure detection and recovery.

**Key Classes**:
- SelfHealingCoordinator — check_and_heal, heal_component
  - heal_ollama() — Restart Ollama
  - heal_cookies() — Refresh SC cookies
  - heal_skills() — Reload skills
  - heal_circuit_breakers() — Reset circuits
  - heal_event_bus() — Reinitialize bus

### 4.40 Anomaly Detector (anomaly_detector.py)

**Purpose**: Statistical anomaly detection.

**Key Functions**:
- detect_metric_anomalies(metric_window) — Z-score based
- detect_order_anomalies(orders) — Pattern deviation
- detect_price_anomalies(prices) — Price deviation
- detect_refund_anomalies(refunds) — Refund pattern

### 4.41 Sentiment Analyzer (sentiment_analyzer.py)

**Purpose**: Customer message and review sentiment analysis.

**Key Functions**:
- nalyze_sentiment(text) — Positive/negative/neutral
- nalyze_review(review) — Rating sentiment
- extract_key_phrases(text) — Important phrases
- detect_urgency(text) — Urgency level

### 4.42 Insights LLM (insights_llm.py)

**Purpose**: LLM-powered business insights.

**Key Functions**:
- generate_trend_insight(trend_data) — NL trend explanation
- generate_anomaly_explanation(anomaly) — Anomaly explanation
- generate_recommendations(context) — Smart recommendations
- generate_executive_summary(metrics) — Executive summary

### 4.43 Goal Management (goal_management.py, goal_library.py)

**Purpose**: Goal lifecycle with synthesis from KPIs.

**Key Classes**:
- GoalManager — synthesize_from_kpis, translate_from_nl, get_priority_ranking, check_completion
- GoalLibrary — Templates: margin_protection, inventory_optimization, price_competitiveness, customer_satisfaction

### 4.44 Cost Predictor (cost_predictor.py)

**Purpose**: LLM-based plan cost estimation.

**Key Functions**:
- predict_plan_cost(plan) — Estimate API calls and time
- predict_action_cost(action) — Individual cost estimation

### 4.45 Proactive Goals (proactive_goals.py)

**Purpose**: Auto-suggest goals from opportunities/risks.

**Key Functions**:
- detect_opportunities(context), detect_risks(context), suggest_goals(opps, risks)

### 4.46 Federated Learning (federated_learning.py, federated_learning_v2.py)

**Purpose**: Collaborative learning across tenants without sharing raw data.

**Key Classes**:
- FederatedLearningCoordinator — train_local, share_update, aggregate_updates, distribute_global_model

### 4.47 Tracing (tracing.py)

**Purpose**: Distributed tracing with context propagation.

**Key Classes**:
- TraceContext — correlation_id, span_id, parent_span_id, endpoint, timing
- Tracer — start_trace, start_span, end_span, get_trace_context

### 4.48 Persistent State (persistent_state.py)

**Purpose**: Thread-safe JSON-backed persistent state.

**Key Classes**:
- PersistentState — get, set, delete, save (atomic), reload. Thread-safe with RLock.

### 4.49 Metrics Exporter (metrics_exporter.py)

**Purpose**: Prometheus metrics export.

**Key Metrics**: health_score, cycle_count, cycle_duration, decisions_total, skills_executed_total, events_total, api_requests_total, api_latency, memory_usage.

### 4.50 Realtime Export (realtime_export.py)

**Purpose**: WebSocket-based real-time data export.

**Key Functions**: subscribe_to_updates, stream_to_websocket, export_batch.

### 4.51 Support Center (support_center.py)

**Purpose**: Automated customer support ticket management.

**Key Classes**:
- SupportCase — id, customer, issue_type, status, priority, messages
- SupportCenter — create_case, auto_classify, suggest_response, escalate, close_case

### 4.52 Auto Login (auto_login.py)

**Purpose**: SC session renewal via Chrome DevTools Protocol.

**Key Functions**: renovar_cookies_via_cdp, login_via_cdp_completo, check_session_valid.

### 4.53 Token Scheduler (token_scheduler.py)

**Purpose**: Scheduled Shopee API token refresh.

**Key Functions**: schedule_refresh, check_token_health, emergency_refresh.

### 4.54 Rating Reply (rating_reply.py)

**Purpose**: Automated product rating responses.

**Key Functions**: processar_avaliacoes_pendentes, generate_reply, approve_and_send.

### 4.55 Email Manager (email_manager.py)

**Purpose**: Send emails via SMTP with attachments.

**Key Functions**: send_email, send_report, send_alert.

### 4.56 Gmail OAuth (gmail_oauth.py)

**Purpose**: Gmail OAuth2 for OTP reading and email sending.

**Key Functions**: authenticate, read_otp, send_via_gmail.

### 4.57 Daily Resumo (resumo_diario.py)

**Purpose**: Daily operational summary to Telegram.

**Key Functions**: postar_resumo, deve_postar_agora.

### 4.58 Learned Actions (learned_actions.py)

**Purpose**: Persist learned action sequences.

**Key Classes**:
- LearnedAction — sequence, context, success_rate, confidence
- LearnedActionStore — store, retrieve, prune

### 4.59 Telegram Mini Apps (telegram_mini_apps.py)

**Purpose**: Telegram Mini App integration for interactive interfaces.

### 4.60 Telegram Web Setup (telegram_web_setup.py)

**Purpose**: Telegram Login widget for dashboard auth.

### 4.61 Charting & Visualization (charting_visualization.py)

**Purpose**: Chart.js config generation for interactive charts.

**Key Functions**: generate_bar_chart, generate_line_chart, generate_pie_chart, generate_heatmap, chart_dashboard.

### 4.62 Worker Bots (worker_bots.py)

**Purpose**: Legacy Telegram worker bot threads for command processing.

**Dependencies**: telegram_bot.py, client.py, seller_center.py.

**Key Functions**: _post, enviar_para_canal, _ensure_clients.

### 4.63 Workers Management (workers_management.py)

**Purpose**: Lifecycle management for background workers.

**Key Classes**:
- WorkersManager — start_workers, stop_workers, get_worker_status, pause_worker, resume_worker, restart_worker

### 4.64 VILU Workers (vilu_workers.py)

**Purpose**: Legacy worker system for Telegram channel posting.

**Key Functions**: _post, enviar_para_canal.

### 4.65 CLI Completion (cli_completion.py)

**Purpose**: Shell auto-completion generation.

**Key Functions**: build_parser, generate_completion, install_completion.

### 4.66 Schema Migrations Manager (schema_migrations.py)

**Purpose**: Versioned database migration system with rollback.

**Key Classes**:
- SchemaMigration — version, description, apply_sql, rollback_sql
- MigrationManager — apply_pending, rollback, current_version, list_migrations, create_migration

### 4.67 Multi-Tenant Manager (multi_tenant.py)

**Purpose**: Support for multiple stores with isolated state.

**Key Classes**:
- TenantConfig — store_id, shop_id, access_token, reports_dir, secrets_dir, db_dir
- TenantManager — register_tenant, switch_tenant, get_current_tenant, list_tenants, remove_tenant

### 4.68 i18n (i18n.py)

**Purpose**: Internationalization for dashboard and CLI.

**Supported Locales**: en_US, pt_BR (200+ keys each).

**Key Functions**: translate(key, locale), get_current_locale, set_locale.

### 4.69 Security Audit (security_audit.py)

**Purpose**: Comprehensive security checks.

**Key Classes**:
- SecurityAudit — run_all, check_env_secrets, check_file_permissions, check_dependencies, check_api_keys_in_code, check_https

### 4.70 Health Check Monitor (healthcheck_monitor.py)

**Purpose**: Periodic health check execution.

**Key Functions**: check_all, check_ollama, check_shopee_api, check_seller_center, check_disk_space, check_token_expiration, check_backup_age.

### 4.71 Alerts (alerts.py)

**Purpose**: Alert generation and dispatch.

**Key Classes**:
- AlertSeverity — INFO, WARNING, CRITICAL
- Alert — severity, title, message, timestamp, source, metadata

### 4.72 Alert Manager (monitoring.py AlertManager)

**Purpose**: Alert rule evaluation and dispatch to channels.

**Key Functions**: evaluate_rules, dispatch_alert, route_to_channel, acknowledge.

### 4.73 Plugin Marketplace (plugin_marketplace.py)

**Purpose**: Community plugin sharing hub.

**Key Functions**: search, publish, install, uninstall, rate, review.

### 4.74 Plugin SDK (plugin_sdk.py)

**Purpose**: Development toolkit for plugin authors.

**Key Features**: Plugin scaffolding generator, manifest validation, hook testing utilities, documentation generator.

### 4.75 Supply Chain Planner v2 (supply_chain_planner_v2.py)

**Purpose**: Enhanced supply chain with multi-echelon inventory optimization, demand sensing with ML, supplier risk scoring.

**Key Enhancements**:
- Multi-echelon: optimize inventory across warehouse/fulfillment/regional levels
- Demand sensing: real-time demand signal from search trends and competitor stockouts
- Supplier risk: score suppliers on lead time variance, quality, communication

### 4.76 Vision Analysis (vision_analysis.py)

**Purpose**: Marketplace Vision Analyzer for product image analysis.

**Dependencies**: Pillow, opencv-python-headless, pytesseract.

**Key Functions**:
- MarketplaceVisionAnalyzer — analyze product images, detect quality issues
- nalyze_items_visuals(items) — Batch visual analysis
- dump_visual_report(results) — Generate visual analysis report
- Caching at ~/.laura_vision_cache

### 4.77 Webhook Handlers (webhook_handlers.py)

**Purpose**: Event handlers for incoming webhook events.

**Key Functions**:
- handle_shopee_push(event) — Process Shopee Set Push notifications
- handle_mediaspace_event(event) — Process MediaSpace transcoding events
- Route events to EventBus for further processing

### 4.78 Webhook Helpers (webhooks.py)

**Purpose**: Outgoing webhook formatters for Slack and Discord.

**Key Classes**:
- SlackWebhook — format(alert) to Slack message format
- DiscordWebhook — format(alert) to Discord message format

### 4.79 Seller Center Browser (seller_center_browser.py)

**Purpose**: Low-level browser automation helpers.

**Key Functions**:
- ind_element, click, 	ype_text, wait_for_navigation, extract_table
- Wraps Playwright API for consistent error handling

### 4.80 Seller Center Actions (seller_center_actions.py)

**Purpose**: Reusable action sequences for Seller Center.

**Key Functions**:
- login_flow(credentials) — Complete login sequence
- 
avigate_to_products() — Navigate to product management
- 
avigate_to_orders() — Navigate to order management
- export_products() — Trigger CSV export
- update_price(item_id, price) — Change product price
- update_stock(item_id, quantity) — Change stock quantity


---

## Expanded Event Typing Hierarchy

All events inherit from the base `Event` dataclass:

```
Event (base)
  event_type: str
  timestamp: Optional[datetime]
  source: str

+-- DecisionSignalEvent
|     event_type: "decision.signal"
|     signal: Any
|     context: Any
|
+-- DecisionExecutedEvent
|     event_type: "decision.executed"
|     decision_id: str
|     rule_id: str
|     status: str
|     result: Any
|
+-- OutcomeRecordedEvent
|     event_type: "outcome.recorded"
|     decision_id: str
|     rule_id: str
|     outcome_type: str
|     impact_realized: Optional[float]
|     metadata: Dict[str, Any]
|
+-- GOAPPlanExecutedEvent
|     event_type: "goap.plan_executed"
|     actions: List[str]
|     total_cost: float
|     results: List[Dict[str, Any]]
|     all_ok: bool
|     state_snapshot: Dict[str, Any]
|
+-- CycleCompleteEvent
|     event_type: "cycle.complete"
|     cycle_id: str
|     duration_seconds: float
|     decisions_count: int
|     skills_executed: int
|     errors: List[str]
|
+-- AlertEvent
|     event_type: "alert.generated"
|     severity: str
|     title: str
|     message: str
|     alert_id: str
|     source_component: str
|
+-- MetricUpdateEvent
|     event_type: "metric.updated"
|     metric_name: str
|     value: float
|     tags: Dict[str, str]
|     timestamp: str
|
+-- SkillExecutedEvent
|     event_type: "skill.executed"
|     skill_name: str
|     status: str
|     duration_ms: float
|     result: Any
|     error: Optional[str]
|
+-- BackupEvent
|     event_type: "backup.completed"
|     backup_name: str
|     size_bytes: int
|     file_count: int
|     status: str
|
+-- HealthChangeEvent
|     event_type: "health.changed"
|     component: str
|     old_status: str
|     new_status: str
|     score: float
```

## Decision Engine Rule Syntax

Rules are Python expressions evaluated with a restricted globals dict:

SAFE_BUILTINS = {abs, all, any, bool, dict, enumerate, filter, float, int, isinstance, len, list, map, max, min, pow, range, round, sorted, str, sum, tuple, type, zip}

Example rules:
- Name: "match_competitor_price", Condition: margin_pct GREATER 25 and competitor_price LESS my_price, Action: reduce_price_to(competitor_price * 0.98), Priority: HIGH, Risk: MEDIUM
- Name: "pause_low_roas_ads", Condition: roas LESS min_roas and ad_spend GREATER 0, Action: pause_campaign(campaign_id), Priority: HIGH, Risk: MEDIUM
- Name: "low_stock_alert", Condition: stock_level LESS reorder_point, Action: generate_restock_order(item_id), Priority: NORMAL, Risk: LOW

## GOAP Planning Examples

### Example: Price Optimization Plan

```
current_state = {
    "margin_protected": False,
    "stock_checked": False,
    "competitor_checked": False,
    "prices_updated": False
}

goal_state = {
    "margin_protected": True,
    "stock_checked": True,
    "competitor_checked": True,
    "prices_updated": True
}

Available actions:
- check_margins: cost=1.0, preconditions={}, effects={"margin_protected": True}
- check_stock: cost=1.0, preconditions={}, effects={"stock_checked": True}
- scan_competitors: cost=2.0, preconditions={}, effects={"competitor_checked": True}
- update_prices: cost=3.0, preconditions={"competitor_checked": True, "margin_protected": True}, effects={"prices_updated": True}

A* plan: [check_margins, scan_competitors, update_prices, check_stock]
Total cost: 1.0 + 2.0 + 3.0 + 1.0 = 7.0
```

### Skill Declaration with GOAP Metadata

```python
class PricingSkill(Skill):
    name = "pricing_skill"
    risk_level = "MEDIUM"
    preconditions = {"competitor_checked": True, "margin_protected": True}
    effects = {"prices_updated": True}
    cost = 3.0
    priority = 1
    reverse_name = "pricing_rollback"
    sub_skills = ["margin_check_skill"]
    event_types = ["cycle.complete", "metric.updated"]
    schedule = "08:00"
    dependencies = ["inventory_skill"]
```

## Plugin System Hook Execution Flow

```
PluginManager.call_hook("on_cycle_start", context)
  |
  +-- For each loaded plugin (in registration order):
  |     +-- if plugin has on_cycle_start method:
  |     |     +-- Call plugin.on_cycle_start(context)
  |     |     +-- Catch exceptions (log, continue)
  |     +-- if plugin has on_cycle_start_filter method:
  |           +-- Call until first non-None return
  |
  +-- Return results dict {plugin_name: return_value}
```

## Filesystem Path Constants

### Reports Directory Key Files

| Path Constant | File | Purpose |
|--------------|------|---------|
| PROFITABILITY_LATEST | reports/laura_profitability_latest.json | Latest profitability analysis |
| PROFITABILITY_HISTORY | reports/laura_profitability_history.jsonl | Profitability history log |
| HEALTH_LATEST | reports/laura_health_latest.json | Latest health check results |
| DECISION_LOG | reports/decision_log.jsonl | Decision audit trail |
| DECISION_OUTCOMES | reports/decision_outcomes.jsonl | Decision outcomes log |
| GOAP_LEARNING | reports/goap_learning.json | GOAP learning state |
| GOAP_STATE | reports/goap_state.json | Current GOAP state |
| PLAN_STORE_DB | reports/plan_store.db | Persisted plans SQLite |
| ANNOY_INDEX | reports/annoy_index.ann | Annoy vector index |
| FAISS_INDEX | reports/faiss_index.faiss | FAISS vector index |
| COMPETITIVE_OFFERS | reports/competitive_offers.jsonl | Competitor price cache |
| PRODUCT_PRICES | reports/product_prices.json | Product price history |
| CHAT_OUTBOUND | reports/chat_outbound.jsonl | Outgoing chat messages |
| ALERTS_HISTORY | reports/laura_alerts_history.jsonl | Alert history |
| METRICS_SNAPSHOT | reports/laura_metrics.jsonl | Metrics snapshots |
| API_CACHE_DIR | reports/api_cache/ | Cached API responses |
| WEEKLY_PDFS_DIR | reports/weekly_pdfs/ | Generated PDF reports |
| APPROVALS_DIR | reports/approvals/ | Approval state files |

### Secrets Directory Key Files

| Path Constant | File | Purpose |
|--------------|------|---------|
| SELLER_CENTER_CREDENTIALS | secrets/seller_center_credentials.json | SC login credentials |
| SELLER_CENTER_COOKIES | secrets/seller_center_cookies.json | SC session cookies |
| GMAIL_CREDENTIALS | secrets/gmail_credentials.json | Gmail OAuth credentials |
| GMAIL_TOKEN | secrets/gmail_token.json | Gmail OAuth token |
| GOOGLE_CREDENTIALS | secrets/Credencial.Laura.json | Google API credentials |
| REPLIED_RATINGS | secrets/laura_replied_ratings.json | Already-replied ratings tracker |
| TELEGRAM_SETUP | secrets/telegram_setup.json | Telegram bot config |

## Configuration Loading Priority

1. Shell environment variables (highest priority)
2. .env file variables (set via os.environ.setdefault)
3. Default values in code (lowest priority)

The _load_env_file_if_present() function reads .env with setdefault semantics:
- Lines starting with "export " have the prefix stripped
- Quoted values (single or double quotes) are unquoted
- Whitespace around key=value is trimmed

## Request Signing Algorithm

Shopee API v2 request signing:

1. Prepare parameters:
   - partner_id (int)
   - timestamp (unix epoch seconds)
   - access_token (if authenticated)
   - shop_id (if authenticated)
   - request body (JSON, sorted keys)

2. Build base string:
   - If POST: base = timestamp + partner_id + path + sorted_json_body
   - If GET: base = timestamp + partner_id + path + sorted_query_string

3. Compute signature:
   - signature = HMAC-SHA256(partner_key, base).hexdigest().upper()

4. Build URL:
   - url = base_url + path + "?partner_id=X" + "&timestamp=Y" + "&sign=Z" + "&access_token=..."

5. Send request:
   - POST with JSON body
   - GET with query parameters

## Circuit Breaker Configuration Examples

```python
# Default configuration
CircuitBreakerConfig(
    failure_threshold=5,
    success_threshold=2,
    timeout_seconds=60,
    window_seconds=60,
    max_requests=100
)

# Strict configuration for critical endpoints
CircuitBreakerConfig(
    failure_threshold=3,
    success_threshold=3,
    timeout_seconds=120,
    window_seconds=30,
    max_requests=50
)

# Lenient configuration for non-critical operations
CircuitBreakerConfig(
    failure_threshold=10,
    success_threshold=1,
    timeout_seconds=30,
    window_seconds=300,
    max_requests=200
)
```

## Rate Limit Configuration Per Endpoint Family

| Endpoint Family | max_requests | window_seconds | rate_per_second |
|----------------|-------------|----------------|-----------------|
| Auth | 10 | 60 | 0.17 |
| Product | 30 | 60 | 0.50 |
| Order | 20 | 60 | 0.33 |
| Logistics | 15 | 60 | 0.25 |
| Promotion | 20 | 60 | 0.33 |
| Media | 10 | 60 | 0.17 |
| Shop | 30 | 60 | 0.50 |
| Payment | 10 | 60 | 0.17 |
| Push | 5 | 60 | 0.08 |
| Returns | 15 | 60 | 0.25 |
| GlobalProduct | 20 | 60 | 0.33 |
| ShopCategory | 20 | 60 | 0.33 |

## Retry Configuration

```python
RetryConfig(
    max_attempts=3,
    initial_delay_ms=100,
    max_delay_ms=5000,
    backoff_factor=2.0,
    jitter=True,
    retryable_exceptions=(ConnectionError, TimeoutError, HTTPError)
)
```

Retry with exponential backoff:
- Attempt 1: immediate
- Attempt 2: approximately 200ms (100 * 2.0 + jitter)
- Attempt 3: approximately 400ms (200 * 2.0 + jitter)
- Max delay capped at 5000ms

## Graceful Shutdown Sequence

1. Signal received (SIGINT/SIGTERM)
2. Set shutting_down flag (duplicate signals ignored)
3. Execute cleanup handlers in reverse registration order:
   - Stop EventBus (drain remaining events, flush WAL)
   - Stop workers (finish current task, no new tasks)
   - Stop webhook server (close connections, flush queue)
   - Stop Telegram bot (end polling loop)
   - Stop dashboard (close WebSocket connections)
   - Save all persistent state
   - Execute backup
   - Close database connections
4. Each handler has per-service timeout (default: 30s total)
5. Force exit if timeout exceeded

## Testing Infrastructure Details

### Test Configuration

```
[tool.pytest.ini_options]
testpaths = ["tests"]
filter_warnings = ["ignore::pytest.PytestUnhandledThreadExceptionWarning"]
asyncio_default_fixture_loop_scope = "function"
addopts = "-x -q --tb=short"
```

### Test Fixtures (conftest.py)

- mock_shopee_client: Mock ShopeeClient with predefined responses
- mock_config: Test configuration with dummy values
- temp_reports_dir: Temporary directory for test reports
- test_db: In-memory SQLite database for schema tests
- sample_decision: Pre-built Decision object for decision engine tests
- sample_goap_actions: Set of GOAPAction objects for planner tests

### Test Coverage Goals

| Module | Target Coverage | Notes |
|--------|-----------------|-------|
| Core (config, paths, logger) | 95%+ | Stable, low change frequency |
| Decision Engine | 90%+ | Critical path, high complexity |
| GOAP Planner | 90%+ | Core AI component |
| Event Bus | 85%+ | Async threading complexity |
| Shopee Client | 80%+ | HTTP mocking needed |
| Pricing Automation | 80%+ | ML component testing |
| Skills Registry | 90%+ | Plugin architecture core |
| Vector Store | 90%+ | Multiple backends |
| Plugin System | 85%+ | Dynamic loading tested |
| Infrastructure | 80%+ | CB, rate limiter, retry |

## Security Audit Checks

The SecurityAudit runs these checks:

1. **check_env_secrets()**: Scans .env for placeholder values (your_, changeme, placeholder, sk-), detects weak passwords, warns about empty values
2. **check_file_permissions()**: Verifies that secrets files have restricted permissions (owner-only read on Unix)
3. **check_dependencies()**: Scans installed packages for known vulnerabilities (requires safety or pip-audit)
4. **check_api_keys_in_code()**: Searches source files for hardcoded API keys, tokens, passwords
5. **check_https()**: Verifies webhook URLs use HTTPS, flags any HTTP endpoints

## Token Lifecycle States

```
ACTIVE: Token is valid and being used
  |-- Token age approaches expiration threshold --> EXPIRING_SOON
  v
EXPIRING_SOON: Token will expire soon, refresh initiated
  |-- Successful refresh --> ACTIVE (new token)
  |-- Refresh in progress --> REFRESHING
  v
REFRESHING: Token refresh is in progress
  |-- Success --> ACTIVE
  |-- Failure --> REFRESH_FAILED
  v
REFRESH_FAILED: Token refresh failed
  |-- Manual intervention --> ACTIVE
  v
EXPIRED: Token can no longer be used
  |-- Full re-authentication --> ACTIVE
```

## Webhook Server Request Flow

```
Webhook Request (POST /webhook/shopee)
  |
  +-- 1. Parse request body as JSON
  +-- 2. Extract signature from headers
  +-- 3. Verify HMAC-SHA256 signature (if LAURA_WEBHOOK_SECRET is set)
  |     +-- Valid: mark event.valid = True
  |     +-- Invalid: reject with 403, log warning
  +-- 4. Create WebhookEvent object
  +-- 5. Route to appropriate handler:
  |     +-- /webhook/shopee -> handle_shopee_push(event)
  |     +-- /webhook/mediaspace -> handle_mediaspace_event(event)
  +-- 6. Emit event to EventBus
  +-- 7. Return 200 OK with acknowledgment
```

## Dashboard Static Routes

| Route | File | Description |
|-------|------|-------------|
| / | index.html | Main dashboard page |
| /summary | summary.html | Executive summary |
| /ab-testing | ab_testing.html | A/B test panel |
| /goap | goap.html | GOAP visualization |
| /skill-health | skill_health.html | Skills health panel |
| /static/* | frontend/dist/* | Static assets (JS, CSS, images) |

## PWA Push Notification Flow

1. User subscribes via POST /api/push/subscribe with subscription object
2. Subscription stored in reports/push_subscriptions.json
3. Events trigger push via POST /api/push/send
4. Browser shows notification even when dashboard tab is closed
5. Clicking notification navigates to relevant dashboard section

## Multi-Tenant Data Isolation

Each tenant gets isolated storage:
- reports/{store_id}/ -- Separate reports directory
- secrets/{store_id}/ -- Separate secrets directory
- data/{store_id}/ -- Separate SQLite databases
- TenantContext (threading.local()) -- Thread-local current tenant
- Tenant switching via TenantManager.switch_tenant(store_id)
- All I/O operations use TenantConfig paths when tenant context is active

## Backup Retention Algorithm

```
prune_backups():
  for each backup in backup_dir:
    age_days = (now - backup.created_at).days
    if age_days GREATER LAURA_BACKUP_RETENTION_DAYS:
        delete backup
        log to backup_log: "pruned {name} (age: {age} days)"

Retention groups (daily backups):
- Last 7 days: all backups kept
- Days 8-14: one backup per day kept (oldest)
- Beyond 14 days: all deleted
```

## CLI Command Dispatch Architecture

```
laura command [args]
  |
  +-- main() in cli.py:
  |     +-- Build ArgumentParser with all subcommands
  |     +-- Handle flags (--help, --version)
  |     +-- Match command to handler:
  |           +-- Simple commands: inline handlers in cli.py
  |           +-- Complex commands: delegate to cli_commands/*_cmd.py
  |           +-- Skill commands: delegate to skills/orchestrator.py
  |           +-- Decision commands: delegate to decision_cli.py
  |     +-- Execute handler with parsed args
  |     +-- Format output (JSON, table, text)
  |     +-- Return exit code
```

## Prometheus Metrics Details

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| laura_health_score | Gauge | component | Health score 0-100 per component |
| laura_cycle_count | Counter | status | Total daemon cycles executed |
| laura_cycle_duration_seconds | Histogram | None | Cycle execution time distribution |
| laura_decisions_total | Counter | type, status, priority | Decision counts by dimension |
| laura_skills_executed_total | Counter | skill_name, status | Skill execution counts |
| laura_events_total | Counter | event_type | Event throughput by type |
| laura_api_requests_total | Counter | endpoint, status_code | API request counts |
| laura_api_latency_seconds | Histogram | endpoint | API response time distribution |
| laura_memory_usage_bytes | Gauge | None | Process RSS memory |
| laura_queue_depth | Gauge | queue_name | EventBus queue depth |

## Concurrency Model

Laura uses a hybrid threading model:

1. **Main thread**: LauraDaemon cycle loop, CLI execution
2. **EventBus thread pool**: Background event processing (configurable pool size)
3. **Telegram bot thread**: Long-polling loop
4. **Auto-login thread**: Periodic cookie refresh
5. **LLM thread**: Ollama model availability check
6. **Worker threads**: DecisionWorker, OutcomeWorker, MetricWorker, NotificationWorker
7. **Backup thread**: Scheduled backup execution
8. **Webhook server threads**: HTTP request handling

Thread safety is ensured via:
- threading.Lock for shared state access
- threading.RLock for reentrant operations
- threading.local() for tenant context
- Queue.Queue for thread-safe work distribution
- Atomic file operations via temp file + rename


---

## Detailed Module Inventory

All modules in shopee_agent/ (137 files total):

### Core Infrastructure Modules

| File | Lines | Purpose |
|------|-------|---------|
| cli.py | 3913 | Main CLI entry point with all command handlers |
| laura_daemon.py | 1146 | Background autonomous daemon |
| config.py | 114 | Configuration loader from env |
| paths.py | 143 | Centralized filesystem paths |
| logger.py | ~50 | Module-level logging functions |
| structured_logger.py | 91 | Structured JSON logging |
| event_bus.py | 468 | Async event bus with WAL + DLQ |
| graceful_shutdown.py | 177 | Orderly service shutdown |
| tracing.py | 269 | Distributed tracing |
| monitoring.py | 306 | Rolling window metrics |
| alerts.py | ~100 | Alert generation |
| metrics_exporter.py | ~150 | Prometheus metrics export |
| monitoring_dashboard.py | ~200 | Real-time monitoring UI |
| healthcheck_monitor.py | ~250 | Health check system |
| self_healing.py | ~200 | Auto-recovery from failures |
| persistent_state.py | ~100 | Thread-safe state management |
| schema_migrations.py | 261 | Versioned DB migrations |
| multi_tenant.py | 288 | Multi-store support |
| i18n.py | 301 | Internationalization |
| cli_completion.py | ~100 | Shell autocomplete |

### Network & Resilience Modules

| File | Lines | Purpose |
|------|-------|---------|
| client.py | 2970 | Shopee API HTTP client |
| endpoints.py | 1264 | API endpoint catalog |
| auth.py | ~200 | OAuth2 + request signing |
| circuit_breaker.py | 334 | Circuit breaker pattern |
| rate_limit.py | 271 | Rate limiting (token bucket) |
| retry.py | 176 | Retry with exponential backoff |
| webhook_server.py | 726 | Webhook HTTP server |
| webhook_handlers.py | ~200 | Webhook event handlers |
| webhooks.py | 167 | Slack/Discord webhook formatters |

### AI & Decision Modules

| File | Lines | Purpose |
|------|-------|---------|
| llm_providers.py | 593 | Multi-provider LLM abstraction |
| llm_local.py | ~200 | Local Ollama analyzer |
| llm_manager.py | 148 | LLM lifecycle management |
| llm.py | ~100 | LLM core interface |
| prompts.py | ~300 | System prompt templates |
| goap_planner.py | 474 | GOAP planner with A* search |
| planner.py | 223 | Plan execution engine |
| strategic_planner.py | ~200 | Long-term strategic planning |
| decision_engine.py | 817 | Central decision engine |
| decision_adaptive.py | 624 | Adaptive rule engine |
| decision_integration.py | ~200 | Decision integration layer |
| decision_memory.py | ~150 | Decision outcome memory |
| decision_cli.py | ~100 | Decision CLI helpers |
| cost_predictor.py | ~100 | Plan cost estimation |
| plan_store.py | ~200 | Plan persistence |
| plan_templates.py | ~100 | Plan template library |
| plan_viz.py | ~150 | Plan visualization |
| plan_healer.py | ~100 | Plan self-healing |
| plan_optimizer.py | ~100 | Plan optimization |
| plan_conformance.py | ~100 | Plan conformance checking |
| plan_explainer.py | ~100 | NL plan explanation |
| planner_alerts.py | ~80 | Planner alerting |
| proactive_goals.py | ~100 | Proactive goal suggestion |
| goal_management.py | ~200 | Goal lifecycle |
| goal_library.py | ~100 | Goal template library |

### Learning & Memory Modules

| File | Lines | Purpose |
|------|-------|---------|
| cognitive_memory.py | 557 | Long-term memory system |
| learning_system.py | 269 | Continuous learning |
| learning_db.py | ~150 | DB-backed learning |
| vector_store.py | 76 | Vector store interface |
| vector_store_annoy.py | ~200 | Annoy backend |
| vector_store_faiss.py | ~150 | FAISS backend |
| learned_actions.py | ~100 | Reusable action storage |

### E-commerce Integration Modules

| File | Lines | Purpose |
|------|-------|---------|
| seller_center_full.py | 1509 | SC full automation |
| seller_center.py | ~300 | SC client |
| seller_center_browser.py | ~200 | SC browser helpers |
| seller_center_actions.py | ~150 | SC action sequences |
| auto_login.py | ~200 | CDP auto-login |
| pricing_automation.py | 683 | ML pricing engine |
| campaign_manager.py | 457 | Campaign CRUD |
| economic_brain.py | ~300 | Financial analysis |
| supply_chain_planner.py | 308 | Supply chain v1 |
| supply_chain_planner_v2.py | ~400 | Supply chain v2 |
| flash_sale_executor.py | ~200 | Flash sale execution |
| flash_sale_recommender.py | ~200 | Flash sale recommendation |
| cross_selling.py | ~150 | Cross-sell engine |
| stock_predictor.py | ~100 | Stock-out prediction |
| predictive_analytics.py | ~200 | Sales forecasting |
| analytics_trending.py | ~200 | Trend analysis |
| anomaly_detector.py | ~150 | Anomaly detection |
| competitive_intelligence.py | ~250 | Competitor monitoring |
| branding_growth.py | ~150 | Brand analysis |
| insights_llm.py | ~150 | LLM-powered insights |
| refunds.py | ~100 | Refund processing |
| token_scheduler.py | ~100 | Token refresh scheduling |

### Communication Modules

| File | Lines | Purpose |
|------|-------|---------|
| telegram_bot.py | 2461 | Telegram interactive bot |
| telegram_narrator.py | ~300 | Push notification narrator |
| telegram_mini_apps.py | ~100 | Mini app integration |
| telegram_web_setup.py | ~100 | Login widget |
| chat_auto.py | ~300 | Chat automation |
| chat_monitor.py | ~200 | Chat monitoring |
| auto_responses.py | ~100 | Auto-response templates |
| email_manager.py | ~100 | Email sending |
| gmail_oauth.py | ~150 | Gmail OAuth2 |
| sentiment_analyzer.py | ~150 | Sentiment analysis |
| rating_reply.py | ~150 | Rating auto-reply |
| support_center.py | ~200 | Support ticket management |

### Dashboard & API Modules

| File | Lines | Purpose |
|------|-------|---------|
| dashboard.py | 1913 | Web dashboard |
| api_router.py | ~200 | Versioned API router |
| api_docs.py | ~100 | API documentation |
| api_cache.py | 113 | File-based API cache |
| api_cache_redis.py | ~100 | Redis cache |
| realtime_export.py | ~100 | WebSocket export |
| charting_visualization.py | ~200 | Chart.js generation |

### Skills Subsystem Modules

| File | Purpose |
|------|---------|
| skills/__init__.py | Package init |
| skills/registry.py | Skill base class + registry |
| skills/orchestrator.py | Skill execution orchestration |
| skills/loader.py | Dynamic skill loading |
| skills/sandbox.py | Isolated execution |
| skills/marketplace.py | Skill marketplace |
| skills/scaffold.py | Skill scaffolding |
| skills/scheduler.py | Cron scheduling |
| skills/state_store.py | Skill state persistence |
| skills/version_history.py | Version tracking |
| skills/ab_testing.py | A/B test framework |
| skills/canary.py | Canary deployment |
| skills/approval.py | Approval workflows |
| skills/event_triggers.py | Event-driven triggers |
| skills/shopee_sandbox.py | Shopee API sandbox |
| skills/generator.py | NL skill generation |
| skills/goal_nl.py | NL-to-goal translation |
| skills/goal_synthesizer.py | KPI-based goal synthesis |
| skills/store_registry.py | Store state registry |
| skills/pricing_skill.py | Dynamic pricing |
| skills/inventory_skill.py | Inventory management |
| skills/order_skill.py | Order processing |
| skills/browser_skill.py | Browser automation |
| skills/support_skill.py | Customer support |

### CLI Commands Modules

| File | Purpose |
|------|---------|
| cli_commands/__init__.py | Package init |
| cli_commands/_utils.py | Shared CLI utilities |
| cli_commands/all_handlers.py | Handler registration |
| cli_commands/auth_shop_cmd.py | Auth/shop commands |
| cli_commands/order_cmd.py | Order commands |
| cli_commands/product_cmd.py | Product commands |
| cli_commands/health_cmd.py | Health check commands |
| cli_commands/chat_cmd.py | Chat commands |
| cli_commands/export_cmd.py | Export commands |
| cli_commands/seller_cmd.py | Seller Center commands |
| cli_commands/report_cmd.py | Report commands |
| cli_commands/monitor_cmd.py | Monitoring commands |
| cli_commands/cache_cmd.py | Cache commands |
| cli_commands/cleanup_cmd.py | Cleanup commands |
| cli_commands/email_cmd.py | Email commands |
| cli_commands/watchdog_cmd.py | Watchdog commands |

### Additional Modules

| File | Purpose |
|------|---------|
| autonomous_loop.py | Autonomous cycle orchestrator |
| autonomous_strategy.py | Strategy layer |
| agent_orchestrator.py | Multi-agent coordination |
| autopilot_actions.py | Autopilot action definitions |
| backup.py | Backup/restore management |
| security_audit.py | Security audit checks |
| secrets_rotation.py | Token lifecycle management |
| workers.py | Event workers |
| workers_management.py | Worker lifecycle |
| worker_bots.py | Telegram worker bots |
| vilu_workers.py | Legacy worker bots |
| resumo_diario.py | Daily summary generation |
| article_scraper.py | Article scraping |
| product_scraper.py | Product scraping |
| site_scraper.py | Site scraping |
| shopee_search_scraper.py | Shopee search scraping |
| vision.py | Computer vision |
| vision_analysis.py | Visual analysis |
| shopee_webhook.py | Webhook utilities |
| reporting.py | Report generation |
| weekly_report.py | Weekly PDF reports |
| setup_wizard.py | First-run setup |
| federated_learning.py | Federated learning v1 |
| federated_learning_v2.py | Federated learning v2 |
| ab_test_automator.py | A/B test automation |
| proactive_notifier.py | Proactive notification |

## CLI Command Categories (Full Enumeration)

| Category | Count | Commands |
|----------|-------|----------|
| Auth/Setup | 8 | auth-url, token-get, token-refresh, token-refresh-save, shop-info, shop-info-default, doctor, health-check |
| API Gateway | 4 | api-call, api-endpoints, api-families, api-serve |
| Products | 4 | product-list, product-item-detail, product-item-base-info, product-item-variations |
| Orders | 8 | order-list, order-detail, order-ship, refunds list, refunds approve, refunds reject, refunds auto-evaluate, predict-refunds |
| Logistics | 3 | logistics-channel-list, logistics-info, logistics-tracking-number |
| Finance | 2 | payment-escrow-detail, economic-brain-summary |
| Promotions | 10 | discount-list, voucher-list, bundle-deal-list, add-on-deal-list, flash-sale-recommend, flash-sale-exec, campaign list, campaign bundle, campaign voucher, campaign auto |
| Media | 6 | media-video-init-upload, media-video-upload-part, media-video-complete-upload, media-video-upload-result, media-video-wait-completion, vision, visual-analysis |
| LLM/Ollama | 4 | llm-prompts, llm-analyze, ollama-status, ollama-fix |
| Daemon | 5 | daemon, start, autonomous-loop, activity, shell |
| Skills | 20 | skill-list, skill-run, skill-register, skill-test, skill-create, skill-generate, skill-goap-plan, skill-goap-explain, skill-history, skill-reload, skill-profile, skill-anomaly, skill-version, skill-market, skill-approve, skill-reject, skill-approval-list, skill-rollback-learning, learning-stats, skill-simulate |
| A/B Test | 7 | ab-test-start, ab-test-status, ab-auto-promote, canary-start, canary-status, canary-promote, canary-rollback |
| GOAP | 17 | goal-synthesize, goal-nl, goal-library, plan-viz, plan-diff, plan-export, plan-import, plan-batch, plan-schedule, plan-optimize, plan-store, plan-heal, plan-explain, plan-conform, plan-template, planners-alerts, proactive-goals, cost-predict, multi-approve |
| Decision Engine | 10 | decision-status, decision-history, decision-detail, decision-cycle, decision-metrics, decision-outcomes, decision-learn, decision-effectiveness, decision-similar, decision-reindex-backend |
| Goals | 5 | goal-summary, goal-list, goal-add, goal-top, goal-complete |
| Analytics | 15 | analytics-trends, anomaly-detect, charts, chart-dashboard, performance-report, export-report, schedule-report, realtime-config, insights-trend, insights-anomaly, insights-recommendations, insights-summary, competitive-intel-summary, branding-growth-summary, dashboard-cli |
| Webhook | 2 | webhook-start, webhook-drain |
| Seller Center | 10 | sc products, sc product, sc orders, sc ship, sc pending, sc balance, sc campaigns, sc perf, sc violations, sc bulk-price, sc bulk-stock, sc export |
| Chat | 8 | chat list, chat auto-reply, chat send, chat history, telegram-bot, cross-sell recommend, cross-sell top-pairs, cross-sell bundle |
| Infrastructure | 12 | queue status, queue dlq, queue retry, metrics-export, metrics-dashboard, trace, agent-orchestration, strategic-plan, browser-run, supply-chain, federated, federated-v2, tenant, sandbox-test, benchmark, completion |
| System | 10 | store-list, store-init, store-summary, workers list, workers status, workers pause, workers resume, workers stats, export, cleanup, health, dashboard |

## SQLite Database Details

### shopee_articles.db

This database stores the product catalog with articles data:

Tables (inferred from usage):
- articles: Product catalog with fields for ID, name, description, price, stock, category, images
- article_costs: Cost data per product (unit cost, shipping cost, fees)
- article_prices: Price history (list price, sale price, competitor price)
- article_analytics: Analytics data (views, sales, conversion rate)

Used by: pricing_automation, economic_brain, reporting modules.

### goap_learning.db

Tables:
- costs: Action cost tracking with execution/success/failure counts
- cost_history: Historical cost adjustments with timestamps
- action_outcomes: Individual action execution results
- notes: Long-term memory notes with tags
- session_plans: Session-specific plan cache

Used by: GOAPPlanner, CognitiveMemory, LearningSystem.

### plan_store.db

Tables:
- plans: Persisted GOAP plans with state, goals, actions JSON
- plan_templates: Reusable plan templates by category
- plan_executions: Plan execution history with results

Used by: PlanStore, PlanTemplates, PlanExecutor.

### learning.db (cognitive memory)

Tables:
- memory_outcomes: Decision outcomes with impact metrics
- memory_reflections: System-generated reflections on outcomes
- memory_notes: Manually stored notes and observations
- memory_vectors: Vector embeddings for semantic search

Used by: CognitiveMemory, ReflectionSystem, SemanticMemory.

## Key Data Flow Diagrams

### Order Processing Flow

```
Shopee Push Webhook (new order notification)
  |
  +-- WebhookServer /webhook/shopee
  |     +-- Verify signature
  |     +-- Create WebhookEvent
  |     +-- Emit to EventBus
  |
  +-- OrderSkill (triggered by event)
  |     +-- Fetch order details via ShopeeClient
  |     +-- Check payment status
  |     +-- Update inventory
  |     +-- Generate shipping label
  |     +-- Mark as ready to ship
  |
  +-- DecisionEngine evaluates:
  |     +-- Auto-ship? (based on rules)
  |     +-- Send thank-you message?
  |     +-- Cross-sell recommendation?
  |
  +-- NotificationWorker sends:
        +-- Telegram alert to seller
        +-- Email confirmation
        +-- Dashboard event update
```

### Price Update Flow

```
MetricUpdateEvent (competitor price changed)
  |
  +-- DecisionEngine processes signal
  |     +-- Evaluate pricing rules
  |     +-- Check margin guardrails
  |     +-- Risk assessment
  |     +-- Generate decision
  |
  +-- Approval workflow (if HIGH risk):
  |     +-- Telegram inline keyboard
  |     +-- Dashboard approval panel
  |     +-- Timeout-based auto-approve
  |
  +-- PricingSkill executes:
  |     +-- Calculate new price
  |     +-- Update via ShopeeClient
  |     +-- Record in pricing_history
  |
  +-- Outcome recorded:
        +-- Sales volume change after 24h
        +-- Margin impact
        +-- Competitor reaction
        +-- Learning system update
```

### Backup Flow

```
Scheduled backup (every VILU_BACKUP_INTERVAL)
  |
  +-- BackupManager.create_backup()
  |     +-- Lock state (prevent concurrent operations)
  |     +-- Snapshot current state:
  |     |     +-- .env configuration
  |     |     +-- secrets/ directory
  |     |     +-- reports/ directory
  |     |     +-- data/ directory
  |     +-- Create ZIP archive:
  |     |     +-- Compress each source directory
  |     |     +-- Preserve directory structure
  |     |     +-- Add metadata manifest
  |     +-- Compute SHA256 checksum
  |     +-- Save to BACKUPS_DIR/{timestamp}.zip
  |     +-- Log to backup_log table
  |     +-- Prune old backups (retention policy)
  |     +-- Unlock state
  |
  +-- NotificationWorker sends:
        +-- Telegram: "Backup completed: {size} MB"
        +-- Dashboard event update
```

## Error Handling Examples

### Shopee API Error Handling

```python
try:
    response = client._request(path, method, payload=payload)
except CircuitBreakerOpen:
    # Circuit is open, skip this endpoint
    log_error(f"Circuit breaker open for {path}, skipping")
    return None
except RateLimitExceeded:
    # Rate limit hit, back off and retry
    log_warning(f"Rate limit exceeded for {path}, waiting")
    time.sleep(rate_limit.reset_time - time.time())
    return client._request(path, method, payload=payload)
except requests.Timeout:
    # Timeout, retry with backoff
    log_warning(f"Timeout for {path}, retrying...")
    return retry(client._request, path, method, payload=payload)
except requests.HTTPError as e:
    if e.response.status_code == 401:
        # Token expired, refresh and retry
        new_token = secrets_rotation.refresh_token("access_token")
        return client._request(path, method, payload=payload, access_token=new_token)
    elif e.response.status_code == 403:
        # Forbidden, check permissions
        log_error(f"Forbidden: {path}, check partner permissions")
        raise
    elif e.response.status_code == 429:
        # Rate limited, wait and retry
        retry_after = int(e.response.headers.get("Retry-After", 60))
        time.sleep(retry_after)
        return client._request(path, method, payload=payload)
    else:
        raise
```

### LLM Error Handling

```python
try:
    response = llm.generate(prompt, config)
    if response.success:
        return response.text
    else:
        # Primary provider failed, try fallback
        log_warning(f"LLM provider {config.provider} failed: {response.error}")
        fallback_config = get_next_available_provider(config)
        return llm.generate(prompt, fallback_config).text
except OllamaNotRunning:
    log_warning("Ollama not running, attempting to start...")
    iniciar_ollama()
    time.sleep(5)
    if ollama_rodando():
        return llm.generate(prompt, config).text
    else:
        log_error("Failed to start Ollama, using rule-based fallback")
        return rule_based_fallback(prompt)
except AllProvidersExhausted:
    log_error("All LLM providers unavailable, using rule-based fallback")
    return rule_based_fallback(prompt)
```

## Performance Optimization Notes

### Caching Strategy

1. **Shopee API responses**: Cached in api_cache/ with 30-day TTL
   - Cache key: normalized endpoint name + query parameters hash
   - Cache invalidation: explicit for mutating calls, TTL-based for reads
   - Benefits: Reduces API calls by 60-80% for frequently accessed data

2. **Vector index caching**: Annoy/FAISS indexes persisted to disk
   - Background rebuild every LAURA_ANNOY_BUILD_INTERVAL seconds
   - Lazy rebuild: only rebuild when new vectors added since last build
   - Benefits: Fast startup (load pre-built index) with fresh data

3. **Plan caching**: GOAPPlanner caches recently computed plans
   - Cache key: state_hash + goals_hash
   - LRU eviction: keep last 100 plans
   - Benefits: Repeated planning requests served in O(1)

4. **LLM response caching**: Identical prompts return cached results
   - Cache key: prompt_hash + model_name
   - TTL: 1 hour for analytical prompts, no cache for generative
   - Benefits: Reduces LLM calls for repeated analytical queries

### Database Optimization

1. All SQLite queries use indexed columns: execution time under 10ms
2. WAL mode for concurrent read/write access
3. Batch inserts for high-volume data (outcomes, events)
4. Periodic VACUUM for space reclamation
5. Foreign keys enabled for referential integrity

### Thread Pool Sizing

EventBus thread pool size calculated based on:
- Number of registered subscribers
- Expected event throughput
- Typical handler latency
- Default: min(32, os.cpu_count() * 4)

## Deployment Configuration Files

### .env.example Template

The .env.example file at project root serves as a template. Key sections:
- Shopee Open Platform API (REQUIRED)
- LLM/Ollama Configuration
- Telegram Integration
- Profitability Autopilot
- Webhook Server
- Metrics and Health Monitoring
- Backup and Retention
- Directory Overrides

### docker-compose.override.yml Example

```yaml
version: "3.8"
services:
  laura:
    environment:
      - LAURA_LLM_MODEL=mistral
      - LAURA_PROFITABILITY_EXECUTE_ENABLED=1
    volumes:
      - ./custom_plugins:/app/plugins
```

### Nginx SSL Configuration

```nginx
server {
    listen 443 ssl;
    server_name laura.example.com;

    ssl_certificate /etc/letsencrypt/live/laura.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/laura.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8888;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws/stream {
        proxy_pass http://127.0.0.1:8888/ws/stream;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

## Development Workflow

### Feature Development

1. Create feature branch from main
2. Implement changes with tests
3. Run: ruff check . && mypy shopee_agent/ && pytest tests/ -x
4. Create pull request
5. CI runs lint + test workflows
6. Review and merge to main

### Hotfix Process

1. Create hotfix branch from main
2. Apply minimal fix with targeted test
3. Run full test suite
4. Create PR with hotfix label
5. Merge and tag release

### Release Process

1. Update version in pyproject.toml
2. Update CHANGELOG.md
3. Create GitHub release with tag
4. Build Docker image and push to registry
5. Update deployment manifests


---

## Detailed Component Interaction Sequences

### Startup Sequence

```
1. laura daemon command executed
2. CLI parser dispatches to daemon handler
3. LauraDaemon.__init__():
   - Load .env file manually
   - Create reports directories
   - Initialize GracefulShutdown
4. LauraDaemon.run():
   a. Load config via load_config()
   b. Initialize ShopeeClient(config)
   c. Initialize AutonomousLoop(client, ...)
   d. Initialize SellerCenterClient()
   e. Initialize EventBus
   f. Start Telegram bot thread (if configured)
   g. Start auto-login thread (if configured)
   h. Start LLM check thread
   i. Start workers (DecisionWorker, OutcomeWorker, etc.)
   j. Start backup scheduler
   k. Enter main loop:
      - Run _cycle()
      - Sleep CYCLE_INTERVAL
      - Check health every 30 min
      - Handle shutdown signals
```

### Decision Engine Integration

```
AutonomousLoop.run_cycle() calls:
  1. DecisionIntegrator.process_signals(context)
     a. Collect signals from EventBus recent events
     b. Aggregate metrics from MetricsCollector
     c. Correlate related signals (e.g., price drop + competitor change)
     d. Build enriched context dict

  2. DecisionEngine.evaluate_signals(enriched_context)
     a. For each active rule:
        - Evaluate condition against context
        - If True: create Decision with action, priority, risk
        - Apply guardrails (financial limits, security policies)
     b. Sort decisions by priority + risk score
     c. For high-risk decisions:
        - Emit approval request to dashboard + Telegram
        - Wait for approval or timeout
     d. Return approved decision list

  3. DecisionExecutor.execute_decisions(decisions)
     a. For each decision (in priority order):
        - Resolve action to Skill via SkillRegistry
        - Execute skill with decision context
        - Record outcome (success/failure + impact)
        - If failure: execute compensation action (reverse_skill)
        - Emit DecisionExecutedEvent to EventBus

  4. AdaptiveRuleEngine.evaluate(enriched_context)
     a. Evaluate adaptive rules against context
     b. Return adjusted rule weights
     c. Emit adjustments to LearningSystem

  5. FeedbackLoop.process_results()
     a. Collect outcomes since last cycle
     b. Compute success/failure rates
     c. Adjust adaptive rule weights
     d. Detect failure patterns
     e. Suggest new rules for detected patterns
     f. Prune ineffective rules
```

### GOAP Planning Integration

```
1. GoalManager.synthesize_from_kpis(context)
   - Extract KPI gaps from current vs target
   - Create Goal objects for each gap
   - Priority rank goals by impact

2. GOAPPlanner.plan(current_state, goals, skills)
   - Build state from current context
   - Build goal state from Goal objects
   - Get available skills from SkillRegistry
   - Run A* search:
     a. Start with current_state, empty plan
     b. For each state in priority queue:
        - If state satisfies all goals: return plan
        - Find all actions with valid preconditions
        - For each action: apply effects, compute cost, add to queue
        - Prune states with cost above threshold
     c. If no plan found: expand threshold, retry
     d. If still no plan: return best partial plan

3. PlanExecutor.execute_plan(plan)
   - For each action in plan:
     - Resolve action to Skill via reverse_name mapping
     - Execute skill
     - If success: record outcome, continue
     - If failure: execute reverse skill (rollback), abort plan

4. LearningSystem.process_plan_outcomes(outcomes)
   - Update action costs based on success/failure
   - Store execution history
   - Generate learning signals
```

### Telegram Bot Command Processing

```
1. Bot thread: long-poll getUpdates with timeout (LAURA_TELEGRAM_BOT_POLL_TIMEOUT_SECONDS)
2. For each update:
   a. Parse text to TelegramCommand (command name + optional arg)
   b. Verify chat_id is allowed (check against LAURA_TELEGRAM_BOT_ALLOWED_CHAT_ID)
   c. Route to command handler:
      - /start: Send welcome message with help
      - /status: Query system status, format response
      - /orders: Fetch recent orders, format as table
      - /profit: Run economic_brain, format summary
      - /decision: Fetch pending decisions, format with inline keyboards
      - /approve <id>: Approve decision, send confirmation
      - /reject <id>: Reject decision, send confirmation
   d. Send response via sendMessage API
   e. Sleep LAURA_TELEGRAM_BOT_SLEEP_SECONDS
```

### Plugin Loading Sequence

```
1. PluginManager.discover_plugins()
   - Scan plugins/ directory for .py files
   - Also scan configured additional paths
   - Skip files starting with underscore (private)
   - Return list of plugin file paths

2. PluginManager.load_all()
   - For each discovered plugin:
     a. Import module dynamically via importlib
     b. Find classes inheriting from Plugin
     c. For each plugin class:
        - Instantiate with default config
        - Call plugin.on_load(context)
        - If returns False: log warning, skip plugin
        - Register plugin in _plugins dict
        - Register hooks in _hooks dict
   - Resolve plugin dependencies (load order)
   - Call on_plugin_load for other plugins

3. PluginManager.call_hook(hook_name, context)
   - For each plugin registered for hook_name:
     - Call plugin.hook_method(context)
     - Catch and log exceptions (don't break chain)
   - Return results dict
```

### Self-Healing Sequence

```
1. SelfHealingCoordinator.check_and_heal()
2. Run diagnostics:
   a. check_ollama_health(): HTTP GET to Ollama API
   b. check_shopee_api_health(): Simple API call (get_shop_info)
   c. check_seller_center_session(): Verify cookies valid
   d. check_disk_space(): Verify available space > 10%
   e. check_token_expiration(): Check all token expiry dates
   f. check_backup_freshness(): Verify backup age < 28h
   g. check_circuit_breakers(): Check for open circuits
   h. check_event_bus_health(): Check WAL and DLQ status

3. For each failed check:
   - Determine recovery action
   - Execute recovery:
     a. Ollama down: iniciar_ollama(), wait 15s, verify
     b. SC session expired: renovar_cookies_via_cdp(), wait 30s, verify
     c. Disk space low: prune_backups(), clean old reports
     d. Token expiring: refresh_token(), update .env
     e. Backup stale: executar_backup() immediately
     f. Circuit open: reset_circuit_breaker(), test with simple call
     g. EventBus full: retry_dlq(), clear stale events

4. Log remediation actions to reports/laura_remediation_cases.jsonl
5. If auto-notify enabled: send Telegram summary of healing actions
```

### Webhook Processing Sequence

```
1. Shopee sends POST to /webhook/shopee
2. WebhookHandler.do_POST():
   a. Read request body
   b. Extract signature from X-Shopee-Signature header
   c. Verify HMAC-SHA256 signature using LAURA_WEBHOOK_SECRET
   d. If invalid: return 403 Forbidden
   e. Parse JSON body to WebhookEvent
   f. Route based on URL path
   g. Call webhook_handlers.handle_shopee_push(event)
   h. Emit event to EventBus as typed event
   i. Return 200 OK with {"ack": "received", "event_id": "..."}
```

### Backup and Restore Sequence

```
Backup:
1. Scheduled or manual trigger
2. BackupManager.create_backup(name):
   a. Get timestamp (YYYYMMDD_HHMMSS_BRT)
   b. Compose ZIP filename
   c. Open ZIP file for writing
   d. Add files from source_dirs:
      - reports/: All files and subdirectories
      - secrets/: Key credential files
      - data/: SQLite databases
      - .env: Configuration file
   e. Compute SHA256 checksum of completed ZIP
   f. Write checksum to backup_log database
   g. Prune backups older than retention days
   h. Return backup metadata dictionary

Restore:
1. Verify backup integrity (checksum check)
2. BackupManager.restore_backup(name):
   a. Check that restoring won't overwrite newer files
   b. Extract ZIP to temporary directory
   c. Compare extracted files with originals
   d. Prompt for confirmation (or auto-confirm if --force)
   e. Copy extracted files to original locations
   f. Log restore event
   g. Return success with file count

3. Post-restore: restart daemon to reload all state
```

## Security Hardening Guidelines

### File Permissions

| Path | Recommended Permission | Owner |
|------|------------------------|-------|
| .env | 600 (owner read/write) | laura user |
| secrets/ | 700 (owner full) | laura user |
| reports/ | 755 (owner full, group/other read) | laura user |
| logs/ | 755 (owner full, group/other read) | laura user |
| backsups/ | 700 (owner full) | laura user |
| plugins/ | 755 (owner full, group/other read/exec) | laura user |

### Network Security

- Dashboard bound to 127.0.0.1 by default (localhost only)
- Webhook server bound to 127.0.0.1 by default (use Nginx reverse proxy for external access)
- Ollama bound to 127.0.0.1 by default (not exposed externally)
- All external API calls use HTTPS (Shopee, Telegram, OpenAI, Anthropic)
- Webhook callback URLs must use HTTPS (enforced by Shopee requirement)

### API Key Protection

- Never commit .env to version control (.env in .gitignore)
- Use environment variables in production (not .env file)
- Rotate keys regularly via SecretsRotationManager
- Use separate Shopee Partner App for production vs development
- Telegram bot tokens stored in secrets/ directory with restricted permissions

## Troubleshooting Guide

### Common Issues and Solutions

| Issue | Symptom | Solution |
|-------|---------|----------|
| Ollama not responding | llm commands fail | laura ollama-fix, or manually: ollama serve |
| Invalid signature | Shopee API returns 403 | Verify PARTNER_KEY, re-run laura auth-url |
| Token expired | API returns 401 | laura token-refresh-save, or auto-refresh in daemon |
| Seller Center session invalid | sc commands fail | Renew cookies via CDP, or laura doctor |
| EventBus errors | Queue operations fail | laura queue dlq --max 50, laura queue retry --max 50 |
| Backup not working | Backup command fails | ./scripts/laura_backup.sh, check disk space |
| Dashboard not loading | Browser shows error | Verify port 8888 free, laura dashboard --port 8080 |
| Plugin not loading | skill-list doesn't show | Check plugin syntax, verify Plugin class inheritance |
| Daemon not starting | No process found | tail -f logs/laura_errors.log, check PID file |

### Diagnostic Commands

```bash
# Full system diagnostic
laura doctor

# Token validation
laura health-check

# Logs review
tail -f logs/laura_operations.log
tail -f logs/laura_errors.log

# Queue inspection
laura queue status
laura queue dlq --max 50

# System resources
laura skill-profile

# Performance benchmark
laura benchmark
```

## Glossary of Internal Abbreviations

| Abbreviation | Full Name |
|-------------|-----------|
| SC | Seller Center |
| PW | Playwright |
| CDP | Chrome DevTools Protocol |
| CB | Circuit Breaker |
| RL | Rate Limiter |
| WAL | Write-Ahead Log |
| DLQ | Dead-Letter Queue |
| FSM | Finite State Machine |
| DAG | Directed Acyclic Graph |
| KPI | Key Performance Indicator |
| ROAS | Return on Ad Spend |
| P&L | Profit and Loss |
| NL | Natural Language |
| ANN | Approximate Nearest Neighbors |
| FAISS | Facebook AI Similarity Search |
| PWA | Progressive Web Application |
| SSE | Server-Sent Events |
| JWT | JSON Web Token |
| OTP | One-Time Password |
| 2FA | Two-Factor Authentication |
| CRDT | Conflict-Free Replicated Data Type |
| FTS5 | Full-Text Search version 5 |
| MCP | Model Context Protocol |
| SDK | Software Development Kit |
| CLI | Command-Line Interface |
| REST | Representational State Transfer |
| API | Application Programming Interface |
| SDK | Software Development Kit |
| CI/CD | Continuous Integration/Continuous Deployment |
| E2E | End-to-End |
| SWAT | Strengths, Weaknesses, Ambitions, Threats |


---

## Complete List of Environment Variables

### Required Variables

| Variable | Type | Description |
|----------|------|-------------|
| SHOPEE_PARTNER_ID | int | Partner ID from Shopee Open Platform app registration |
| SHOPEE_PARTNER_KEY | string | Partner Key (private HMAC secret) associated with the Partner ID |
| SHOPEE_REDIRECT_URL | url | OAuth2 redirect URL configured in the Shopee Open Platform app |

### Optional Variables - Shopee API

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| SHOPEE_BASE_URL | url | https://partner.shopeemobile.com | Base URL for Shopee API endpoints |
| SHOPEE_DEFAULT_SHOP_ID | int | None | Default Shop ID for API calls |
| SHOPEE_DEFAULT_ACCESS_TOKEN | string | None | Default OAuth access token |
| SHOPEE_DEFAULT_REFRESH_TOKEN | string | None | Default OAuth refresh token |

### Optional Variables - LLM Configuration

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| LAURA_LLM_ENABLED | bool | 1 | Enable local LLM integration (0 to disable all LLM features) |
| LAURA_LLM_MODEL | string | tinyllama | Ollama model name to use for inference |
| LAURA_OLLAMA_HOST | host | 127.0.0.1 | Ollama server hostname |
| LAURA_OLLAMA_PORT | port | 11434 | Ollama server port |
| LAURA_LLM_REQUEST_TIMEOUT_SECONDS | int | 30 | Timeout for LLM API requests |
| LAURA_ALLOW_PAID_LLM | bool | 0 | Allow paid LLM providers (OpenAI, Anthropic) |
| OPENAI_API_KEY | string | None | OpenAI API key (requires ALLOW_PAID_LLM=1) |
| ANTHROPIC_API_KEY | string | None | Anthropic API key (requires ALLOW_PAID_LLM=1) |

### Optional Variables - Daemon Operation

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| VILU_DAEMON_INTERVAL | int | 300 | Daemon cycle interval in seconds (5 minutes) |
| VILU_BACKUP_INTERVAL | int | 86400 | Backup interval in seconds (24 hours) |
| LAURA_AUTO_LOGIN_INTERVAL | int | 21600 | Auto-login refresh interval in seconds (6 hours) |
| PRICING_CYCLE_INTERVAL | int | 5 | Number of cycles between pricing analysis runs |

### Optional Variables - Telegram Integration

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| LAURA_ALERT_TELEGRAM_BOT_TOKEN | string | None | Bot token for alert notifications |
| LAURA_ALERT_TELEGRAM_CHAT_ID | int | None | Chat ID to receive alerts |
| LAURA_TELEGRAM_LIVE_NOTIFICATIONS | bool | 0 | Enable real-time notifications |
| LAURA_TELEGRAM_NOTIFY_LEVEL | enum | INFO | Minimum level for notifications (INFO/WARNING/ERROR) |
| LAURA_TELEGRAM_NARRATOR | bool | 0 | Enable narrator mode for milestone notifications |
| LAURA_TELEGRAM_NARRATOR_LEVEL | enum | INFO | Narrator notification level |
| LAURA_TELEGRAM_BOT_ALLOWED_CHAT_ID | int | None | Restrict bot commands to specific chat ID |
| LAURA_TELEGRAM_BOT_POLL_TIMEOUT_SECONDS | int | 30 | Long-polling timeout for getUpdates |
| LAURA_TELEGRAM_BOT_SLEEP_SECONDS | float | 1.0 | Sleep interval between polling cycles |

### Optional Variables - Profitability Autopilot

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| LAURA_PROFITABILITY_ENABLED | bool | 1 | Master switch for autopilot feature |
| LAURA_PROFITABILITY_EXECUTE_ENABLED | bool | 0 | Enable actual execution (safe default: disabled) |
| LAURA_PROFITABILITY_COOLDOWN_MINUTES | int | 120 | Minimum time between pricing actions |
| LAURA_PROFITABILITY_MIN_MARGIN_PCT | float | 12 | Hard floor margin percentage |
| LAURA_PROFITABILITY_MAX_REFUND_RATE_PCT | float | 6 | Maximum acceptable refund rate |
| LAURA_PROFITABILITY_MIN_ROAS | float | 3 | Minimum return on ad spend |
| LAURA_PROFITABILITY_MIN_ORDERS_FOR_SCALE | int | 20 | Minimum orders for scaling decisions |
| LAURA_PROFITABILITY_EXEC_KILL_SWITCH | bool | 1 | Emergency kill switch for all actions |
| LAURA_PROFITABILITY_EXEC_ALLOWED_ACTIONS | string | scale_winners | Comma-separated whitelist of allowed action types |

### Optional Variables - Webhook Server

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| LAURA_WEBHOOK_HOST | host | 127.0.0.1 | Webhook server bind address |
| LAURA_WEBHOOK_PORT | port | 8765 | Webhook server port |
| LAURA_WEBHOOK_PATH | path | /webhook/shopee | Callback URL path |
| LAURA_WEBHOOK_PUBLIC_BASE_URL | url | None | Public HTTPS URL for Shopee callbacks |
| LAURA_WEBHOOK_SECRET | string | None | Live Push Partner Key (HMAC secret) |
| LAURA_WEBHOOK_ALLOW_UNVERIFIED_ACK | bool | 0 | Accept unverified callbacks (development only) |
| LAURA_WEBHOOK_READY_TIMEOUT_SECONDS | int | 10 | Readiness check timeout |
| LAURA_WEBHOOK_READY_MAX_LATENCY_SECONDS | int | 3 | Maximum acceptable latency |
| LAURA_WEBHOOK_READY_RETRY_ATTEMPTS | int | 2 | Readiness check retry count |
| LAURA_WEBHOOK_READY_GUARD_ENABLED | bool | 1 | Enable readiness guard |
| LAURA_WEBHOOK_READY_ALERT_STREAK | int | 2 | Consecutive failures before alert |
| LAURA_WEBHOOK_READY_AUTO_HEAL | bool | 1 | Automatic recovery on failure |
| LAURA_WEBHOOK_READY_AUDIT_ENABLED | bool | 1 | Log readiness audit events |
| LAURA_WEBHOOK_READY_DIGEST_ENABLED | bool | 1 | Daily readiness digest |

### Optional Variables - Metrics and Monitoring

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| LAURA_METRICS_RETENTION_DAYS | int | 30 | Days to retain metric data |
| LAURA_METRICS_DIGEST_ENABLED | bool | 1 | Daily metrics digest |
| LAURA_METRICS_DIGEST_WINDOW_HOURS | int | 24 | Digest aggregation window |
| LAURA_METRICS_SCORE_WEIGHT_API | int | 25 | API health weight in composite score |
| LAURA_METRICS_SCORE_WEIGHT_CRON | int | 25 | Cron health weight |
| LAURA_METRICS_SCORE_WEIGHT_BACKUP | int | 25 | Backup health weight |
| LAURA_METRICS_SCORE_WEIGHT_FULL | int | 25 | Full system health weight |
| LAURA_METRICS_GUARD_WINDOW_HOURS | int | 24 | Guard evaluation window |
| LAURA_METRICS_GUARD_MIN_SUCCESS_PCT | int | 90 | Minimum acceptable success rate |
| LAURA_METRICS_GUARD_MIN_SAMPLES | int | 6 | Minimum samples for guard evaluation |
| LAURA_METRICS_AUTO_REMEDIATE_ENABLED | bool | 0 | Automatic remediation on guard failure |
| LAURA_METRICS_WEEKLY_REPORT_ENABLED | bool | 1 | Automatic weekly report generation |
| LAURA_METRICS_AUDIT_RETENTION_DAYS | int | 30 | Audit log retention period |

### Optional Variables - Health and Security

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| LAURA_HEALTHCHECK_MAX_LOG_BYTES | int | 5242880 | Maximum health check log size (5MB) |
| LAURA_HEALTHCHECK_MAX_LOG_BACKUPS | int | 1 | Number of log file backups |
| LAURA_HEALTHCHECK_MAX_BACKUP_AGE_DAYS | int | 7 | Maximum backup age in days |
| LAURA_SUCCESS_GUARD_MAX_AGE_SECONDS | int | 14400 | Maximum age of last success (4 hours) |
| LAURA_WATCHDOG_MAX_AGE_SECONDS | int | 14400 | Maximum watchdog age (4 hours) |
| LAURA_CRON_GUARD_AUTO_HEAL | bool | 1 | Automatic cron healing |
| LAURA_SECURITY_GUARD_NOTIFY_ON_FIX | bool | 1 | Notification on security fix |
| LAURA_SECURITY_REMINDER_ENABLED | bool | 1 | Monthly security reminder |

### Optional Variables - Backup and Retention

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| LAURA_BACKUP_RETENTION_DAYS | int | 14 | Backup retention period |
| LAURA_VERIFY_BACKUP_MAX_AGE_HOURS | int | 48 | Maximum age for backup verification |
| LAURA_RESTORE_DRILL_MAX_AGE_HOURS | int | 72 | Maximum age for restore drill |
| LAURA_ENV_SNAPSHOT_RETENTION_DAYS | int | 30 | Environment snapshot retention |
| LAURA_REPORT_RETENTION_DAYS | int | 14 | Report retention period |
| VILU_MAX_BACKUPS | int | 30 | Maximum number of backup archives |

### Optional Variables - Seller Center

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| GMAIL_CREDENTIALS_FILE | path | None | Path to Gmail OAuth credentials JSON |
| GMAIL_TOKEN_FILE | path | None | Path to Gmail OAuth token JSON |
| SELLER_CENTER_CREDENTIALS_FILE | path | None | Path to Seller Center credentials |
| SELLER_CENTER_COOKIES_FILE | path | None | Path to persistent cookies |
| CDP_WS_URL | url | None | Chrome DevTools Protocol WebSocket URL |

### Optional Variables - Vector Store

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| LAURA_VECTOR_BACKEND | enum | memory | Vector store backend (memory/annoy/faiss) |
| LAURA_VECTOR_DIM | int | 128 | Vector dimension for embeddings |
| LAURA_ANNOY_INDEX_PATH | path | None | Annoy index file path |
| LAURA_ANNOY_META_PATH | path | None | Annoy metadata file path |
| LAURA_ANNOY_BACKGROUND_BUILD | bool | 0 | Enable background index rebuilding |
| LAURA_ANNOY_BUILD_INTERVAL | int | 60 | Index rebuild interval in seconds |
| LAURA_FAISS_INDEX_PATH | path | None | FAISS index file path |
| LAURA_FAISS_META_PATH | path | None | FAISS metadata file path |

### Optional Variables - Directory Overrides

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| LAURA_REPORTS_DIR | path | ./reports | Reports and state directory |
| LAURA_LOGS_DIR | path | ./logs | Log files directory |
| LAURA_SECRETS_DIR | path | ./secrets | Secrets storage directory |
| LAURA_BACKUPS_DIR | path | ./backups | Backup archives directory |
| LAURA_DATA_DIR | path | ./data | SQLite databases directory |
| LAURA_SKILLS_DIR | path | ./shopee_agent/skills | Skills module directory |
| LAURA_VISION_TEMP_DIR | path | ~/.laura_vision | Vision processing temp directory |
| LAURA_VISION_CACHE_DIR | path | ~/.laura_vision_cache | Vision analysis cache directory |
