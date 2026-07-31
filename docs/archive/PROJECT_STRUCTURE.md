# 📁 Project Structure - Laura (Shopee Autonomous Agent)

## Overview
Laura is an AI-powered autonomous agent for Shopee seller management, featuring order automation, profitability optimization, and real-time monitoring.

---

## 🏗️ Directory Layout

```
agente/
├── .github/                          # GitHub workflows & settings
│   └── workflows/                    # CI/CD pipelines
│
├── deploy/                           # Production deployment configs
│   ├── *.service                     # systemd unit files
│   ├── *.timer                       # systemd timer definitions
│   └── README_*.md                   # Deployment documentation
│
├── docs/                             # Project documentation
│   ├── PHASE_*.md                    # Feature phase implementations
│   ├── phases/                       # Phase summaries & reports
│   ├── deployment/                   # Deployment guides
│   ├── operations/                   # Operational procedures
│   ├── planning/                     # Planning & design docs
│   ├── audits/                       # Audit reports
│   └── artifacts/                    # Technical artifacts
│
├── logs/                             # Runtime execution logs
│   ├── *.log                         # Current logs (last 3 days)
│   └── archive/                      # Old logs (archived)
│
├── reports/                          # Runtime metrics & data
│   ├── laura_*.jsonl                 # Event logs
│   ├── laura_*_latest.json           # Latest state snapshots
│   ├── laura_*_history.jsonl         # Historical records
│   ├── *.state                       # Guard/audit state files
│   ├── webhooks/                     # Webhook logs
│   └── profitability_ingest_archive/ # Profitability data archive
│
├── scripts/                          # Shell script utilities
│   ├── laura_*.sh                    # Laura feature scripts
│   ├── telegram_*.sh                 # Telegram integration
│   └── test_*.sh                     # Test scripts
│
├── secrets/                          # 🔐 Configuration & tokens (GITIGNORED)
│   ├── api_token                     # Shopee API token
│   ├── telegram_token                # Telegram bot token
│   ├── env_*                         # Environment configs
│   └── secrets_rotation_history.jsonl# Rotation audit log
│
├── shopee_agent/                     # ⭐ Main Python package
│   ├── __init__.py                   # Package initialization
│   ├── cli.py                        # Command-line interface
│   ├── logger.py                     # Logging setup
│   │
│   ├── autonomous_loop.py            # Core autonomous cycle
│   ├── chat_auto.py                  # Chat automation with Ollama
│   ├── flash_sale_recommender.py     # Flash sales detection
│   │
│   ├── order_*.py                    # Order management modules
│   ├── profitability_*.py            # Profitability analysis
│   ├── webhook_*.py                  # Webhook handling
│   ├── telegram_bot.py               # Telegram integration
│   │
│   ├── api/                          # API client & utilities
│   ├── llm.py / llm_local.py         # LLM integration (Ollama)
│   ├── rate_limit.py                 # Rate limiting logic
│   └── monitoring.py                 # Health monitoring
│
├── tests/                            # ✅ Test suite
│   ├── test_*.py                     # Unit tests (153 tests)
│   ├── conftest.py                   # pytest configuration
│   ├── integration/                  # Integration test scripts
│   └── __pycache__/                  # (gitignored)
│
├── tools/                            # External tools & binaries
│   ├── cloudflared                   # Tunnel binary
│   ├── testing/                      # Test utilities
│   └── *.deb                         # Package files
│
├── backups/                          # Database backups
│   ├── laura_backup_*.tar.gz         # Recent backups (keep 3)
│   └── archive/                      # Old backups (7.4 MB archived)
│
├── baselines_test/                   # Test baselines (legacy)
│
├── .env                              # 🔐 Environment variables (GITIGNORED)
├── .env.example                      # Template for .env
├── .gitignore                        # Git ignore rules
│
├── README.md                         # Main documentation
├── GITHUB_SETUP.md                   # GitHub setup guide
├── RATINGS_BACKFILL_FEATURE.md       # Feature documentation
│
├── example_phase32_usage.py          # Chat automation example
├── pyproject.toml                    # Python project config
├── requirements.txt                  # Python dependencies
│
├── laura_producao.sh                 # 🚀 Production deployment script
├── deploy_production.sh              # Legacy deployment (superseded)
└── run_audit.sh                      # Audit runner script
```

---

## 📦 Key Modules

### Core Autonomous Loop
- **autonomous_loop.py** - Main cycle: collects state → analyzes → acts → reports

### Phase 32: Chat Automation
- **chat_auto.py** - Ollama-based message classification with 5 intent types
- **intent types**: tracking, deadline, cancellation, product_info, other

### Phase 33: Flash Sales
- **flash_sale_recommender.py** - Detects stalled products for promotional pricing

### Integrations
- **order_*.py** - Shopee API order management (list, detail, status)
- **profitability_*.py** - Revenue & margin analysis
- **webhook_*.py** - Real-time order event handling
- **telegram_bot.py** - Alert notifications & approvals

