"""
Daemon principal da Laura.

Roda em loop continuo: coleta dados, analisa, notifica workers.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from typing import Optional

import requests

from shopee_agent.ceo_mode import ceo_mode_enabled
from shopee_agent.graceful_shutdown import GracefulShutdown

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Carregar .env manualmente
env_path = BASE_DIR / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip("\"'")
        if not os.environ.get(key):
            os.environ[key] = val

from shopee_agent.article_scraper import scrape_all
from shopee_agent.auto_login import login_via_cdp_completo, renovar_cookies_via_cdp
from shopee_agent.autonomous_loop import AutonomousLoop
from shopee_agent.backup import executar as executar_backup
from shopee_agent.chat_monitor import ChatMonitor
from shopee_agent.cli import _upsert_env_values
from shopee_agent.client import ShopeeClient
from shopee_agent.config import load_config
from shopee_agent.event_bus import AsyncEventBus
from shopee_agent.llm_manager import garantir_todos_modelos
from shopee_agent.logger import error as log_error
from shopee_agent.logger import info, warning
from shopee_agent.persistent_state import PersistentState
from shopee_agent.product_scraper import scrape_all_products
from shopee_agent.rating_reply import processar_avaliacoes_pendentes
from shopee_agent.resumo_diario import deve_postar_agora, postar_resumo
from shopee_agent.seller_center import SellerCenterClient, load_cookies
from shopee_agent.seller_center import load_cookies as load_seller_cookies
from shopee_agent.site_scraper import init_content_db, scrape_all_content
from shopee_agent.vilu_workers import _post, enviar_para_canal
from shopee_agent.worker_bots import iniciar_todos_workers, parar_todos_workers
from shopee_agent.workers import DecisionWorker, MetricWorker, NotificationWorker, OutcomeWorker

CYCLE_INTERVAL = int(os.getenv("VILU_DAEMON_INTERVAL", "300"))  # 5 min default
BACKUP_INTERVAL = int(os.getenv("VILU_BACKUP_INTERVAL", "86400"))  # 24h default
AUTO_LOGIN_INTERVAL = int(os.getenv("LAURA_AUTO_LOGIN_INTERVAL", "21600"))  # 6h default


def _telegram_bot_already_running() -> bool:
    """Detecta se o telegram-bot ja roda em processo separado (evita polling duplo)."""
    try:
        import subprocess

        if os.name == "nt":
            out = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_Process).CommandLine | Select-String 'telegram-bot' | Measure-Object | Select-Object -ExpandProperty Count",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            ).stdout
        else:
            out = subprocess.run(
                ["ps", "-ef"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
        return out.strip() not in ("", "0")
    except Exception:
        return False


class LauraDaemon:
    def __init__(self, reports_dir: str | Path = "reports"):
        self._reports_dir = Path(reports_dir)
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        self._running = False
        self._cfg: Optional = None
        self._client: Optional = None
        self._seller_client: Optional = None
        self._loop: AutonomousLoop | None = None
        self._chat_monitor: ChatMonitor | None = None
        self._event_bus: AsyncEventBus | None = None
        self._metric_worker: MetricWorker | None = None
        self._cycle_counter: int = 0
        self._ultimo_backup: float = 0
        self._ultimo_resumo: str = ""
        self._last_analytics: float = 0
        self._last_predictive: float = 0
        self._last_competitive: float = 0
        self._last_monitoring: float = 0
        self._last_learning: float = 0
        self._last_adaptive_rules: float = 0
        self._last_flash_sale: float = 0
        self._last_health_check: float = 0
        self._last_token_refresh: float = 0
        self._last_rating_reply: float = 0
        self._last_alerts: float = 0
        self._last_insights: float = 0
        self._last_profitability: float = 0
        self._last_articles: float = 0
        self._last_products: float = 0
        self._last_daily_tip: float = 0
        self._last_pricing: float = 0
        self._last_stock_prediction: float = 0
        self._last_sentiment: float = 0
        self._last_weekly_report: float = 0
        self._last_proactive: float = 0
        self._last_goal_suggest: float = 0
        self._last_cycle_result: dict | None = None
        self._last_search_update: float = 0
        self._last_week_num: int = 0
        self._tunnel_process: subprocess.Popen | None = None
        self._state = PersistentState(self._reports_dir / "laura_daemon_state.json")
        self._carregar_estado()
        self._shutdown = GracefulShutdown(timeout=30.0)

        # Background thread for auto-login
        try:
            self._auto_login_thread = Thread(target=self._auto_login_worker, daemon=True)
            self._auto_login_thread.start()
        except Exception as e:
            print(f"[LauraDaemon] Auto-login thread error: {e}")

        # Background thread for continuous LLM analysis (keeps GPU active 24/7)
        try:
            self._llm_thread = Thread(target=self._llm_worker, daemon=True)
            self._llm_thread.start()
        except Exception as e:
            print(f"[LauraDaemon] LLM worker thread error: {e}")

    def _carregar_estado(self) -> None:
        self._last_analytics = self._state.get("last_analytics")
        self._last_predictive = self._state.get("last_predictive")
        self._last_competitive = self._state.get("last_competitive")
        self._last_monitoring = self._state.get("last_monitoring")
        self._last_learning = self._state.get("last_learning")
        self._last_flash_sale = self._state.get("last_flash_sale")
        self._last_health_check = self._state.get("last_health_check")
        self._last_token_refresh = self._state.get("last_token_refresh")
        self._last_rating_reply = self._state.get("last_rating_reply")
        self._last_alerts = self._state.get("last_alerts")
        self._last_insights = self._state.get("last_insights")
        self._last_profitability = self._state.get("last_profitability")
        self._last_articles = self._state.get("last_articles")
        self._last_products = self._state.get("last_products")
        self._last_daily_tip = self._state.get("last_daily_tip")
        self._last_pricing = self._state.get("last_pricing")
        self._last_stock_prediction = self._state.get("last_stock_prediction")
        self._last_sentiment = self._state.get("last_sentiment")
        self._last_weekly_report = self._state.get("last_weekly_report")
        self._last_proactive = self._state.get("last_proactive")
        self._last_goal_suggest = self._state.get("last_goal_suggest", 0)
        self._last_search_update = self._state.get("last_search_update")
        self._ultimo_backup = self._state.get("ultimo_backup")

    def _salvar_estado(self) -> None:
        self._state.update_and_save("last_analytics", self._last_analytics)
        self._state.update_and_save("last_predictive", self._last_predictive)
        self._state.update_and_save("last_competitive", self._last_competitive)
        self._state.update_and_save("last_monitoring", self._last_monitoring)
        self._state.update_and_save("last_learning", self._last_learning)
        self._state.update_and_save("last_flash_sale", self._last_flash_sale)
        self._state.update_and_save("last_health_check", self._last_health_check)
        self._state.update_and_save("last_token_refresh", self._last_token_refresh)
        self._state.update_and_save("last_rating_reply", self._last_rating_reply)
        self._state.update_and_save("last_alerts", self._last_alerts)
        self._state.update_and_save("last_insights", self._last_insights)
        self._state.update_and_save("last_profitability", self._last_profitability)
        self._state.update_and_save("last_articles", self._last_articles)
        self._state.update_and_save("last_products", self._last_products)
        self._state.update_and_save("last_daily_tip", self._last_daily_tip)
        self._state.update_and_save("last_pricing", self._last_pricing)
        self._state.update_and_save("last_stock_prediction", self._last_stock_prediction)
        self._state.update_and_save("last_sentiment", self._last_sentiment)
        self._state.update_and_save("last_weekly_report", self._last_weekly_report)
        self._state.update_and_save("last_proactive", self._last_proactive)
        self._state.update_and_save("last_goal_suggest", self._last_goal_suggest)
        self._state.update_and_save("last_search_update", self._last_search_update)
        self._state.update_and_save("ultimo_backup", self._ultimo_backup)

    def _auto_login_worker(self) -> None:
        try:
            from shopee_agent.auto_login import auto_login_loop
            credentials_file = os.getenv("GMAIL_CREDENTIALS_FILE", "secrets/gmail_credentials.json")
            token_file = os.getenv("GMAIL_TOKEN_FILE", "secrets/gmail_token.json")
            auto_login_loop(
                credentials_file=credentials_file,
                token_file=token_file,
                interval_hours=AUTO_LOGIN_INTERVAL // 3600,
            )
        except ImportError:
            print("[LauraDaemon] auto_login module not available (skip)")
        except Exception as e:
            print(f"[LauraDaemon] Auto-login worker error: {e}")

    def _llm_worker(self) -> None:
        """Background thread that continuously runs LLM analysis every 5min.

        Keeps the LLM GPU active and sends periodic store insights to Telegram.
        """
        llm_insights_path = self._reports_dir / "laura_llm_insights.jsonl"
        llm_model = os.getenv("LAURA_LLM_MODEL", "llama3.2:3b")
        ollama_host = os.getenv("LAURA_OLLAMA_HOST", "http://127.0.0.1:11434")
        import time as _time
        _time.sleep(15)
        last_telegram = 0
        while True:
            try:
                seller = SellerCenterClient()
                shop_info = seller.get_shop_info() if seller.is_authenticated() else {}
                user_info = seller.get_user_info() if seller.is_authenticated() else {}
                todo = seller.get_todo_summary() if seller.is_authenticated() else {}
                rating = seller.get_rating_dashboard() if seller.is_authenticated() else {}

                prompt_parts = [
                    f"You are Laura, an AI assistant for Shopee store '{shop_info.get('name', 'ViluShop')}'.",
                    "Current store state:",
                    f"- Vacation mode: {user_info.get('holiday_mode_on', '?')}",
                    f"- Orders to process: {todo.get('shipment_to_process', 0)}",
                    f"- Returns/refunds: {todo.get('order_return_refund_cancel', 0)}",
                    f"- Products banned/deboosted: {todo.get('product_banned_deboosted', 0)}",
                    f"- Recent ratings: {rating.get('metric', {}).get('ratings_received', 0)}",
                    f"- Good rating rate: {rating.get('metric', {}).get('good_rating_rate', 0)*100:.0f}%",
                    "",
                    'Respond ONLY with a short JSON: {"summary":"1 line","alert":"urgent issue or none","recommendation":"what to do","confidence":0.0-1.0}',
                ]
                prompt = "\n".join(prompt_parts)

                resp = requests.post(
                    f"{ollama_host}/api/generate",
                    json={"model": llm_model, "prompt": prompt, "stream": False},
                    timeout=120,
                )
                if resp.status_code == 200:
                    raw = resp.json().get("response", "")
                    entry = {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "model": llm_model,
                        "raw_response": raw,
                    }
                    llm_insights_path.parent.mkdir(parents=True, exist_ok=True)
                    with llm_insights_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

                    # Enviar alerta ao Telegram a cada ~30min se houver alerta urgente
                    if _time.time() - last_telegram > 1800:
                        try:
                            parsed = json.loads(raw)
                            alert = parsed.get("alert", "").strip()
                            if alert and alert.lower() not in ("none", "nenhum", "", "no alerts"):
                                from shopee_agent.vilu_workers import enviar_para_canal
                                enviar_para_canal("sistema", f"🤖 *LLM Alert*\n{alert}")
                                last_telegram = _time.time()
                        except Exception:
                            pass
            except Exception:
                pass
            _time.sleep(300)  # 5 min entre analises

    def _setup(self) -> bool:
        try:
            # Garantir modelos LLM e visao
            ok = garantir_todos_modelos()
            if not ok:
                print("[LauraDaemon] Modelos LLM nao disponiveis")
                return False

            self._cfg = load_config()
            self._client = ShopeeClient(self._cfg)
            token = self._cfg.default_access_token
            shop = self._cfg.default_shop_id

            # Iniciar Event Bus + Workers (Phase 36)
            bus = None
            try:
                bus = AsyncEventBus(
                    worker_count=3,
                    max_retries=3,
                    retry_backoff=1.0,
                    journal_path=str(self._reports_dir / "event_journal.jsonl"),
                )
                bus.start()

                from shopee_agent.decision_engine import DecisionEngine, create_default_rules
                from shopee_agent.decision_integration import DecisionExecutor, DecisionIntegrator
                from shopee_agent.decision_memory import MemoryLayer

                eng = DecisionEngine(store_id=str(shop or "default"), rules=create_default_rules())
                ml = MemoryLayer(path="reports/decision_outcomes.jsonl")

                integ = DecisionIntegrator(engine=eng, store_id=str(shop or "default"), metrics_dir=str(self._reports_dir))
                exec_obj = DecisionExecutor(store_id=str(shop or "default"), engine=eng, client=self._client)

                dw = DecisionWorker(bus, engine=eng, executor=exec_obj, integrator=integ)
                dw.subscribe()
                ow = OutcomeWorker(bus, engine=eng, memory_layer=ml)
                ow.subscribe()
                self._metric_worker = MetricWorker(bus)
                self._metric_worker.subscribe()
                nw = NotificationWorker(bus, telegram_sender=enviar_para_canal)
                nw.subscribe()

                from shopee_agent.workers import AutoSkillWorker, OrchestrationWorker, PlanningWorker, RefundWorker
                OrchestrationWorker(bus, executor=exec_obj).subscribe()
                PlanningWorker(bus, executor=exec_obj).subscribe()
                RefundWorker(bus).subscribe()
                AutoSkillWorker(bus, registry=None, interval_seconds=300).subscribe()

                self._event_bus = bus
                info("Event bus started with workers", workers=7)

                # Conecta webhook handlers -> event bus
                from shopee_agent.webhook_handlers import set_event_bus
                set_event_bus(bus)

                # Passa engine singleton para o AutonomousLoop
                self._loop = AutonomousLoop(
                    client=self._client,
                    access_token=token,
                    shop_id=shop,
                    reports_dir=self._reports_dir,
                    event_bus=bus,
                    external_engine=eng,
                    external_integrator=integ,
                    enable_auto_skills=True,
                )
            except Exception as e:
                warning(f"Event bus setup failed: {e}")
                self._event_bus = None
                self._loop = AutonomousLoop(
                    client=self._client,
                    access_token=token,
                    shop_id=shop,
                    reports_dir=self._reports_dir,
                )

            # Iniciar monitor de chat com SellerCenterClient (cookie-based)
            seller_session = load_seller_cookies()
            seller_client = SellerCenterClient(session=seller_session) if seller_session else None
            self._seller_client = seller_client
            self._chat_monitor = ChatMonitor(
                client=self._client,
                access_token=str(token or ""),
                shop_id=int(shop or 0),
                auto_reply=True,
                seller_center_client=seller_client,
            )
            self._chat_monitor.start()

            # Iniciar workers bots (respondem comandos no privado)
            try:
                iniciar_todos_workers()
                print("[LauraDaemon] Workers bots iniciados")
            except Exception as e:
                print(f"[LauraDaemon] Workers bots error: {e}")

            # Tentar registrar webhook na Shopee (pode falhar se API nao disponivel)
            try:
                from shopee_agent.shopee_webhook import list_webhooks
                hooks = list_webhooks()
                print(f"[LauraDaemon] Webhooks: {len(hooks)} encontrado(s)")
            except Exception as e:
                print(f"[LauraDaemon] Webhook check: {e} (continue mode)")

            # Iniciar servidor webhook local (recebe notificacoes push da Shopee)
            try:
                webhook_host = os.getenv("LAURA_WEBHOOK_HOST", "127.0.0.1")
                webhook_port = int(os.getenv("LAURA_WEBHOOK_PORT", "8766"))
                webhook_secret = os.getenv("LAURA_WEBHOOK_SECRET", "")
                from shopee_agent.webhook_handlers import initialize_handlers
                from shopee_agent.webhook_server import initialize_webhook_server
                self._webhook_server = initialize_webhook_server(
                    host=webhook_host,
                    port=webhook_port,
                    secret_key=webhook_secret if webhook_secret else None,
                    allow_unverified_ack=True,
                )
                initialize_handlers(self._webhook_server)
                self._webhook_server.start()
                print(f"[LauraDaemon] Webhook server started on {webhook_host}:{webhook_port}")
            except Exception as e:
                print(f"[LauraDaemon] Webhook server error: {e}")
                self._webhook_server = None

            self._start_tunnel()

            return bool(token and shop)
        except Exception as e:
            print(f"[LauraDaemon] Setup error: {e}")
            return False

    def _start_tunnel(self) -> None:
        cloudflared = BASE_DIR / "cloudflared.exe"
        config = BASE_DIR / ".cloudflared" / "config.yml"
        if cloudflared.exists() and config.exists():
            try:
                log_file = open(self._reports_dir / "cloudflared.log", "a", encoding="utf-8")
                self._tunnel_process = subprocess.Popen(
                    [str(cloudflared), "tunnel", "--config", str(config), "run"],
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                )
                print(f"[LauraDaemon] Cloudflare named tunnel started (PID={self._tunnel_process.pid})")
                print("[LauraDaemon] Domain: webhook.agentelaura.uk -> localhost:8766")
                # Salvar URLs fixas
                (self._reports_dir / "laura_webhook_tunnel_latest.txt").write_text("https://webhook.agentelaura.uk")
                cb = f"https://webhook.agentelaura.uk{os.getenv('LAURA_WEBHOOK_PATH', '/webhook/shopee')}"
                (self._reports_dir / "laura_webhook_callback_latest.txt").write_text(cb)
            except Exception as e:
                print(f"[LauraDaemon] Tunnel start error: {e}")
        else:
            print("[LauraDaemon] cloudflared.exe or config.yml not found, tunnel skipped")

    def _monitor_tunnel_url(self) -> None:
        pass  # Tunnel nomeado usa URL fixa, nao precisa monitorar

    def _stop_tunnel(self) -> None:
        if self._tunnel_process is not None:
            try:
                self._tunnel_process.terminate()
                self._tunnel_process.wait(timeout=5)
                print("[LauraDaemon] Cloudflare tunnel stopped")
            except Exception as e:
                print(f"[LauraDaemon] Tunnel stop error: {e}")
            self._tunnel_process = None

    def _refresh_token(self) -> bool:
        """Renova access_token se estiver perto de expirar (token expira em 4h)."""
        agora = time.time()
        if agora - self._last_token_refresh < 10800:  # 3h entre renovacoes
            return True
        try:
            cfg = load_config()
            if not cfg.default_refresh_token or cfg.default_shop_id is None:
                return False
            client = ShopeeClient(cfg)
            resp = client.refresh_token(
                refresh_token=cfg.default_refresh_token,
                shop_id=cfg.default_shop_id,
            )
            data = resp.data if isinstance(resp.data, dict) else {}
            new_token = str(data.get("access_token", "")).strip()
            new_refresh = str(data.get("refresh_token", "")).strip()
            if new_token and new_refresh:
                import shutil
                env_path = Path(".env")
                if env_path.exists():
                    bak = env_path.with_suffix(".env.bak")
                    shutil.copy2(str(env_path), str(bak))
                _upsert_env_values(env_path, {
                    "SHOPEE_DEFAULT_ACCESS_TOKEN": new_token,
                    "SHOPEE_DEFAULT_REFRESH_TOKEN": new_refresh,
                })
                self._last_token_refresh = agora
                print("[LauraDaemon] Token refreshed successfully")
                return True
        except Exception as e:
            print(f"[LauraDaemon] Token refresh error: {e}")
        return False

    def _health_check(self) -> None:
        erros = []
        checks = {}

        try:
            r = requests.get("http://127.0.0.1:11434/api/tags", timeout=5)
            ollama_ok = r.status_code == 200
            checks["ollama"] = "ok" if ollama_ok else f"status={r.status_code}"
            if not ollama_ok:
                erros.append("Ollama nao respondeu (status=%d)" % r.status_code)
        except Exception as e:
            checks["ollama"] = f"erro: {e}"
            erros.append("Ollama erro: %s" % e)

        try:
            r = requests.get("http://127.0.0.1:8766/health", timeout=5)
            webhook_ok = r.status_code == 200
            checks["webhook"] = "ok" if webhook_ok else f"status={r.status_code}"
            if not webhook_ok:
                erros.append("Webhook nao respondeu (status=%d)" % r.status_code)
        except Exception as e:
            checks["webhook"] = f"erro: {e}"
            erros.append("Webhook erro: %s" % e)

        checks["thread"] = "ok" if self._running else "parada"
        if not self._running:
            erros.append("Thread daemon nao esta viva")

        # Verifica sessao do Seller Center
        seller_ok = False
        try:
            seller_session = load_cookies()
            seller_ok = seller_session is not None and seller_session.is_valid()
            checks["seller_session"] = "ok" if seller_ok else "INVALIDA"
        except Exception as e:
            checks["seller_session"] = f"erro: {e}"
            log_error(f"Erro ao verificar sessao Seller Center: {e}")

        # Event Bus stats
        bus = self._event_bus
        if bus:
            stats = bus.stats()
            checks["event_bus"] = f"queued={stats.queued} processed={stats.processed} failed={stats.failed}"
            if self._metric_worker:
                mm = self._metric_worker.get_metrics()
                checks["total_decisions"] = str(mm.get("total_decisions", 0))
                checks["success_rate"] = f"{self._metric_worker.get_success_rate():.0%}"

        if erros:
            msg = "\n".join(erros)
            print("[LauraDaemon] Health check FAIL: %s" % msg)
            try:
                enviar_para_canal("sistema", "\u26a0\ufe0f *Health Check*\n" + msg)
            except Exception:
                pass
        else:
            status_str = " | ".join(f"{k}={v}" for k, v in checks.items())
            print(f"[LauraDaemon] Health check OK | {status_str}")

        # Self-healing evaluation and circuit-breaker auto-reset
        try:
            from shopee_agent.self_healing import SelfHealingCoordinator
            healer = SelfHealingCoordinator()
            snapshot = healer.evaluate()
            checks["self_healing"] = f"status={snapshot.status} score={snapshot.resilience_score}"
            if snapshot.open_circuits > 0 or snapshot.critical_alerts > 0:
                erros.append(f"Self-healing: {snapshot.open_circuits} open circuits, {snapshot.critical_alerts} critical alerts")
                recovery = healer.run_recovery_plan(auto_reset=True)
                reset_count = len(recovery.get("reset_results", []))
                if reset_count:
                    checks["circuit_breaker_reset"] = f"{reset_count} reset"
            checks["dlq_count"] = str(len(bus.dlq())) if bus else "0"
        except Exception as e:
            checks["self_healing"] = f"erro: {e}"

        # Tenta renovar sessao se invalida
        if not seller_ok:
            warning("Sessao Seller Center INVALIDA - tentando renovar...")
            try:
                if renovar_cookies_via_cdp():
                    info("Cookies renovados via CDP com sucesso")
                else:
                    log_error("Falha ao renovar cookies via CDP, tentando login completo...")
                    try:
                        if login_via_cdp_completo():
                            info("Re-login via CDP completo realizado")
                        else:
                            log_error("Falha no re-login via CDP completo")
                    except Exception as e2:
                        log_error(f"Excecao no login completo: {e2}")
            except Exception as e1:
                log_error(f"Excecao ao renovar cookies: {e1}")

        # Auto-refresh token a cada 3h
        self._refresh_token()

        self._last_health_check = time.time()

    def _cycle(self) -> dict:
        ts = datetime.now(UTC).isoformat()
        if not self._loop:
            return {"timestamp": ts, "error": "not_initialized"}

        result = self._loop.run_cycle()
        self._last_cycle_result = result
        result["timestamp"] = ts
        result["cycle_at"] = ts

        # Log resumo
        orders = result.get("cycle_result", {}).get("orders_seen", 0)
        executed = len(result.get("executed", []))
        info("Cycle done", orders=orders, executed=executed)

        self._cycle_counter += 1

        # Pricing automation (every N cycles)
        pricing_interval = int(os.getenv("PRICING_CYCLE_INTERVAL", "5"))
        if self._cycle_counter % pricing_interval == 0:
            try:
                from .pricing_automation import DynamicPricingEngine
                p_engine = DynamicPricingEngine(client=self._client)
                items = self._client.get_item_list(limit=200) if self._client else {"item_list": []}
                item_list = items.get("item_list", items.get("items", []))
                has_local = False
                try:
                    from shopee_agent.pricing_automation import _cached_competitor_prices
                    has_local = True
                except ImportError:
                    pass
                comp_cache = _cached_competitor_prices() if has_local else {}
                results = p_engine.analyze_all_items(item_list, comp_cache)
                if results:
                    report = p_engine.generate_report(results)
                    info("Pricing analysis complete", items_analyzed=len(results))
                    try:
                        from .telegram_narrator import narrador
                        narrador.info(f"Analise de precos: {len(results)} itens analisados")
                    except ImportError:
                        pass
            except Exception as exc:
                warning("Pricing automation failed", error=str(exc))

        agora = time.time()

        # Backup periodico (a cada BACKUP_INTERVAL segundos)
        if agora - self._ultimo_backup > BACKUP_INTERVAL:
            try:
                bk = executar_backup()
                print(f"[LauraDaemon] Backup: {bk['destino']}")
                self._ultimo_backup = agora
            except Exception as e:
                print(f"[LauraDaemon] Backup error: {e}")

        # Resumo diario (uma vez por dia no horario certo)
        if deve_postar_agora():
            data_hoje = datetime.now(UTC).strftime("%Y-%m-%d")
            if self._ultimo_resumo != data_hoje:
                try:
                    token = self._cfg.default_access_token if self._cfg else None
                    shop = self._cfg.default_shop_id if self._cfg else None
                    if token and shop and self._client:
                        postar_resumo(self._client, token, shop)
                        print("[LauraDaemon] Resumo diario postado")
                        self._ultimo_resumo = data_hoje
                except Exception as e:
                    print(f"[LauraDaemon] Resumo error: {e}")

        # analytics_trending (a cada 12h)
        if agora - self._last_analytics > 12 * 3600:
            try:
                from shopee_agent.analytics_trending import AdvancedAnalytics
                aa = AdvancedAnalytics(reports_dir=str(self._reports_dir))
                report = aa.get_trending_report()
                _post("sistema", f"📊 *Analytics & Trending*\n{json.dumps(report, indent=2, ensure_ascii=False)}")
                print("[LauraDaemon] analytics_trending OK")
            except Exception as e:
                print(f"[LauraDaemon] analytics_trending: {e}")
            self._last_analytics = agora

        # predictive_analytics (diario - 30d forecast)
        if agora - self._last_predictive > 24 * 3600:
            try:
                from shopee_agent.predictive_analytics import PredictiveAnalytics
                pa = PredictiveAnalytics(reports_dir=str(self._reports_dir))
                snapshot = pa.forecast_overview(horizon_days=30)
                _post("sistema", f"🔮 *Predictive Analytics (30d)*\n{json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False)}")
                print("[LauraDaemon] predictive_analytics OK")
            except Exception as e:
                print(f"[LauraDaemon] predictive_analytics: {e}")
            self._last_predictive = agora

        # competitive_intelligence (a cada 6h)
        if agora - self._last_competitive > 6 * 3600:
            try:
                from shopee_agent.competitive_intelligence import CompetitiveIntelligence
                ci = CompetitiveIntelligence(path=str(self._reports_dir / "competitive_offers.jsonl"))
                # Scrape competitors before generating snapshot
                scraped = ci.scrape_competitors(max_per_item=3)
                if scraped:
                    print(f"[LauraDaemon] competitive_intelligence: {scraped} offers scraped")
                snap = ci.snapshot()
                _post("sistema", f"🏪 *Competitive Intelligence*\n{json.dumps(snap.to_dict(), indent=2, ensure_ascii=False)}")
                print("[LauraDaemon] competitive_intelligence OK")
            except Exception as e:
                print(f"[LauraDaemon] competitive_intelligence: {e}")
            self._last_competitive = agora

        # monitoring_dashboard (a cada 4h)
        if agora - self._last_monitoring > 4 * 3600:
            try:
                from shopee_agent.monitoring_dashboard import MonitoringDashboard
                md = MonitoringDashboard(reports_dir=str(self._reports_dir))
                metrics = md.get_store_metrics()
                _post("sistema", f"📈 *Monitoring Dashboard*\n{json.dumps(metrics, indent=2, ensure_ascii=False)}")
                print("[LauraDaemon] monitoring_dashboard OK")
            except Exception as e:
                print(f"[LauraDaemon] monitoring_dashboard: {e}")
            self._last_monitoring = agora

        # learning_system (a cada 6h)
        if agora - self._last_learning > 6 * 3600:
            try:
                from shopee_agent.learning_system import LearningSystem
                ls = LearningSystem()
                report = ls.evaluate(window_days=7)
                _post("sistema", f"🧠 *Learning System*\n{json.dumps(report.to_dict(), indent=2, ensure_ascii=False)}")
                print("[LauraDaemon] learning_system OK")
            except Exception as e:
                print(f"[LauraDaemon] learning_system: {e}")
            self._last_learning = agora

        # adaptive rules learning (a cada 6h)
        if agora - self._last_adaptive_rules > 6 * 3600:
            try:
                from shopee_agent.decision_engine import DecisionEngine, DecisionRule, create_default_rules
                from shopee_agent.decision_memory import MemoryLayer
                mem = MemoryLayer(path="reports/decision_outcomes.jsonl")
                rules_file = Path("reports") / "rules_state.json"
                if rules_file.exists():
                    with open(rules_file) as f:
                        data = json.load(f)
                        rules = [DecisionRule.from_dict(r) for r in data.get("rules", [])]
                else:
                    rules = create_default_rules()
                engine = DecisionEngine(store_id="default", rules=rules)
                adjusted = []
                for rule_id, rule in engine.rules.items():
                    eff = mem.get_rule_effectiveness(rule_id)
                    if hasattr(rule, "effectiveness_score"):
                        rule.effectiveness_score = eff
                    rule.last_success_rate = eff
                    if hasattr(rule, "adjust_based_on_outcomes"):
                        rule.adjust_based_on_outcomes(eff)
                    adjusted.append(rule_id)
                # Persist adjusted rules
                rules_file.parent.mkdir(parents=True, exist_ok=True)
                with open(rules_file, "w") as f:
                    json.dump({"rules": [r.to_dict() for r in engine.rules.values()]}, f, indent=2)
                info("Adaptive rules adjusted", rules=len(adjusted))
                print(f"[LauraDaemon] adaptive_rules: {len(adjusted)} rule(s) adjusted")
            except Exception as e:
                print(f"[LauraDaemon] adaptive_rules: {e}")
            self._last_adaptive_rules = agora

        # flash_sale_recommender (diario)
        if agora - self._last_flash_sale > 24 * 3600:
            try:
                token = self._cfg.default_access_token if self._cfg else None
                shop = self._cfg.default_shop_id if self._cfg else None
                if token and shop and self._client:
                    from shopee_agent.flash_sale_recommender import FlashSaleRecommender
                    fsr = FlashSaleRecommender(
                        client=self._client,
                        access_token=token,
                        shop_id=shop,
                        reports_dir=self._reports_dir,
                    )
                    rec = fsr.generate_recommendations()
                    _post("sistema", f"⚡ *Flash Sale Recommender*\n{json.dumps(fsr.summarize(rec), indent=2, ensure_ascii=False)}")
                    print("[LauraDaemon] flash_sale_recommender OK")
            except Exception as e:
                print(f"[LauraDaemon] flash_sale_recommender: {e}")
            self._last_flash_sale = agora

        # alerts_engine (a cada 1h)
        if agora - self._last_alerts > 3600:
            try:
                from shopee_agent.alerts import create_alerts_engine, get_default_alert_config
                engine = create_alerts_engine()
                config = get_default_alert_config()
                metrics = {
                    "margin_pct": 15.0,
                    "order_count": result.get("cycle_result", {}).get("orders_seen", 0),
                    "health_score": result.get("health_score", 100),
                    "error_rate": 0.0,
                    "latency_ms": 0,
                    "cpu_pct": 0,
                    "memory_pct": 0,
                    "ollama_running": True,
                }
                alert_list = engine.evaluate(metrics, config)
                for a in alert_list:
                    from shopee_agent.vilu_workers import enviar_para_canal
                    enviar_para_canal("sistema", f"🚨 *{a.severity}: {a.title}*\n{a.message}")
                    print(f"[LauraDaemon] Alert: {a.severity} - {a.title}")
                self._last_alerts = agora
            except Exception as e:
                print(f"[LauraDaemon] alerts_engine error: {e}")

        # insights_llm (a cada 6h)
        if agora - self._last_insights > 6 * 3600:
            try:
                from shopee_agent.insights_llm import InsightsAnalyzer
                ia = InsightsAnalyzer(reports_dir=str(self._reports_dir))
                summary = ia.generate_executive_summary(days=7, language="pt_BR")
                if summary and isinstance(summary, dict):
                    txt = summary.get("ai_analysis", summary.get("reasoning", str(summary)))
                    _post("sistema", f"🧠 *Insights LLM (7d)*\n{txt[:2000]}")
                    print("[LauraDaemon] insights_llm OK")
                recom = ia.generate_smart_recommendations(context="daily_operations", language="pt_BR")
                if recom and isinstance(recom, dict):
                    rtxt = recom.get("ai_recommendations", str(recom))
                    _post("sistema", f"💡 *Recomendacoes LLM*\n{rtxt[:2000]}")
                self._last_insights = agora
            except Exception as e:
                print(f"[LauraDaemon] insights_llm error: {e}")

        # analyze_profitability (a cada 24h)
        if agora - self._last_profitability > 24 * 3600:
            try:
                from shopee_agent.llm_local import LauraOllamaAnalyzer
                llm_model = os.getenv("LAURA_LLM_MODEL", "llama3.2:3b")
                analyzer = LauraOllamaAnalyzer(model=llm_model)
                metrics = {
                    "revenue": result.get("cycle_result", {}).get("revenue", 0),
                    "cogs": result.get("cycle_result", {}).get("cogs", 0),
                    "ad_spend": 0,
                    "shipping_subsidy": 0,
                    "refunds": result.get("cycle_result", {}).get("refunds", 0),
                    "orders": result.get("cycle_result", {}).get("orders_seen", 0),
                }
                profit_result = analyzer.analyze_profitability(metrics=metrics)
                if profit_result:
                    text = str(profit_result)
                    _post("financeiro", f"💰 *Analise de Rentabilidade*\n{text[:2000]}")
                    print("[LauraDaemon] profitability analysis OK")
                self._last_profitability = agora
            except Exception as e:
                print(f"[LauraDaemon] profitability error: {e}")

        # rating_reply (a cada 2h)
        if agora - self._last_rating_reply > 2 * 3600:
            try:
                stats = processar_avaliacoes_pendentes()
                if stats.get("respondidas", 0) > 0:
                    print(f"[LauraDaemon] Rating reply: {stats['respondidas']} respondidas")
                self._last_rating_reply = agora
            except Exception as e:
                print(f"[LauraDaemon] rating_reply error: {e}")

        # article_scraper (a cada 30 dias)
        ARTICLES_INTERVAL = 30 * 24 * 3600
        if agora - self._last_articles > ARTICLES_INTERVAL:
            try:
                result_arts = scrape_all(force=False)
                total = result_arts.get("total_articles_found", 0)
                novos = result_arts.get("total_articles_new", 0)
                print(f"[LauraDaemon] Articles scraped: {total} total, {novos} novos")
                if novos > 0:
                    _post("sistema",
                        f"📰 *Artigos Shopee Atualizados*\n"
                        f"{novos} novos artigos encontrados\n"
                        f"{total} artigos no total")
                self._last_articles = agora
            except Exception as e:
                print(f"[LauraDaemon] article_scraper error: {e}")

        # site_scraper (blog + cursos + webinars, a cada 30 dias junto com artigos)
        if agora - self._last_articles > ARTICLES_INTERVAL:
            try:
                init_content_db()
                result_site = scrape_all_content(force=False)
                total = result_site.get("total_found", 0)
                novos = result_site.get("total_new", 0)
                print(f"[LauraDaemon] Site content scraped: {total} found, {novos} novos")
                if novos > 0:
                    blog_n = result_site.get("blog", {}).get("new", 0)
                    course_n = result_site.get("courses", {}).get("new", 0)
                    _post("sistema",
                        f"🌐 *Conteudo do Site Atualizado*\n"
                        f"{novos} novos itens ({blog_n} blog, {course_n} cursos)\n"
                        f"{total} itens no total")
            except Exception as e:
                print(f"[LauraDaemon] site_scraper error: {e}")

        # product_scraper (a cada 6h)
        PRODUCTS_INTERVAL = 6 * 3600
        if agora - self._last_products > PRODUCTS_INTERVAL:
            try:
                token = self._cfg.default_access_token if self._cfg else None
                shop = self._cfg.default_shop_id if self._cfg else None
                if token and shop and self._client:
                    result_prod = scrape_all_products(self._client, token, shop, force=False)
                    total = result_prod.get("total_found", 0)
                    novos = result_prod.get("total_new", 0)
                    errors = result_prod.get("errors", 0)
                    print(f"[LauraDaemon] Products scraped: {total} total, {novos} novos, {errors} erros")
                    if novos > 0:
                        _post("sistema",
                            f"🛍️ *Produtos da Loja Atualizados*\n"
                            f"{novos} novos produtos adicionados\n"
                            f"{total} produtos no total")
                self._last_products = agora
            except Exception as e:
                print(f"[LauraDaemon] product_scraper error: {e}")

        # daily_tip (a cada 24h)
        if agora - self._last_daily_tip > 24 * 3600:
            try:
                from shopee_agent.article_scraper import get_random_article
                art = get_random_article()
                if art and art.get("title"):
                    aid = art["article_id"]
                    title = art["title"]
                    snippet = art.get("snippet", "")
                    _post("sistema",
                        f"💡 *Dica do Dia: {title}*\n\n"
                        f"{snippet}\n\n"
                        f"Leia mais: /artigo id:{aid}")
                    print(f"[LauraDaemon] Daily tip: {title[:50]}")
                self._last_daily_tip = agora
            except Exception as e:
                print(f"[LauraDaemon] daily_tip error: {e}")

        # Proactive notifications (a cada 2h)
        if agora - self._last_proactive > 2 * 3600:
            try:
                from shopee_agent.proactive_notifier import run_all
                if self._seller_client:
                    alerts = run_all(self._seller_client, low_stock_threshold=5)
                    for a in alerts:
                        if a["type"] == "low_stock":
                            _post("sistema", f"⚠️ *Estoque Baixo*: {a['name']} - apenas {a['stock']} unidades!")
                        elif a["type"] == "bad_rating":
                            _post("avaliacoes", f"⭐ *Avaliacao Ruim*: {a['stars']} estrelas de {a['buyer']}\n\"{a['comment']}\"")
                        elif a["type"] == "cancellation":
                            _post("pedidos", f"❌ *Cancelamento*: Pedido {a['order_sn']} cancelado ({a['reason']})")
                    print(f"[LauraDaemon] Proactive: {len(alerts)} alerts sent")
                self._last_proactive = agora
            except Exception as e:
                print(f"[LauraDaemon] proactive error: {e}")

        # Proactive GOAP goals (a cada 4h)
        if not hasattr(self, "_last_goal_suggest") or agora - self._last_goal_suggest > 4 * 3600:
            try:
                from shopee_agent.proactive_goals import suggest_goals
                # Build metrics from available data
                metrics = {}
                if hasattr(self, "_last_cycle_result") and self._last_cycle_result:
                    cycle = self._last_cycle_result
                    if "orders" in cycle:
                        metrics["orders_pending_ship"] = len([o for o in cycle.get("orders", []) if o.get("order_status") == "READY_TO_SHIP"])
                    if "low_stock_items" in cycle:
                        metrics["stock_risk_level"] = "critical" if len(cycle.get("low_stock_items", [])) > 5 else "low"
                suggestions = suggest_goals(metrics)
                if suggestions:
                    info(f"[LauraDaemon] Goal suggestions: {len(suggestions)}", suggestions=[s.get("goal") for s in suggestions[:3]])
                self._last_goal_suggest = agora
            except Exception as e:
                print(f"[LauraDaemon] goal suggest error: {e}")

        # Pricing automation (a cada 12h)
        if agora - self._last_pricing > 12 * 3600:
            try:
                from shopee_agent.pricing_automation import generate_pricing_report
                if self._seller_client:
                    suggestions = generate_pricing_report(self._seller_client)
                    changes = [s for s in suggestions if s.get("direction") in ("subir", "descer")]
                    if changes:
                        summary = "\n".join(
                            f"- {s['name'][:40]}: R$ {s['current_price']} → R$ {s['suggested_price']} ({s['direction']})"
                            for s in changes[:5]
                        )
                        _post("sistema", f"🏷️ *Sugestoes de Preco ({len(changes)} itens)*\n{summary}")
                    print(f"[LauraDaemon] Pricing: {len(suggestions)} analyzed")
                self._last_pricing = agora
            except Exception as e:
                print(f"[LauraDaemon] pricing error: {e}")

        # Competitor search update (a cada 12h junto com pricing)
        if agora - self._last_search_update > 12 * 3600:
            try:
                from shopee_agent.pricing_automation import update_competitor_data
                if self._seller_client:
                    r = update_competitor_data(self._seller_client)
                    print(f"[LauraDaemon] Search update: {r.get('updated', 0)} products, {r.get('total_competitors', 0)} competitors")
                self._last_search_update = agora
            except Exception as e:
                print(f"[LauraDaemon] search_update error: {e}")

        # Stock prediction (a cada 6h)
        if agora - self._last_stock_prediction > 6 * 3600:
            try:
                from shopee_agent.stock_predictor import predict_restock
                if self._seller_client:
                    recs = predict_restock(self._seller_client)
                    urgent = [r for r in recs if r.get("priority") == "alta"]
                    if urgent:
                        summary = "\n".join(
                            f"- {r['name'][:40]}: {r['current_stock']} em estoque, {r['days_until_empty']} dias restantes"
                            for r in urgent[:5]
                        )
                        _post("sistema", f"📦 *Reabastecimento Urgente ({len(urgent)} itens)*\n{summary}")
                    print(f"[LauraDaemon] Stock prediction: {len(recs)} recommendations")
                self._last_stock_prediction = agora
            except Exception as e:
                print(f"[LauraDaemon] stock_prediction error: {e}")

        # Sentiment analysis (a cada 24h)
        if agora - self._last_sentiment > 24 * 3600:
            try:
                from shopee_agent.sentiment_analyzer import analyze_ratings
                if self._seller_client:
                    result = analyze_ratings(self._seller_client)
                    if result.get("suggestions"):
                        sug = "\n".join(f"- {s}" for s in result["suggestions"])
                        _post("avaliacoes", f"🔍 *Analise de Sentimento*\n{sug}")
                    print(f"[LauraDaemon] Sentiment: {result.get('total_ratings', 0)} ratings analyzed")
                self._last_sentiment = agora
            except Exception as e:
                print(f"[LauraDaemon] sentiment error: {e}")

        # Weekly report (cada segunda-feira)
        week_num = datetime.now(UTC).isocalendar()[1]
        if week_num != self._last_week_num and datetime.now(UTC).weekday() == 0:
            try:
                from shopee_agent.weekly_report import generate_pdf
                if self._seller_client and self._loop:
                    summary = result.get("cycle_result", {})
                    orders_list = self._seller_client.get_orders(limit=50) or []
                    ratings_data = self._seller_client.get_ratings(limit=50) or {}
                    report = generate_pdf(self._seller_client, summary, orders_list, ratings_data)
                    _post("sistema", f"📊 *Relatorio Semanal*\n{report['file']}")
                    print(f"[LauraDaemon] Weekly report: {report['file']}")
                self._last_week_num = week_num
                self._last_weekly_report = agora
            except Exception as e:
                print(f"[LauraDaemon] weekly_report error: {e}")

        # Auto-cleanup de JSONL antigos (a cada 24h)
        if agora - self._last_daily_tip > 24 * 3600:
            try:
                from shopee_agent.cli_commands.cleanup_cmd import handle_cleanup
                class FakeArgs:
                    days = 30
                    max_lines = 5000
                    dry_run = False
                handle_cleanup(FakeArgs())
                info("Auto-cleanup completed")
            except Exception as e:
                log_error("Auto-cleanup error", error=str(e))

        # CDP health check (a cada 6h)
        if agora - self._last_competitive > 6 * 3600:
            cdp_url = os.getenv("CDP_WS_URL", "")
            if cdp_url:
                try:
                    import requests
                    http_url = cdp_url.replace("ws://", "http://").replace("/devtools/browser", "/json/version")
                    resp = requests.get(http_url, timeout=5)
                    if not resp.ok:
                        warning("CDP nao responde", status=resp.status_code)
                except Exception as e:
                    warning("CDP unreachable", error=str(e))

        self._salvar_estado()

        return result

    def _register_shutdown_handlers(self) -> None:
        gs = self._shutdown
        gs.register_handler("daemon_stop", self.stop, priority=100)
        gs.register_handler("save_state", self._salvar_estado, priority=50)
        gs.register_handler("tunnel_stop", self._stop_tunnel, priority=40)
        gs.register_handler(
            "event_bus",
            lambda: self._event_bus.stop() if getattr(self, "_event_bus", None) else None,
            priority=30,
        )
        gs.register_handler(
            "webhook_server",
            lambda: self._webhook_server.stop() if getattr(self, "_webhook_server", None) else None,
            priority=20,
        )
        gs.register_handler(
            "workers",
            lambda: (parar_todos_workers() or None),
            priority=10,
        )
        gs.register_handler(
            "auto_login",
            lambda: setattr(self._auto_login_thread, "_stop", True)
            if getattr(self, "_auto_login_thread", None)
            else None,
            priority=5,
        )

    def run_forever(self) -> None:
        if not self._setup():
            print("[LauraDaemon] Setup failed - exiting")
            return

        self._register_shutdown_handlers()
        self._shutdown.setup_signal_handlers()

        self._running = True
        if ceo_mode_enabled():
            print("[LauraDaemon] 🚀 CEO MODE ATIVO — acoes executadas sem aprovacao humana")
        print(f"[LauraDaemon] Started (interval={CYCLE_INTERVAL}s)")
        info("Daemon started", interval=CYCLE_INTERVAL)

        # Auto-start Telegram bot if token is configured
        try:
            from shopee_agent.telegram_bot import start_bot
            if os.getenv("TELEGRAM_BOT_TOKEN") and not _telegram_bot_already_running():
                start_bot(daemon_mode=True)
                info("Telegram bot auto-started with daemon")
        except Exception as exc:
            warning("Failed to auto-start Telegram bot", error=str(exc))

        while self._running and not self._shutdown.is_shutting_down():
            try:
                self._cycle()
            except Exception as e:
                log_error("Cycle error", error=str(e))

            if self._shutdown.is_shutting_down():
                break

            agora = time.time()
            if agora - self._last_health_check > 1800:
                try:
                    self._health_check()
                except Exception as e:
                    print(f"[LauraDaemon] Health check error: {e}")

            for _ in range(CYCLE_INTERVAL):
                if not self._running or self._shutdown.is_shutting_down():
                    break
                time.sleep(1)

        self._shutdown.shutdown()

    def stop(self) -> None:
        self._running = False
        self._stop_tunnel()
        info("Daemon stopping")
        if getattr(self, "_event_bus", None):
            try:
                self._event_bus.stop()
                print("[LauraDaemon] Event bus stopped")
            except Exception as e:
                print(f"[LauraDaemon] Event bus stop error: {e}")
        if getattr(self, "_webhook_server", None):
            try:
                self._webhook_server.stop()
                print("[LauraDaemon] Webhook server stopped")
            except Exception as e:
                print(f"[LauraDaemon] Webhook server stop error: {e}")
        try:
            parar_todos_workers()
        except Exception:
            pass
        print("[LauraDaemon] Stopped")


if __name__ == "__main__":
    daemon = LauraDaemon()
    try:
        daemon.run_forever()
    except KeyboardInterrupt:
        print("[LauraDaemon] KeyboardInterrupt received")
        daemon.stop()
    except SystemExit:
        daemon.stop()
    finally:
        if hasattr(daemon, "_shutdown"):
            daemon._shutdown.restore_signal_handlers()
