"""
auto_responses.py - Automatic response engine for ratings and events
Generates contextual replies to buyer ratings, messages, and issues.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from .client import ShopeeClient
from .config import load_config
from .logger import debug, info, warning
from .logger import error as log_error
from .telegram_narrator import narrador


class AutoResponseEngine:
    """Manages automatic responses to ratings and customer interactions."""

    def __init__(self, cache_dir: str = "reports"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.response_history_file = self.cache_dir / "auto_responses_history.jsonl"
        self.cooldown_seconds = 3600  # 1 hour between responses to same buyer

    def _get_cooldown_key(self, buyer_id: str, response_type: str) -> str:
        """Generate cooldown key for buyer+type combo"""
        return hashlib.md5(f"{buyer_id}:{response_type}".encode()).hexdigest()

    def _is_in_cooldown(self, cooldown_key: str) -> bool:
        """Check if response is in cooldown period"""
        try:
            hist = []
            if self.response_history_file.exists():
                for line in self.response_history_file.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        try:
                            hist.append(json.loads(line))
                        except Exception:
                            pass

            if hist:
                last_entry = hist[-1]
                if last_entry.get("cooldown_key") == cooldown_key:
                    last_ts = datetime.fromisoformat(last_entry.get("timestamp", "").replace("Z", "+00:00"))
                    now = datetime.now(UTC)
                    elapsed = (now - last_ts).total_seconds()
                    return elapsed < self.cooldown_seconds
        except Exception:
            pass

        return False

    def _log_response(self, response_data: dict[str, Any]) -> None:
        """Log response to history"""
        try:
            response_data["timestamp"] = datetime.now(UTC).isoformat()
            with self.response_history_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(response_data, ensure_ascii=False) + "\n")
        except Exception as exc:
            warning(f"Failed to log auto-response: {exc}")

    def _fallback_contextual_response(self, *, rating: int, comment: str, order_id: str) -> str:
        comment_clean = (comment or "").strip()
        if rating >= 4:
            if comment_clean:
                return (
                    f"Obrigado pela sua avaliação! Ficamos felizes com seu comentário sobre '{comment_clean[:60]}'. "
                    "Se precisar de algo, estamos à disposição."
                )
            return "Obrigado pela avaliação positiva! Seu feedback é muito importante para nós. Conte com a gente sempre."
        if rating == 3:
            if comment_clean:
                return (
                    f"Obrigado pelo seu feedback sobre '{comment_clean[:60]}'. "
                    "Vamos usar seu comentário para melhorar sua próxima experiência."
                )
            return "Obrigado pela avaliação. Estamos melhorando continuamente para te atender cada vez melhor."
        if comment_clean:
            return (
                f"Sentimos muito pela experiência e levamos a sério seu comentário: '{comment_clean[:70]}'. "
                "Queremos resolver isso com prioridade; por favor nos chame no chat para ajudar agora."
            )
        return "Sentimos muito pela experiência. Queremos resolver seu caso com prioridade; nos chame no chat para te ajudar agora."

    def _generate_contextual_response_local(self, *, rating: int, comment: str, order_id: str) -> str:
        """Generate a non-template, contextual response using local Ollama (cost zero)."""
        model = os.getenv("LAURA_LLM_MODEL", "tinyllama")
        timeout_seconds = int(os.getenv("LAURA_AUTO_RESPONSE_LLM_TIMEOUT_SECONDS", "5"))
        prompt = (
            "Você é atendente de loja Shopee. Escreva UMA resposta curta e humana ao comprador, "
            "em português-BR, sem emoji excessivo, sem promessas impossíveis, com tom cordial. "
            "Não use frases genéricas repetitivas. "
            f"Contexto: pedido={order_id}; nota={rating}; comentário='{(comment or '').strip()}'. "
            "Responda apenas com o texto final para enviar ao cliente (máx 280 caracteres)."
        )
        try:
            resp = requests.post(
                "http://127.0.0.1:11434/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0.7,
                    "num_predict": 120,
                },
                timeout=(5, timeout_seconds),
            )
            resp.raise_for_status()
            text = str(resp.json().get("response", "")).strip()
            if text:
                text = text.replace("\n", " ").strip()
                if len(text) > 280:
                    text = text[:277].rstrip() + "..."
                return text
        except Exception as exc:
            debug("Local LLM response generation failed", error=str(exc)[:120], model=model)
        return self._fallback_contextual_response(rating=rating, comment=comment, order_id=order_id)

    def _try_send_chat_response(self, *, buyer_id: str, shop_id: int | None, text: str) -> tuple[str, str | None]:
        """Try sending the generated response through Shopee Chat API."""
        auto_send = os.getenv("LAURA_AUTO_RESPONSE_SEND_CHAT", "1").strip().lower() in {"1", "true", "yes", "on"}
        if not auto_send:
            return "generated_only", "chat_send_disabled"
        if not buyer_id or buyer_id == "?":
            return "generated_only", "missing_buyer_id"

        try:
            cfg = load_config()
            effective_shop_id = int(shop_id) if shop_id else cfg.default_shop_id
            effective_access_token = cfg.default_access_token
            if effective_shop_id is None or not effective_access_token:
                return "generated_only", "missing_shop_or_token"

            client = ShopeeClient(cfg)
            resp = client.send_chat_message(
                access_token=effective_access_token,
                shop_id=effective_shop_id,
                buyer_id=buyer_id,
                message=text,
            )
            return "sent", None if isinstance(resp.data, dict) else None
        except Exception as exc:
            warning("Failed to send chat response", buyer_id=buyer_id, error=str(exc)[:160])
            return "generated_only", str(exc)

    def respond_to_rating(self, *, order_id: str, buyer_id: str, rating: int, comment: str = "", shop_id: int | None = None) -> dict[str, Any]:
        """
        Generate and log automatic response to a buyer rating.
        
        Returns dict with response text and status.
        """
        cooldown_key = self._get_cooldown_key(buyer_id, "rating_response")

        if self._is_in_cooldown(cooldown_key):
            return {
                "status": "cooldown",
                "buyer_id": buyer_id,
                "order_id": order_id,
                "reason": f"Recent response already sent; cooldown {self.cooldown_seconds}s"
            }

        # Generate contextual response (local LLM + fallback)
        response_text = self._generate_contextual_response_local(
            rating=rating,
            comment=comment,
            order_id=order_id,
        )
        if rating >= 4:
            response_type = "positive_rating_contextual"
        elif rating == 3:
            response_type = "neutral_rating_contextual"
        else:
            response_type = "negative_rating_contextual"

        send_status, send_error = self._try_send_chat_response(
            buyer_id=buyer_id,
            shop_id=shop_id,
            text=response_text,
        )
        info("Auto-response generated for rating",
             buyer_id=buyer_id,
             order_id=order_id,
             rating=rating,
             response_type=response_type
        )

        # Log the response
        response_record = {
            "order_id": order_id,
            "buyer_id": buyer_id,
            "shop_id": shop_id,
            "rating": rating,
            "comment_preview": comment[:100] if comment else "",
            "response_type": response_type,
            "response_text": response_text,
            "cooldown_key": cooldown_key,
            "status": send_status,
            "send_error": send_error,
        }
        self._log_response(response_record)

        # Notify via Telegram
        msg = f"Auto-resposta {send_status} para avaliação {rating}⭐ (order: {order_id})"
        narrador.webhook_evento("auto_response.rating", msg)

        return {
            "status": send_status,
            "order_id": order_id,
            "buyer_id": buyer_id,
            "rating": rating,
            "response_type": response_type,
            "response_text": response_text,
            "send_error": send_error,
        }

    def notify_seller_action_required(self, *, order_id: str, buyer_id: str, action_type: str, expires_at: str | None = None) -> dict[str, Any]:
        """
        Notify about seller action required (e.g., rating response needed).
        """
        msg = f"⚠️ Ação requerida: {action_type} para order `{order_id}`"
        if expires_at:
            msg += f" (vence em {expires_at})"

        narrador.alerta(msg)
        info("Seller action notification sent",
             order_id=order_id,
             buyer_id=buyer_id,
             action_type=action_type
        )

        return {
            "status": "notified",
            "order_id": order_id,
            "buyer_id": buyer_id,
            "action_type": action_type,
            "timestamp": datetime.now(UTC).isoformat()
        }

    def get_pending_actions(self, days: int = 7) -> list[dict[str, Any]]:
        """Get pending seller actions from recent events"""
        pending = []

        try:
            history_path = self.cache_dir / "auto_responses_history.jsonl"
            if not history_path.exists():
                return []

            cutoff = datetime.now(UTC) - timedelta(days=days)

            for line in history_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry.get("timestamp", "").replace("Z", "+00:00"))
                    if ts >= cutoff and entry.get("status") != "resolved":
                        pending.append(entry)
                except Exception:
                    pass
        except Exception as exc:
            warning(f"Failed to fetch pending actions: {exc}")

        return pending

    def _get_responded_rating_ids(self) -> set[str]:
        """Load set of rating_ids we've already responded to"""
        try:
            responded_path = self.cache_dir / "laura_responded_ratings.state"
            if not responded_path.exists():
                return set()
            data = json.loads(responded_path.read_text(encoding="utf-8"))
            return set(data.get("responded_rating_ids", []))
        except Exception as exc:
            debug(f"Failed to load responded ratings state: {exc}")
            return set()

    def _save_responded_rating_ids(self, rating_ids: set[str]) -> None:
        """Persist set of rating_ids we've responded to"""
        try:
            responded_path = self.cache_dir / "laura_responded_ratings.state"
            data = {
                "responded_rating_ids": sorted(rating_ids),
                "updated_at": datetime.now(UTC).isoformat()
            }
            responded_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            warning(f"Failed to save responded ratings state: {exc}")

    def process_ratings_backfill(
        self,
        client: Any,
        access_token: str,
        shop_id: int,
        lookback_days: int = 60,
        batch_size: int = 50,
    ) -> dict[str, Any]:
        """
        Process all pending unanswered ratings from recent orders.
        
        Args:
            client: ShopeeClient instance
            access_token: Shopee API access token
            shop_id: Shopee shop ID
            lookback_days: How many days back to look for orders with ratings
            batch_size: Max orders per API call
        
        Returns:
            Dict with stats (total_orders, total_ratings, responses_sent, errors)
        """
        stats = {
            "total_orders": 0,
            "total_ratings": 0,
            "responses_sent": 0,
            "responses_skipped": 0,
            "errors": [],
        }

        try:
            # Calculate time window
            now = int(time.time())
            lookback_seconds = lookback_days * 86400
            time_from = now - lookback_seconds

            info(f"Starting ratings backfill for {lookback_days} days",
                 shop_id=shop_id,
                 time_from=time_from)

            # Get responded ratings we've already processed
            responded_ids = self._get_responded_rating_ids()

            # Fetch orders in batches
            cursor = ""
            while True:
                try:
                    resp = client.get_order_list(
                        access_token=access_token,
                        shop_id=shop_id,
                        time_from=time_from,
                        time_to=now,
                        time_range_field="create_time",
                        page_size=batch_size,
                        cursor=cursor,
                    )

                    if resp.status_code not in (200, 0):
                        error_msg = f"API error: {resp.status_code}"
                        stats["errors"].append(error_msg)
                        warning(error_msg)
                        break

                    orders = resp.data.get("orders", [])
                    if not orders:
                        break

                    stats["total_orders"] += len(orders)

                    # Process each order for ratings
                    for order in orders:
                        order_sn = order.get("order_sn")
                        if not order_sn:
                            continue

                        try:
                            # Fetch order detail to get rating info
                            detail_resp = client.get_order_detail(
                                access_token=access_token,
                                shop_id=shop_id,
                                order_sn=order_sn,
                            )

                            if detail_resp.status_code not in (200, 0):
                                continue

                            order_detail = detail_resp.data.get("order", {})

                            # Check for buyer rating
                            rating_data = order_detail.get("buyer_rating")
                            if not rating_data:
                                continue

                            stats["total_ratings"] += 1

                            rating_id = rating_data.get("rating_id", f"order_{order_sn}")
                            if rating_id in responded_ids:
                                stats["responses_skipped"] += 1
                                continue

                            # Extract rating details
                            rating = int(rating_data.get("rating_star", 0))
                            comment = rating_data.get("comment", "")
                            buyer_id = order_detail.get("buyer_id")
                            order_id = order_detail.get("order_id") or order_sn

                            if not buyer_id or rating == 0:
                                continue

                            # Generate and send response
                            response_result = self.respond_to_rating(
                                order_id=str(order_id),
                                buyer_id=str(buyer_id),
                                rating=rating,
                                comment=comment,
                                shop_id=shop_id,
                            )

                            if response_result.get("status") in ("sent", "generated_only"):
                                responded_ids.add(rating_id)
                                stats["responses_sent"] += 1
                                info(f"Backfill: response to rating {rating_id}",
                                     order_id=order_id,
                                     buyer_id=buyer_id,
                                     rating=rating)

                        except Exception as exc:
                            error_msg = f"Order {order_sn}: {str(exc)[:100]}"
                            stats["errors"].append(error_msg)
                            debug(error_msg)

                    # Check for next page
                    cursor = resp.data.get("next_cursor")
                    if not cursor:
                        break

                    # Small delay between batches
                    time.sleep(0.5)

                except Exception as exc:
                    error_msg = f"Batch processing failed: {str(exc)[:120]}"
                    stats["errors"].append(error_msg)
                    log_error(error_msg)
                    break

            # Save updated state
            self._save_responded_rating_ids(responded_ids)

            # Notify
            msg = (
                f"✅ Backfill concluído: {stats['responses_sent']} respostas enviadas, "
                f"{stats['total_ratings']} avaliações processadas, {stats['responses_skipped']} puladas"
            )
            narrador.webhook_evento("ratings_backfill", msg)

            info("Ratings backfill complete", stats=stats)

        except Exception as exc:
            error_msg = f"Ratings backfill failed: {str(exc)[:150]}"
            stats["errors"].append(error_msg)
            log_error(error_msg)
            narrador.alerta(f"❌ Erro backfill avaliações: {error_msg[:80]}")

        return stats


