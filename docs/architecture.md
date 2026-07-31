# Architecture

## System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                        LAURA AGENT                                │
│                                                                   │
│  ┌─────────┐   ┌──────────┐   ┌──────────┐   ┌───────────────┐   │
│  │   CLI    │   │ Dashboard│   │  Daemon  │   │  REST API     │   │
│  │ (argparse)│  │ (FastAPI) │   │ (async)  │   │  (FastAPI)    │   │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘   └──────┬────────┘   │
│       │               │              │                │            │
│       └───────────────┼──────────────┼────────────────┘            │
│                       │              │                             │
│              ┌────────▼──────────────▼──────────┐                  │
│              │        DECISION ENGINE            │                  │
│              │  (GOAP Planner + Skill Executor)  │                  │
│              └────────────────┬──────────────────┘                  │
│                               │                                     │
│              ┌────────────────▼──────────────────┐                  │
│              │         SKILLS REGISTRY            │                  │
│              │  (24+ skills with preconditions)   │                  │
│              └────────────────┬──────────────────┘                  │
│                               │                                     │
├───────────────────────────────┼─────────────────────────────────────┤
│                               │                                     │
│              ┌────────────────▼──────────────────┐                  │
│              │         SHOPEE INTEGRATION         │                  │
│              │                                     │                  │
│  ┌───────────▼──────────┐    ┌───────────────────┐│                  │
│  │  Shopee Open API     │    │  Seller Center    ││                  │
│  │  (REST)              │    │  (Browser/CDP)    ││                  │
│  └───────────┬──────────┘    └─────────┬─────────┘│                  │
│              │                          │          │                  │
│              └──────────────────────────┘          │                  │
│                                                    │                  │
│  ┌──────────────────────────────────────────────┐  │                  │
│  │             INFRASTRUCTURE                    │  │                  │
│  │  ┌─────────┐ ┌──────────┐ ┌──────────────┐   │  │                  │
│  │  │ Ollama  │ │  Redis   │ │ Vector Store │   │  │                  │
│  │  │ (LLM)   │ │ (cache)  │ │ (Annoy/FAISS)│   │  │                  │
│  │  └─────────┘ └──────────┘ └──────────────┘   │  │                  │
│  │  ┌─────────┐ ┌──────────┐ ┌──────────────┐   │  │                  │
│  │  │ SQLite  │ │ Event Bus│ │  File Store  │   │  │                  │
│  │  │ (state) │ │ (async)  │ │ (reports)    │   │  │                  │
│  │  └─────────┘ └──────────┘ └──────────────┘   │  │                  │
│  └──────────────────────────────────────────────┘  │                  │
└──────────────────────────────────────────────────────────────────┘
```

## Data Flow

### Order Processing

```
Shopee API  ──►  Order Polling  ──►  Event Bus  ──►  Skills
       ▲                                                    │
       │                                                    ▼
       │                                            Fulfillment Skill
       │                                                    │
       │                                                    ▼
       └────────────────  Ship Confirmation  ◄──  API Call
```

### Autonomous Decision Loop

```
┌─────────────────────────────────────────────────────────────┐
│                  AUTONOMOUS LOOP                             │
│                                                              │
│  1. Collect State ──► 2. Analyze ──► 3. Plan ──► 4. Execute │
│       ▲                                        │              │
│       └───────────────── 5. Learn ◄────────────┘              │
│                                                              │
│  - Collect: Shop state, orders, messages, metrics             │
│  - Analyze: LLM summarization, anomaly detection              │
│  - Plan: GOAP planner selects optimal skill sequence          │
│  - Execute: Run skills, call Shopee API                       │
│  - Learn: Record outcomes, adjust costs                       │
└─────────────────────────────────────────────────────────────┘
```

## Key Components

### CLI Layer
- `cli.py` — entry point, argument parsing, dispatch
- `cli_commands/` — handler modules for each command group
- `cli_completion.py` — shell completion generator

### Decision Engine
- `goap_planner.py` — A* search for optimal skill sequence
- `decision_engine.py` — orchestrates planning and execution
- `decision_memory.py` — stores and retrieves past decisions
- `strategic_planner.py` — high-level goal management

### Skills
- `skills/registry.py` — skill class registry
- `skills/base.py` — base skill class
- `skills/*.py` — individual skill implementations (24+ skills)
- `goal_library.py` — predefined goal templates
- `goal_management.py` — goal lifecycle management

### Shopee Integration
- `client.py` — Shopee Open API client (REST)
- `endpoints.py` — API endpoint catalog
- `seller_center.py` — browser automation via CDP
- `seller_center_full.py` — comprehensive Seller Center client
- `webhook_server.py` — Shopee webhook receiver
- `webhook_handlers.py` — webhook event dispatchers
- `auth.py` — OAuth flow for shop authorization
- `token_scheduler.py` — automatic token refresh

### LLM Layer
- `llm.py` — unified LLM interface
- `llm_local.py` — Ollama local inference
- `llm_providers.py` — OpenAI, Anthropic, etc.
- `llm_manager.py` — model lifecycle and fallback
- `insights_llm.py` — LLM-powered analysis

### Data Storage
- `vector_store.py` — abstract vector store interface
- `vector_store_annoy.py` — Annoy backend
- `vector_store_faiss.py` — FAISS backend
- `cognitive_memory.py` — persistent knowledge store
- `learning_db.py` — skill learning database
- `learning_system.py` — learning loop coordinator

### Infrastructure
- `event_bus.py` — async pub/sub event system
- `event_bus_backends.py` — Redis/in-memory backends
- `circuit_breaker.py` — API call protection
- `rate_limit.py` — API rate limiting
- `tracing.py` — distributed tracing
- `monitoring.py` — system monitoring
- `structured_logger.py` — JSON logging

### Security
- `auth.py` — Shopee OAuth
- `secrets_rotation.py` — automatic secret rotation
- `security_audit.py` — configuration and environment audit
- `multi_tenant.py` — multi-store isolation

## Key Design Decisions

1. **SQLite-first** — no external database required for basic operation; Redis optional for scale
2. **Local LLM default** — Ollama provides free, private inference; remote LLMs are opt-in
3. **Plugin architecture** — skills and integrations are hot-loadable
4. **Event-driven** — async event bus decouples components
5. **GOAP for planning** — flexible, learnable action selection vs rigid workflows
6. **CLI-primary** — all functionality accessible from terminal; dashboard is a convenience layer
