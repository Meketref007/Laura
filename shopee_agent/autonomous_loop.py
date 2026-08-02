from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from shopee_agent.ceo_mode import ceo_mode_enabled
from shopee_agent.decision_engine import DecisionEngine, DecisionPriority, DecisionStatus, create_default_rules
from shopee_agent.decision_integration import DecisionExecutor, DecisionIntegrator

from .client import ShopeeClient

# --- Conditional imports for enhanced modules ---
try:
    from shopee_agent.analytics_trending import AdvancedAnalytics  # if needed
except ImportError:
    AdvancedAnalytics = None

try:
    from shopee_agent.predictive_analytics import PredictiveAnalytics
except ImportError:
    PredictiveAnalytics = None

try:
    from shopee_agent.competitive_intelligence import CompetitiveIntelligence
except ImportError:
    CompetitiveIntelligence = None

try:
    from shopee_agent.strategic_planner import StrategicPlanner
except ImportError:
    StrategicPlanner = None

try:
    from shopee_agent.learning_system import LearningSystem
except ImportError:
    LearningSystem = None

try:
    from shopee_agent.flash_sale_recommender import FlashSaleRecommender
except ImportError:
    FlashSaleRecommender = None
# ---

_CYCLE_INTERVAL_LEARNING = 10  # every N cycles run learning evaluation