### Infrastructure
- **llm_local.py** - Ollama LLM client for semantic classification
- **rate_limit.py** - API rate limiting with backoff
- **monitoring.py** - Health checks & metrics

---

## 🚀 Deployment

### Production Initialization
```bash
# Run full deployment validation (10 phases)
bash laura_producao.sh

# Phases:
# 1. Environment checks (Python, pip, git)
# 2. Dependency installation
# 3. Secret validation
# 4. API connectivity
# 5. Token refresh mechanism
# 6. Ollama LLM availability
# 7. Telegram integration
# 8. Webhook server
# 9. systemd service installation (user-mode)
# 10. Cron job configuration
```

### systemd Services (User-Mode)
```bash
# Start services
systemctl --user start laura_analysis.service
systemctl --user start laura_reports.service

# View status
systemctl --user status laura_analysis.timer
systemctl --user list-timers
```

---

## 🧪 Testing

### Run All Tests
```bash
pytest tests/ -v --tb=short
# Current: 153 tests passing
```

### Test Coverage
- **test_autonomous_loop.py** - Autonomous cycle & enrichment
- **test_chat_auto.py** - Message classification & fallback
- **test_flash_sale_recommender.py** - Product stalling detection
- **test_*.py** - Order, profitability, webhook, telegram modules

---

## 🔧 Configuration

### Environment Variables
```bash
# Copy template
cp .env.example .env

# Required variables:
SHOPEE_API_KEY=<token>
TELEGRAM_BOT_TOKEN=<token>
OLLAMA_BASE_URL=http://localhost:11434
```

### Secrets Rotation
- Secrets stored in `secrets/` directory (gitignored)
- Token auto-refresh on 403 errors
- Rotation history tracked in `secrets/secrets_rotation_history.jsonl`

---

## 📊 Runtime Data

### Logs
- **Location**: `logs/` (current) + `logs/archive/` (older than 3 days)
- **Files**: Feature-specific logs (laura_*.log, token_refresh.log)
- **Size**: ~24MB (archived to manage storage)

### Reports
- **Location**: `reports/` directory
- **Types**: Metrics, events, state snapshots, audit trails
- **Format**: `.jsonl` (NDJSON) for events, `.json` for snapshots

### Backups
- **Location**: `backups/` (3 most recent) + `backups/archive/` (older)
- **Rotation**: Automated daily backups
- **Size**: ~7.4MB (archived backups)

---

## 📈 Architecture Patterns

### Order Processing Pipeline
```
collect_state() → get_order_list()
    ↓
_analyze() → get_order_detail() (enrichment)
    ↓
_process_chat_messages() → chat_auto.classify_message()
    ↓
send_notifications() / generate_actions()
```

### Chat Automation
```
user_message → Ollama LLM classification
    ├─ High confidence (≥0.6) → send predefined response
    └─ Low confidence → fallback keyword matching
```

### Flash Sales Detection
```
product_list() → filter(stock > threshold)
    ↓
filter(days_without_sales > limit)
    ↓
estimate_discount() → build_payload()
```

---

## ✅ Cleanup Summary

### Recently Cleaned
- ✅ Python caches (`__pycache__`, `.pytest_cache`, `.ruff_cache`) removed
- ✅ Old backups (20/23) archived to `backups/archive/` (-7.4MB live)
- ✅ Old logs archived to `logs/archive/` (keep last 3 days)
- ✅ Temporary files removed (nohup.out, .env.bak, etc)
- ✅ Enhanced .gitignore with complete ignore rules

### Current Storage Usage
```
tools/        38M  (cloudflared binary, test utilities)
logs/         24M  (current logs + archive)
backups/      8.9M (recent backups + archive)
reports/      2.6M (runtime metrics & snapshots)
shopee_agent/ 1.6M (source code)
scripts/      460K (shell utilities)
docs/         396K (documentation)
deploy/       52K  (systemd configs)
tests/        536K (test suite)
```

**Total Project**: ~76MB (down from ~90MB after cleanup)

---

## 📚 Documentation Index

| Document | Purpose |
|----------|---------|
| README.md | Main project overview |
| GITHUB_SETUP.md | GitHub configuration guide |
| PHASE_32_IMPLEMENTATION_REPORT.md | Chat automation details |
| PHASE_33_FLASH_SALES.md | Flash sales feature spec |
| deploy/README_DEPLOY.md | Deployment procedures |
| docs/deployment/ | Environment-specific guides |

---

## 🎯 Next Steps

1. **Monitor** - Track autonomous-loop execution in production
2. **Validate** - Test chat automation response accuracy
3. **Optimize** - Measure Ollama latency under load
4. **Plan** - Design Phase 34 features (if needed)

---

*Last Updated: 2026-05-13*  
*Project: Laura v1.0 (Phase 32-33 complete)*