# Global instance
_engine: AutoResponseEngine | None = None


def get_auto_response_engine() -> AutoResponseEngine:
    """Get or create global auto-response engine"""
    global _engine
    if _engine is None:
        _engine = AutoResponseEngine()
    return _engine


def respond_to_rating(*, order_id: str, buyer_id: str, rating: int, comment: str = "", shop_id: int | None = None) -> dict[str, Any]:
    """Convenience function to respond to rating"""
    engine = get_auto_response_engine()
    return engine.respond_to_rating(order_id=order_id, buyer_id=buyer_id, rating=rating, comment=comment, shop_id=shop_id)


def notify_seller_action_required(*, order_id: str, buyer_id: str, action_type: str, expires_at: str | None = None) -> dict[str, Any]:
    """Convenience function to notify about required action"""
    engine = get_auto_response_engine()
    return engine.notify_seller_action_required(order_id=order_id, buyer_id=buyer_id, action_type=action_type, expires_at=expires_at)


def process_ratings_backfill(client: Any, access_token: str, shop_id: int, lookback_days: int = 60, batch_size: int = 50) -> dict[str, Any]:
    """Convenience function to process ratings backfill"""
    engine = get_auto_response_engine()
    return engine.process_ratings_backfill(
        client=client,
        access_token=access_token,
        shop_id=shop_id,
        lookback_days=lookback_days,
        batch_size=batch_size,
    )