@dataclass
class AutonomousLoop:
    client: ShopeeClient
    access_token: str | None
    shop_id: int | None
    reports_dir: Path
    telegram_token: str | None = None
    telegram_chat_id: str | None = None
    chat_auto: Any | None = None  # ChatAutomation instance (avoid circular import)
    event_bus: Any | None = None
    external_engine: Any | None = None
    external_integrator: Any | None = None
    enable_auto_skills: bool | None = None
    ceo_mode: bool | None = None
    _cycle_counter: int = field(default=0, init=False, repr=False)
    _sent_approvals: dict = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.enable_auto_skills is None:
            raw = os.getenv("LAURA_ENABLE_AUTO_SKILLS", "1")
            self.enable_auto_skills = str(raw).strip().lower() not in ("0", "false", "no", "off")
        if self.ceo_mode is None:
            self.ceo_mode = ceo_mode_enabled()
        self._predictive_analytics = (
            PredictiveAnalytics(reports_dir=str(self.reports_dir))
            if PredictiveAnalytics is not None
            else None
        )
        self._competitive_intelligence = (
            CompetitiveIntelligence(path=str(self.reports_dir / "competitive_offers.jsonl"))
            if CompetitiveIntelligence is not None
            else None
        )
        self._strategic_planner = (
            StrategicPlanner()
            if StrategicPlanner is not None
            else None
        )
        self._learning_system = (
            LearningSystem(outcomes_path=str(self.reports_dir / "decision_outcomes.jsonl"))
            if LearningSystem is not None
            else None
        )
        self._flash_sale_recommender = (
            FlashSaleRecommender(
                client=self.client,
                access_token=str(self.access_token or ""),
                shop_id=int(str(self.shop_id or "0")),
                reports_dir=self.reports_dir,
            )
            if FlashSaleRecommender is not None
            else None
        )
        self._last_flash_sale_scan: datetime | None = None

    def _send_telegram(self, text: str) -> bool:
        token = self.telegram_token or os.getenv("LAURA_ALERT_TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = self.telegram_chat_id or os.getenv("LAURA_ALERT_TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat_id:
            return False
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={
                    "chat_id": chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            return True
        except Exception:
            return False

    def _append_log(self, payload: dict[str, Any]) -> None:
        path = self.reports_dir / "laura_autonomous_log.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _enrich_order(self, order: dict[str, Any]) -> dict[str, Any]:
        """
        Enriquece dados do pedido com detalhes da API.
        Adiciona: product_name, product_price, buyer_id, etc.
        """
        if not self.access_token or not self.shop_id:
            return order

        order_sn = str(order.get("order_sn") or "").strip()
        if not order_sn:
            return order

        try:
            resp = self.client.get_order_detail(
                access_token=self.access_token,
                shop_id=self.shop_id,
                order_sn=order_sn,
            )

            detail_body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
            orders_detail = detail_body.get("order_list", []) if isinstance(detail_body, dict) else []

            if orders_detail and isinstance(orders_detail[0], dict):
                detail = orders_detail[0]
                order_enriched = {**order}
                order_enriched["buyer_id"] = detail.get("buyer_id")
                order_enriched["buyer_username"] = detail.get("buyer_username")
                order_enriched["total_amount"] = detail.get("total_amount")

                items = detail.get("item_list", []) if isinstance(detail.get("item_list"), list) else []
                if items and isinstance(items[0], dict):
                    order_enriched["product_name"] = items[0].get("item_name")
                    order_enriched["product_quantity"] = items[0].get("model_quantity_purchased")

                return order_enriched
        except Exception:
            pass

        return order

    def _collect_state(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        time_to = int(now.timestamp())
        time_from = int((now - timedelta(days=1)).timestamp())

        orders: list[dict[str, Any]] = []
        try:
            resp = self.client.get_order_list(
                access_token=self.access_token,
                shop_id=self.shop_id,
                time_from=time_from,
                time_to=time_to,
                page_size=100,
                order_status="READY_TO_SHIP",
                time_range_field="update_time",
            )
            body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
            orders = body.get("order_list", []) if isinstance(body, dict) else []

            orders = [self._enrich_order(order) for order in orders if isinstance(order, dict)]
        except Exception:
            orders = []

        items_low_stock: list[dict[str, Any]] = []
        try:
            resp2 = self.client.get_item_list(
                access_token=self.access_token,
                shop_id=self.shop_id,
                offset=0,
                page_size=200,
            )
            body2 = resp2.data.get("response", {}) if isinstance(resp2.data, dict) else {}
            items = body2.get("item", []) if isinstance(body2, dict) else []
            for it in items:
                try:
                    stock = int(it.get("stock", 0) or 0)
                except Exception:
                    stock = 0
                if stock <= 3:
                    items_low_stock.append({"item_id": it.get("item_id"), "stock": stock})
        except Exception:
            items_low_stock = []

        return {"collected_at": now.isoformat(), "orders": orders, "low_stock_items": items_low_stock}

    def _analyze(self, state: dict[str, Any]) -> dict[str, Any]:
        actions: dict[str, list[dict[str, Any]]] = {"auto": [], "approval": []}
        orders = state.get("orders", []) if isinstance(state.get("orders"), list) else []
        now = datetime.now(UTC)
        for order in orders:
            if not isinstance(order, dict):
                continue
            order_sn = str(order.get("order_sn") or order.get("ordersn") or "").strip()
            status = str(order.get("order_status") or "").upper()
            created_ts = int(order.get("create_time") or order.get("ctime") or 0)
            created = datetime.fromtimestamp(created_ts, UTC) if created_ts else now
            age = (now - created).total_seconds()
            if status == "PAID" or status == "READY_TO_SHIP":
                if age >= 30 * 60:
                    actions["approval"].append({"type": "ship_order", "order_sn": order_sn, "reason": "PAID >30m"})

        low = state.get("low_stock_items", []) if isinstance(state.get("low_stock_items"), list) else []
        if low:
            actions["auto"].append({"type": "replenish_stock", "items": low[:10]})

        # LLM strategic analysis (non-blocking)
        try:
            import os as _os

            import requests as _req
            _ollama_host = _os.getenv("LAURA_OLLAMA_HOST", "http://127.0.0.1:11434")
            _llm_model = _os.getenv("LAURA_LLM_MODEL", "llama3.2:3b")
            _order_count = len(orders)
            _low_count = len(low)
            _prompt = (
                "You are Laura, an AI store analyst for Shopee. "
                "Analyze the current store state and respond with short JSON:\n"
                f'{{"strategic_priority":"high/medium/low","focus_area":"shipping/stock/pricing/marketing","recommendation":"one sentence","confidence":0.0-1.0}}\n'
                f"Context: {_order_count} orders pending, {_low_count} low-stock items, vacation_mode={state.get('vacation_mode', '?')}"
            )
            try:
                _resp = _req.post(f"{_ollama_host}/api/generate", json={"model": _llm_model, "prompt": _prompt, "stream": False}, timeout=15)
                if _resp.status_code == 200:
                    _raw = _resp.json().get("response", "")
                    _parsed = json.loads(_raw)
                    actions["llm_analysis"] = _parsed
            except Exception:
                pass
        except Exception:
            pass

        return actions

    def _process_chat_messages(self) -> list[dict[str, Any]]:
        if not self.chat_auto:
            return []

        return []

    def _notify_workers(self, state: dict[str, Any]) -> None:
        from .vilu_workers import (
            estoque_baixo,
            pedido_novo,
            pedido_status,
            produto_sem_estoque,
        )

        orders = state.get("orders", []) if isinstance(state.get("orders"), list) else []
        for order in orders:
            if not isinstance(order, dict):
                continue
            order_sn = str(order.get("order_sn") or "")
            if not order_sn:
                continue
            prod_name = order.get("product_name") or "Produto"
            try:
                amount = float(order.get("total_amount", 0) or 0) / 100000
            except Exception:
                amount = 0.0
            qty = int(order.get("product_quantity", 1) or 1)
            buyer = order.get("buyer_username") or ""
            pedido_novo(order_sn, prod_name, amount, qty, buyer)

            status = str(order.get("order_status") or "")
            if status == "READY_TO_SHIP":
                pedido_status(order_sn, status, "Pronto para envio")

        low_stock = state.get("low_stock_items", []) if isinstance(state.get("low_stock_items"), list) else []
        for item in low_stock:
            if not isinstance(item, dict):
                continue
            item_id = item.get("item_id", "")
            stock = int(item.get("stock", 0))
            if stock <= 0:
                produto_sem_estoque(str(item_id))
            else:
                estoque_baixo(str(item_id), stock)

    def _skill_orchestrator_state(self, state: dict[str, Any]) -> dict[str, Any]:
        low_stock = state.get("low_stock_items", [])
        return {
            "stock_checked": len(low_stock) == 0,
            "margin_protected": False,
            "orders_pending_ship": len(state.get("orders", [])) == 0,
            "support_handled": True,
        }

    def _run_learning_cycle(self) -> dict[str, Any]:
        """Evaluate learning system every N cycles."""
        if self._learning_system is None:
            return {"status": "skipped", "reason": "LearningSystem not available"}
        try:
            report = self._learning_system.evaluate(window_days=30, persist_note=True)
            self._append_log({
                "event": "learning_cycle",
                "timestamp": datetime.now(UTC).isoformat(),
                "success_rate": report.success_rate,
                "failure_rate": report.failure_rate,
                "signals": [s.name for s in report.signals],
                "actionable_insights": report.actionable_insights,
            })
            return {"status": "ok", "report": report}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def _run_flash_sale_scan(self) -> dict[str, Any]:
        """Run flash sale recommender weekly."""
        if self._flash_sale_recommender is None:
            return {"status": "skipped", "reason": "FlashSaleRecommender not available"}
        try:
            recommendations = self._flash_sale_recommender.scan_catalog()
            if recommendations:
                text = "\n".join(
                    f"🏷️ Flash sale sugerida: {r.get('item_name', 'Item')} "
                    f"({r.get('discount_pct', 15)}% off)"
                    for r in recommendations[:5]
                )
                self._send_telegram(text)
            self._last_flash_sale_scan = datetime.now(UTC)
            self._append_log({
                "event": "flash_sale_scan",
                "timestamp": self._last_flash_sale_scan.isoformat(),
                "recommendations_count": len(recommendations),
            })
            return {"status": "ok", "count": len(recommendations)}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def run_cycle(self) -> dict[str, Any]:
        state = self._collect_state()
        self._notify_workers(state)

        # Emitir DecisionSignalEvent a partir do estado coletado
        bus = self.event_bus
        if bus is not None:
            from shopee_agent.event_bus import DecisionSignalEvent
            for anomaly in state.get("anomalies", []):
                bus.submit(DecisionSignalEvent(
                    event_type="decision.signal",
                    source="metrics",
                    signal=anomaly,
                    context=state,
                ))
            if state.get("low_stock_items"):
                bus.submit(DecisionSignalEvent(
                    event_type="decision.signal",
                    source="metrics",
                    signal={"type": "risk", "metric": "inventory", "items": len(state["low_stock_items"])},
                    context=state,
                ))

        engine = self.external_engine if self.external_engine is not None else DecisionEngine(
            store_id=str(self.shop_id or "default"), rules=create_default_rules()
        )

        integrator = self.external_integrator if self.external_integrator is not None else DecisionIntegrator(
                engine=engine,
                store_id=str(self.shop_id or "default"),
                metrics_dir=str(self.reports_dir),
                predictive_analytics=self._predictive_analytics,
                competitive_intelligence=self._competitive_intelligence,
                strategic_planner=self._strategic_planner,
            )

        cycle_result = integrator.process_cycle()

        decisions_list = list(engine.pending_decisions.values())

        # Modo CEO: auto-aprova decisoes pendentes (sem aprovacao humana)
        if self.ceo_mode:
            auto_approved = 0
            for d in decisions_list:
                try:
                    if d.status == DecisionStatus.PENDING:
                        d.status = DecisionStatus.APPROVED
                        auto_approved += 1
                except Exception:
                    continue
            if auto_approved:
                try:
                    self._send_telegram(f"🤖 *CEO Mode* — {auto_approved} decisao(es) aprovada(s) automaticamente.")
                except Exception:
                    pass
            try:
                engine._save_pending()
            except Exception:
                pass

        # Notificar apenas decisoes PENDING de alta prioridade (1x por titulo)
        for d in decisions_list:
            try:
                if self.ceo_mode:
                    continue
                if d.status == DecisionStatus.PENDING and d.priority in (DecisionPriority.HIGH, DecisionPriority.CRITICAL):
                    title_key = f"pending_approval_{d.title}"
                    if title_key not in self._sent_approvals:
                        text = f"⚠️ Aprovação necessária: {d.title} (id={d.decision_id})"
                        self._send_telegram(text)
                        self._sent_approvals[title_key] = time.time()
            except Exception:
                continue

        executor = DecisionExecutor(store_id=str(self.shop_id or "default"), engine=engine, client=self.client)
        executed = []
        for d in decisions_list:
            try:
                if d.status.name != "APPROVED":
                    continue
                md = d.metadata if isinstance(d.metadata, dict) else {}
                if (md.get("skill") or md.get("skill_name")) and not self.enable_auto_skills:
                    continue
                if not self.ceo_mode and d.priority != DecisionPriority.LOW:
                    continue
                success = executor.execute(d)
                if success:
                    integrator.mark_decision_executed(d.decision_id)
                    executed.append(d.decision_id)
            except Exception:
                continue

        if self.enable_auto_skills:
            # Execute skill-tagged decisions (existing logic)
            for d in decisions_list:
                try:
                    if d.decision_id in executed:
                        continue
                    if d.status.name == "APPROVED":
                        md = d.metadata if isinstance(d.metadata, dict) else {}
                        if md.get("skill") or md.get("skill_name"):
                            if not self.ceo_mode and d.priority in (DecisionPriority.CRITICAL, DecisionPriority.HIGH):
                                continue
                            success = executor.execute(d)
                            if success:
                                integrator.mark_decision_executed(d.decision_id)
                                executed.append(d.decision_id)
                except Exception:
                    continue

            # Also run SkillOrchestrator for state goals
            try:
                from shopee_agent.skills.loader import discover_and_register
                from shopee_agent.skills.orchestrator import SkillOrchestrator

                discover_and_register()
                orch = SkillOrchestrator()
                current = self._skill_orchestrator_state(state)
                goal = {"stock_checked": True, "margin_protected": True, "orders_pending_ship": False, "support_handled": True}
                eval_result = orch.evaluate_state(current, goal, max_depth=4)
                if eval_result["status"] == "executed":
                    for r in eval_result["results"]:
                        if r.get("ok"):
                            from shopee_agent.decision_engine import DecisionType
                            dummy = __import__("shopee_agent.decision_engine", fromlist=["Decision"]).Decision(
                                decision_id=f"auto_skill_{r['skill']}_{int(time.time())}",
                                title=f"AutoSkill: {r['skill']}",
                                decision_type=DecisionType.ALERTS,
                                recommended_action=r.get("result", ""),
                                priority=DecisionPriority.LOW,
                                status=DecisionStatus.APPROVED,
                                metadata={"skill": r["skill"], "source": "auto_orchestrator"},
                            )
                            success = executor.execute(dummy)
                            if success:
                                executed.append(dummy.decision_id)
            except Exception:
                pass

        # Emitir OutcomeRecordedEvent para decisoes executadas
        if bus is not None:
            from shopee_agent.event_bus import OutcomeRecordedEvent
            for did in executed:
                d_obj = engine.pending_decisions.get(did)
                if d_obj:
                    bus.submit(OutcomeRecordedEvent(
                        event_type="outcome.recorded",
                        decision_id=did,
                        rule_id=getattr(d_obj, "rule_id", ""),
                        outcome_type="success",
                        impact_realized=getattr(d_obj, "impact_score", 0.0),
                        metadata={"source": "autonomous_loop"},
                    ))

        approvals = self._analyze(state).get("approval", []) if isinstance(self._analyze(state), dict) else []
        orders_by_sn = {str(o.get("order_sn", "")): o for o in state.get("orders", []) if isinstance(o, dict)}
        for a in approvals:
            order_sn = a.get("order_sn")
            if not order_sn:
                continue
            order = orders_by_sn.get(order_sn, {})
            if self.ceo_mode and getattr(self.client, "ship_order", None) is not None:
                # CEO mode: envia pedido pronto automaticamente
                try:
                    self.client.ship_order(
                        access_token=self.access_token,
                        shop_id=self.shop_id,
                        order_sn=order_sn,
                    )
                    try:
                        self._send_telegram(f"📦 *CEO Mode* — pedido {order_sn} enviado automaticamente.")
                    except Exception:
                        pass
                except Exception as exc:
                    try:
                        self._send_telegram(f"⚠️ *CEO Mode* — falha ao enviar {order_sn}: {exc}")
                    except Exception:
                        pass
                continue
            msg_lines = [
                "📦 <b>Pedido pronto para envio</b>",
                "",
                f"<b>Número do pedido:</b> <code>{order_sn}</code>",
            ]
            if order.get("product_name"):
                msg_lines.append(f"<b>Produto:</b> {order['product_name']}")
            if order.get("product_quantity"):
                msg_lines.append(f"<b>Quantidade:</b> {order['product_quantity']}")
            if order.get("total_amount"):
                try:
                    price = float(order["total_amount"]) / 100000
                    msg_lines.append(f"<b>Valor:</b> R$ {price:.2f}")
                except Exception:
                    pass
            buyer = order.get("buyer_username") or order.get("buyer_id", "")
            if buyer:
                msg_lines.append(f"<b>Cliente:</b> {buyer}")
            msg_lines.extend(["", f"Use /enviar_{order_sn} para aprovar o envio."])
            text = "\n".join(msg_lines)
            try:
                self._send_telegram(text)
            except Exception:
                pass

        # --- Periodic tasks ---
        self._cycle_counter += 1

        if self._cycle_counter % _CYCLE_INTERVAL_LEARNING == 0:
            learning_result = self._run_learning_cycle()
        else:
            learning_result = {"status": "skipped"}

        now = datetime.now(UTC)
        if self._flash_sale_recommender is not None:
            if self._last_flash_sale_scan is None or (now - self._last_flash_sale_scan) > timedelta(days=7):
                flash_sale_result = self._run_flash_sale_scan()
            else:
                flash_sale_result = {"status": "skipped"}
        else:
            flash_sale_result = {"status": "skipped"}
        # ---

        ts = now.isoformat()
        log = {
            "timestamp": ts,
            "state_summary": {
                "orders_seen": len(state.get("orders", [])),
                "low_stock_count": len(state.get("low_stock_items", [])),
            },
            "decision_cycle_summary": cycle_result,
            "pending_decisions_count": len(decisions_list),
            "executed_decisions": executed,
            "learning_cycle": learning_result,
            "flash_sale_scan": flash_sale_result,
        }
        self._append_log(log)

        # Emitir eventos para o event bus
        bus = self.event_bus
        if bus is not None:
            from shopee_agent.event_bus import CycleCompleteEvent, MetricUpdateEvent
            bus.submit(CycleCompleteEvent(
                event_type="cycle.complete",
                cycle_number=self._cycle_counter,
                summary={"orders_seen": len(state.get("orders", [])), "executed_decisions": executed},
            ))
            bus.submit(MetricUpdateEvent(
                event_type="metric.update",
                metrics={"cycle_number": self._cycle_counter, "executed_decisions": len(executed)},
            ))

        return {"timestamp": ts, "cycle_result": cycle_result, "executed": executed}
