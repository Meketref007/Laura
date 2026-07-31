"""Centralized path configuration for Laura agent.

All hardcoded file/directory paths should be defined here and imported
by other modules. This allows changing the entire directory layout
by modifying environment variables.

Usage:
    from shopee_agent.paths import (
        REPORTS_DIR, LOGS_DIR, SECRETS_DIR, BACKUPS_DIR,
        laura_daemon_state, skill_execution_history, ...
    )
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Top-level directories ──────────────────────────────────────────────────
REPORTS_DIR = Path(os.getenv("LAURA_REPORTS_DIR", BASE_DIR / "reports"))
LOGS_DIR = Path(os.getenv("LAURA_LOGS_DIR", BASE_DIR / "logs"))
SECRETS_DIR = Path(os.getenv("LAURA_SECRETS_DIR", BASE_DIR / "secrets"))
BACKUPS_DIR = Path(os.getenv("LAURA_BACKUPS_DIR", BASE_DIR / "backups"))
DATA_DIR = Path(os.getenv("LAURA_DATA_DIR", BASE_DIR / "data"))
SKILLS_DIR = Path(os.getenv("LAURA_SKILLS_DIR", BASE_DIR / "shopee_agent" / "skills"))

# ── Ensure directories exist at import time ────────────────────────────────
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Reports files ──────────────────────────────────────────────────────────
PRODUCT_COSTS = REPORTS_DIR / "product_costs.json"
SKILL_EXECUTION_HISTORY = REPORTS_DIR / "skill_execution_history.jsonl"
GOAP_LEARNING = REPORTS_DIR / "goap_learning.json"
GOAP_LEARNING_DB = REPORTS_DIR / "goap_learning.db"
PLAN_STORE_DB = REPORTS_DIR / "plan_store.db"
DECISION_LOG = REPORTS_DIR / "decision_log.jsonl"
DECISION_OUTCOMES = REPORTS_DIR / "decision_outcomes.jsonl"
DECISION_VECTORS = REPORTS_DIR / "decision_vectors.jsonl"
GOALS_STATE = REPORTS_DIR / "goals_state.jsonl"
GOAP_STATE = REPORTS_DIR / "goap_state.json"
PROFITABILITY_LATEST = REPORTS_DIR / "laura_profitability_latest.json"
PROFITABILITY_HISTORY = REPORTS_DIR / "laura_profitability_history.jsonl"
PROFITABILITY_INPUTS = REPORTS_DIR / "laura_profitability_inputs_latest.json"
PROFITABILITY_LLM = REPORTS_DIR / "laura_profitability_llm_latest.json"
PROFITABILITY_LLM_BASELINE = REPORTS_DIR / "laura_profitability_llm_baseline_latest.json"
COMPETITIVE_OFFERS = REPORTS_DIR / "competitive_offers.jsonl"
PRODUCT_PRICES = REPORTS_DIR / "product_prices.json"
PRODUCT_CATALOG = REPORTS_DIR / "product_catalog.jsonl"
HEALTH_LATEST = REPORTS_DIR / "laura_health_latest.json"
RULES_STATE = REPORTS_DIR / "rules_state.json"
ANNOY_INDEX = REPORTS_DIR / "annoy_index.ann"
ANNOY_META = REPORTS_DIR / "annoy_meta.json"
FAISS_INDEX = REPORTS_DIR / "faiss_index.faiss"
FAISS_META = REPORTS_DIR / "faiss_meta.json"
CHAT_OUTBOUND = REPORTS_DIR / "chat_outbound.jsonl"
STOCK_PRICE_CHANGES = REPORTS_DIR / "stock_price_changes.jsonl"
CHAT_LAST_CHECK = REPORTS_DIR / "chat_last_check.txt"
CHAT_IMAGES_DIR = REPORTS_DIR / "chat_images"
LONG_TERM_MEMORY_NOTES = REPORTS_DIR / "long_term_memory_notes.jsonl"
MEMORY_REFLECTIONS = REPORTS_DIR / "memory_reflections.jsonl"
FEDERATED_LEARNING = REPORTS_DIR / "federated_learning.json"
SHARED_MODELS = REPORTS_DIR / "shared_models.json"
SKILL_CANARY = REPORTS_DIR / "skill_canary.json"
SKILL_AB_TESTS = REPORTS_DIR / "skill_ab_tests.json"
SKILL_VERSIONS = REPORTS_DIR / "skill_versions.json"
APPROVALS_DIR = REPORTS_DIR / "approvals"
PROACTIVE_LAST_RUN = REPORTS_DIR / "proactive_last_run.json"
PROACTIVE_STATE = REPORTS_DIR / "proactive_state.json"
DAILY_SUMMARY_XLSX = REPORTS_DIR / "laura_daily_summary.xlsx"
DAILY_SUMMARY_PDF = REPORTS_DIR / "laura_daily_summary.pdf"
SELLER_CENTER_SCREENSHOT = REPORTS_DIR / "seller_center_screenshot.png"
WEBHOOK_READY_GUARD = REPORTS_DIR / "laura_webhook_ready_guard.state"
VECTOR_BACKEND_CONFIG = REPORTS_DIR / "vector_backend_config.json"
API_CACHE_DIR = REPORTS_DIR / "api_cache"
PRODUCT_MARGIN_REVIEW = REPORTS_DIR / "laura_product_margin_review_latest.json"
ERP_STATE_LATEST = REPORTS_DIR / "laura_erp_state_latest.json"
COMMERCIAL_STRATEGY = REPORTS_DIR / "laura_commercial_strategy_latest.json"
INVENTORY_MONITOR = REPORTS_DIR / "laura_inventory_monitor_latest.json"
NOTIFIED_ORDERS_STATE = REPORTS_DIR / "laura_notified_orders.state"
ORDERS_NOTIFY_POLL_AUDIT = REPORTS_DIR / "laura_orders_notify_poll_audit.jsonl"
PROFITABILITY_EVENTS = REPORTS_DIR / "laura_profitability_events.jsonl"
REMEDIATION_CASES = REPORTS_DIR / "laura_remediation_cases.jsonl"
REMEDIATION_AUDIT = REPORTS_DIR / "laura_remediation_audit.jsonl"
PRODUCT_COSTS_AUDIT = REPORTS_DIR / "product_costs_audit.jsonl"
PRODUCT_COSTS_IMPORT_AUDIT = REPORTS_DIR / "product_costs_import_audit.jsonl"
PRODUCT_MARGIN_REVIEW_HISTORY = REPORTS_DIR / "laura_product_margin_review_history.jsonl"
FLASH_SALE_LATEST = REPORTS_DIR / "laura_flash_sale_recommendation_latest.json"
FLASH_SALE_HISTORY = REPORTS_DIR / "laura_flash_sale_recommendation_history.jsonl"
FLASH_SALE_RESULT = REPORTS_DIR / "laura_flash_sale_result_latest.json"
PRICING_SUGGESTIONS = REPORTS_DIR / "pricing_suggestions.json"
PRICING_COMPETITOR_CACHE = REPORTS_DIR / "pricing_competitor_cache.json"
SEARCH_CACHE = REPORTS_DIR / "search_cache.json"
SENTIMENT_ANALYSIS = REPORTS_DIR / "sentiment_analysis.json"
STOCK_PREDICTIONS = REPORTS_DIR / "stock_predictions.json"
WEEKLY_PDFS_DIR = REPORTS_DIR / "weekly_pdfs"
LAURA_DAEMON_STATE = REPORTS_DIR / "laura_daemon_state.json"

# ── Logs files ─────────────────────────────────────────────────────────────
OPERATIONS_LOG = LOGS_DIR / "laura_operations.log"

# ── Secrets files ──────────────────────────────────────────────────────────
SELLER_CENTER_CREDENTIALS = SECRETS_DIR / "seller_center_credentials.json"
SELLER_CENTER_COOKIES = SECRETS_DIR / "seller_center_cookies.json"
GMAIL_CREDENTIALS = SECRETS_DIR / "gmail_credentials.json"
GMAIL_TOKEN = SECRETS_DIR / "gmail_token.json"
GOOGLE_CREDENTIALS = SECRETS_DIR / "Credencial.Laura.json"
REPLIED_RATINGS = SECRETS_DIR / "laura_replied_ratings.json"
TELEGRAM_WEB_COOKIES = SECRETS_DIR / "telegram_web_cookies.json"
TELEGRAM_SETUP = SECRETS_DIR / "telegram_setup.json"
AUTOPILOT_CONFIG_DIR = REPORTS_DIR  # decision_integration uses secrets/ but reports/ is safer

# ── Data files ─────────────────────────────────────────────────────────────
ARTICLES_DB = DATA_DIR / "shopee_articles.db"
LEARNED_ACTIONS_DIR = DATA_DIR / "learned_actions"
LEARNED_ACTIONS_INDEX = LEARNED_ACTIONS_DIR / "index.json"

# ── Skills generated files ────────────────────────────────────────────────
GENERATED_SKILLS_DIR = SKILLS_DIR / "generated"

# ── Other files ────────────────────────────────────────────────────────────
CLOUDFLARED_CONFIG = BASE_DIR / ".cloudflared" / "config.yml"
CLOUDFLARED_EXE = BASE_DIR / "cloudflared.exe"
DAEMON_PID = BASE_DIR / "laura_daemon.pid"
WATCHDOG_PID = BASE_DIR / "laura_watchdog.pid"
WATCHDOG_SCRIPT = BASE_DIR / "tools" / "laura_watchdog.py"
ENV_FILE = BASE_DIR / ".env"

# ── Vision cache ───────────────────────────────────────────────────────────
VISION_TEMP_DIR = Path(os.getenv("LAURA_VISION_TEMP_DIR", Path.home() / ".laura_vision"))
VISION_CACHE_DIR = Path(os.getenv("LAURA_VISION_CACHE_DIR", Path.home() / ".laura_vision_cache"))


def ensure_dirs() -> None:
    """Create all known directories if they don't exist."""
    for d in [REPORTS_DIR, LOGS_DIR, SECRETS_DIR, BACKUPS_DIR, DATA_DIR,
              CHAT_IMAGES_DIR, APPROVALS_DIR, WEEKLY_PDFS_DIR, API_CACHE_DIR,
              LEARNED_ACTIONS_DIR, GENERATED_SKILLS_DIR, VISION_TEMP_DIR,
              VISION_CACHE_DIR]:
        d.mkdir(parents=True, exist_ok=True)
