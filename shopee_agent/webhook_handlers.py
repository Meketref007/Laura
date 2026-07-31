"""
webhook_handlers.py - Event handlers for webhook events
Processes MediaSpace, Shopee, and other async events
"""

import functools
import time as _time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from shopee_agent.auto_responses import get_auto_response_engine
from shopee_agent.chat_auto import ChatAutomation
from shopee_agent.client import ShopeeClient
from shopee_agent.config import load_config
from shopee_agent.event_bus import AlertEvent, AsyncEventBus, MetricUpdateEvent, RefundEvent
from shopee_agent.logger import debug, error, info, warning
from shopee_agent.telegram_narrator import narrador
from shopee_agent.webhook_server import WebhookEvent


def _retry_with_backoff(func=None, max_retries=3, base_delay=1.0):
    """Decorator that retries the wrapped function with exponential backoff.
    delay = base_delay * (2 ** attempt). Logs each attempt. On final failure,
    logs the error and returns without crashing.
    """
    if func is None:
        return lambda f: _retry_with_backoff(f, max_retries=max_retries, base_delay=base_delay)

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        last_exc = None
        for attempt in range(1, max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                delay = base_delay * (2 ** (attempt - 1))
                warning(
                    f"Retry {attempt}/{max_retries} for {func.__name__} failed: {exc}",
                    attempt=attempt,
                    max_retries=max_retries,
                    delay=delay,
                )
                if attempt < max_retries:
                    _time.sleep(delay)
        error(
            f"All {max_retries} retries exhausted for {func.__name__}: {last_exc}",
            func=func.__name__,
        )
        return None

    return wrapper


_chat_auto_instance: ChatAutomation | None = None


def _friendly_order_status(status: Any) -> str:
    raw = str(status or "").strip()
    if not raw:
        return "não informado"

    normalized = raw.upper()
    labels = {
        "READY_TO_SHIP": "pronto para envio",
        "UNPAID": "aguardando pagamento",
        "PROCESSED": "em processamento",
        "SHIPPED": "enviado",
        "COMPLETED": "concluído",
        "TO_CONFIRM_RECEIVE": "aguardando confirmação de recebimento",
        "CANCELLED": "cancelado",
        "IN_CANCEL": "cancelamento em andamento",
        "INCOMPLETED": "incompleto",
        "TO_RETURN": "devolução em andamento",
    }
    return labels.get(normalized, raw.replace("_", " ").strip().lower())


def _get_chat_automation() -> ChatAutomation | None:
    global _chat_auto_instance
    if _chat_auto_instance is not None:
        return _chat_auto_instance

    try:
        cfg = load_config()
        if not cfg.default_access_token or cfg.default_shop_id is None:
            return None
        _chat_auto_instance = ChatAutomation(
            client=ShopeeClient(cfg),
            access_token=cfg.default_access_token,
            shop_id=cfg.default_shop_id,
        )
        return _chat_auto_instance
    except Exception as exc:
        warning(f"Failed to initialize chat automation: {exc}")
        return None


class MediaSpaceEventHandler:
    """Handles MediaSpace transcoding events"""

    @staticmethod
    def on_transcoding_complete(event: WebhookEvent) -> None:
        """
        Handle MediaSpace transcoding completion.
        
        Event data expected:
        {
            "job_id": "abc123",
            "video_id": "vid123",
            "status": "completed",
            "output_url": "https://...",
            "duration_ms": 5000
        }
        """
        data = event.data
        job_id = data.get("job_id")
        video_id = data.get("video_id")
        status = data.get("status", "unknown")

        info(f"MediaSpace transcoding {status}: {job_id}",
            video_id=video_id,
            event_id=event.event_id
        )

        if status == "completed":
            output_url = data.get("output_url")
            duration_ms = data.get("duration_ms", 0)

            info("Video transcoded successfully",
                video_id=video_id,
                output_url=output_url,
                duration_ms=duration_ms
            )
        elif status == "failed":
            error_msg = data.get("error", "Unknown error")
            error(f"MediaSpace transcoding failed: {error_msg}",
                video_id=video_id,
                job_id=job_id
            )

    @staticmethod
    def on_transcoding_progress(event: WebhookEvent) -> None:
        """
        Handle MediaSpace transcoding progress.
        
        Event data expected:
        {
            "job_id": "abc123",
            "video_id": "vid123",
            "progress_pct": 45,
            "eta_seconds": 120
        }
        """
        data = event.data
        progress = data.get("progress_pct", 0)
        eta = data.get("eta_seconds", 0)

        debug(f"MediaSpace transcoding progress: {progress}%",
            eta_seconds=eta,
            event_id=event.event_id
        )


class ShopeeEventHandler:
    """Handles Shopee API events"""

    @staticmethod
    def _extract_order_ref(data: dict[str, Any]) -> str:
        for key in ("order_id", "order_sn", "ordersn", "orderSn", "id"):
            value = data.get(key)
            if value:
                return str(value)
        return "?"

    @staticmethod
    def _extract_amount(data: dict[str, Any]) -> float:
        for key in ("total_amount", "amount", "order_total", "payment_amount", "paid_amount", "total_price"):
            value = data.get(key)
            try:
                if isinstance(value, bool) or value is None:
                    continue
                number = float(value)
                if number >= 0:
                    return number
            except Exception:
                continue
        return 0.0

    @staticmethod
    def on_order_created(event: WebhookEvent) -> None:
        """
        Handle Shopee order creation.
        
        Event data expected:
        {
            "order_id": "123456",
            "shop_id": "789",
            "total_amount": 1000,
            "buyer_id": "buyer123"
        }
        """
        data = event.data
        order_id = ShopeeEventHandler._extract_order_ref(data)
        shop_id = data.get("shop_id")
        order_status = data.get("order_status") or data.get("status") or data.get("state") or "created"
        amount = ShopeeEventHandler._extract_amount(data)
        buyer = data.get("buyer_username") or data.get("buyer_nickname") or data.get("buyer_id")
        product = data.get("product_name") or data.get("item_name") or data.get("name")
        quantity = data.get("product_quantity") or data.get("quantity") or data.get("item_quantity")

        info(f"Shopee order created: {order_id}",
            shop_id=shop_id,
            order_status=order_status,
            event_id=event.event_id
        )
        narrador.novo_pedido(
            str(order_id or "?"),
            amount,
            status=str(order_status or ""),
            buyer=str(buyer or "") or None,
            product=str(product or "") or None,
            quantity=quantity,
        )
        if order_status and order_status != "created":
            narrador.webhook_evento("shopee.order_created", f"Pedido `{order_id}` | situação: {_friendly_order_status(order_status)}")

    @staticmethod
    def on_order_cancelled(event: WebhookEvent) -> None:
        """Handle Shopee order cancellation"""
        data = event.data
        order_id = ShopeeEventHandler._extract_order_ref(data)
        reason = data.get("reason", "unknown")

        info(f"Shopee order cancelled: {order_id}",
            reason=reason,
            event_id=event.event_id
        )
        narrador.webhook_evento("shopee.order_cancelled", f"Order `{order_id}` | motivo: {reason}")

    @staticmethod
    def on_buyer_rating(event: WebhookEvent) -> None:
        """
        Handle Shopee buyer rating/review.
        
        Event data expected:
        {
            "order_id": "123456",
            "shop_id": "789",
            "buyer_id": "buyer123",
            "rating": 5,
            "comment": "Produto excelente!",
            "rating_id": "rating123"
        }
        """
        import time
        start_time = time.time()

        data = event.data
        order_id = ShopeeEventHandler._extract_order_ref(data)
        buyer_id = data.get("buyer_id")
        rating = data.get("rating", 0)
        comment = data.get("comment", "")
        # rating_id is not used here
        shop_id = data.get("shop_id")

        info(f"Shopee buyer rating received: {order_id}",
            buyer_id=buyer_id,
            rating=rating,
            event_id=event.event_id
        )

        # Notificar sobre avaliação
        stars = "⭐" * max(0, min(5, rating))
        msg = f"Avaliação recebida para order `{order_id}`: {stars} | {comment[:60]}"
        narrador.webhook_evento("shopee.buyer_rating", msg)

        # Gerar resposta automática com retry
        max_retries = 2
        for attempt in range(1, max_retries + 1):
            try:
                engine = get_auto_response_engine()
                response = engine.respond_to_rating(
                    order_id=str(order_id or "?"),
                    buyer_id=str(buyer_id or "?"),
                    rating=int(rating or 0),
                    comment=str(comment or ""),
                    shop_id=int(shop_id) if shop_id else None
                )

                status = response.get("status")
                response_type = response.get("response_type")
                elapsed = time.time() - start_time

                info(f"Auto-response {status} for rating (attempt {attempt}/{max_retries})",
                    response_status=status,
                    response_type=response_type,
                    elapsed_ms=int(elapsed * 1000)
                )

                # Notificar sucesso
                if status == "sent":
                    narrador.feito(
                        f"Resposta enviada para avaliação {stars}",
                        f"Order: {order_id} em {int(elapsed*1000)}ms"
                    )
                    return
                elif status in ("generated_only", "cooldown"):
                    narrador.webhook_evento(
                        "shopee.buyer_rating",
                        f"Resposta gerada mas não enviada ({status}) para {order_id}"
                    )
                    return

            except Exception as exc:
                elapsed = time.time() - start_time
                warning(f"Failed to generate auto-response for rating (attempt {attempt}/{max_retries}): {exc}",
                       order_id=order_id,
                       buyer_id=buyer_id,
                       elapsed_ms=int(elapsed * 1000))

                if attempt < max_retries:
                    time.sleep(0.5)  # Retry rápido
                else:
                    narrador.alerta(
                        f"⚠️ Falha ao responder avaliação {stars} (order: {order_id}) após {max_retries} tentativas"
                    )

    @staticmethod
    def on_seller_response_required(event: WebhookEvent) -> None:
        """
        Handle Shopee seller response required notification.
        
        Event data expected:
        {
            "order_id": "123456",
            "shop_id": "789",
            "buyer_id": "buyer123",
            "message_type": "rating_response_required",
            "expires_at": "2026-05-10T00:00:00Z"
        }
        """
        data = event.data
        order_id = ShopeeEventHandler._extract_order_ref(data)
        buyer_id = data.get("buyer_id")
        message_type = data.get("message_type", "unknown")
        expires_at = data.get("expires_at")

        info(f"Shopee seller response required: {order_id}",
            message_type=message_type,
            event_id=event.event_id
        )

        msg = f"Resposta do vendedor necessária para order `{order_id}` (tipo: {message_type})"
        narrador.alerta(msg)

        # Registrar ação necessária
        try:
            engine = get_auto_response_engine()
            engine.notify_seller_action_required(
                order_id=str(order_id or "?"),
                buyer_id=str(buyer_id or "?"),
                action_type=message_type,
                expires_at=expires_at
            )
            info("Seller action notification recorded",
                action_type=message_type,
                expires_at=expires_at
            )
        except Exception as exc:
            warning(f"Failed to record seller action: {exc}")

    @staticmethod
    def on_buyer_message(event: WebhookEvent) -> None:
        """Handle buyer chat messages and respond automatically when safe."""
        data = event.data

        # Auto-process incoming chat messages through ChatAutomation (env-gated)
        import os as _os
        if _os.getenv("CHAT_AUTO_RESPOND", "0") == "1":
            if data.get("auto_response_enabled") or True:
                try:
                    from shopee_agent.client import ShopeeClient
                    from shopee_agent.config import load_config

                    from .chat_auto import ChatAutomation
                    cfg = load_config()
                    client = ShopeeClient(cfg)
                    auto = ChatAutomation(client=client)
                    response = auto.respond_to_message(
                        conversation_id=data.get("conversation_id", ""),
                        message_text=data.get("content", ""),
                        buyer_id=data.get("buyer_id", ""),
                    )
                    if response and response.should_respond:
                        auto.send_reply(data.get("conversation_id", ""), response.response_text)
                        info("Auto-responded to chat message", intent=response.classified_intent)
                except Exception as exc:
                    from shopee_agent.logger import error as log_error
                    log_error("Chat auto-response failed", error=str(exc))
        conversation_id = str(data.get("conversation_id") or data.get("conversationId") or data.get("chat_id") or event.event_id)
        buyer_id = str(data.get("buyer_id") or data.get("sender_id") or data.get("from_user_id") or data.get("user_id") or "?")
        message_text = str(
            data.get("message")
            or data.get("text")
            or (data.get("content", {}).get("text") if isinstance(data.get("content"), dict) else "")
            or (data.get("payload", {}).get("text") if isinstance(data.get("payload"), dict) else "")
            or ""
        ).strip()

        info(
            f"Shopee buyer message received: {conversation_id}",
            buyer_id=buyer_id,
            event_id=event.event_id,
        )

        chat_auto = _get_chat_automation()
        if not chat_auto:
            warning("Chat automation unavailable; buyer message left for manual review", conversation_id=conversation_id)
            narrador.webhook_evento("shopee.buyer_message", f"Mensagem recebida de `{buyer_id}`: {message_text[:120]}")
            return

        try:
            response = chat_auto.classify_and_respond(
                conversation_id=conversation_id,
                buyer_id=buyer_id,
                message_text=message_text,
            )
            if response.should_respond:
                narrador.webhook_evento(
                    "shopee.buyer_message",
                    f"Auto-resposta enviada para `{buyer_id}` | intenção: {response.classified_intent} | confiança: {response.confidence:.2f}",
                )
            else:
                narrador.webhook_evento(
                    "shopee.buyer_message",
                    f"Mensagem recebida de `{buyer_id}` sem auto-resposta | intenção: {response.classified_intent}",
                )
        except Exception as exc:
            warning(f"Failed to auto-handle buyer message: {exc}")
            narrador.webhook_evento("shopee.buyer_message", f"Falha ao responder automaticamente para `{buyer_id}`")


class EventHandlerRegistry:
    """
    Registry for all event handlers.
    Centralizes handler setup and management.
    """

    def __init__(self):
        self.handlers: dict[str, Callable[[WebhookEvent], None]] = {}
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        """Register default handlers"""
        # MediaSpace handlers
        self.register(
            "mediaspace.transcoding_complete",
            MediaSpaceEventHandler.on_transcoding_complete
        )
        self.register(
            "mediaspace.transcoding_progress",
            MediaSpaceEventHandler.on_transcoding_progress
        )

        # Shopee handlers
        self.register(
            "shopee.order_created",
            ShopeeEventHandler.on_order_created
        )
        self.register(
            "shopee.order_cancelled",
            ShopeeEventHandler.on_order_cancelled
        )
        self.register(
            "shopee.buyer_rating",
            ShopeeEventHandler.on_buyer_rating
        )
        self.register(
            "shopee.buyer_message",
            _retry_with_backoff(ShopeeEventHandler.on_buyer_message, max_retries=3, base_delay=1.0)
        )
        self.register(
            "shopee.seller_response_required",
            ShopeeEventHandler.on_seller_response_required
        )
        self.register(
            "shopee.order_status_change",
            _retry_with_backoff(ShopeeEventHandler.on_buyer_message, max_retries=3, base_delay=1.0)
        )

    def register(
        self,
        event_type: str,
        handler: Callable[[WebhookEvent], None]
    ) -> None:
        """Register a handler for event type"""
        self.handlers[event_type] = handler
        info(f"Event handler registered: {event_type}")

    def register_with_server(self, server) -> None:
        """Register all handlers with webhook server"""
        for event_type, handler in self.handlers.items():
            server.register_handler(event_type, handler)

        info(f"Registered {len(self.handlers)} handlers with webhook server")

    def handle_event(self, event: WebhookEvent) -> None:
        """Handle an event and emit typed events on the bus if connected."""
        handler = self.handlers.get(event.event_type)

        if handler:
            try:
                handler(event)
            except Exception as e:
                error(f"Error handling {event.event_type}: {str(e)}")
        else:
            warning(f"No handler for event type: {event.event_type}")

        self._emit_to_bus(event)

    @staticmethod
    def on_order_status_change(event: WebhookEvent) -> None:
        """Handle order status changes with retry support."""
        data = event.data
        order_id = ShopeeEventHandler._extract_order_ref(data)
        new_status = data.get("order_status") or data.get("status") or data.get("state") or "unknown"
        prev_status = data.get("previous_status") or data.get("prev_status") or ""
        info(
            f"Shopee order status changed: {order_id}",
            new_status=new_status,
            previous_status=prev_status,
            event_id=event.event_id,
        )
        narrador.webhook_evento(
            "shopee.order_status_change",
            f"Pedido `{order_id}`: {_friendly_order_status(prev_status)} → {_friendly_order_status(new_status)}",
        )

    @staticmethod
    def on_refund_update(event: WebhookEvent) -> None:
        """Handle refund/return updates with retry support."""
        data = event.data
        order_id = ShopeeEventHandler._extract_order_ref(data)
        return_sn = data.get("return_sn") or data.get("refund_id") or data.get("returnsn") or order_id
        refund_status = data.get("return_status") or data.get("status") or data.get("refund_status") or "unknown"
        amount = ShopeeEventHandler._extract_amount(data)
        reason = data.get("reason", data.get("text_reason", ""))
        info(
            f"Shopee refund update: {return_sn}",
            order_id=order_id,
            refund_status=refund_status,
            amount=amount,
            event_id=event.event_id,
        )
        narrador.webhook_evento(
            "shopee.refund_update",
            f"Reembolso `{return_sn}` | pedido `{order_id}` | status: {refund_status} | valor: R$ {amount:.2f} | motivo: {reason[:100]}",
        )

    def _emit_to_bus(self, event: WebhookEvent) -> None:
        bus = _event_bus
        if bus is None:
            return
        try:
            suffix = event.event_type.split(".")[-1] if "." in event.event_type else event.event_type
            if suffix == "order_created":
                bus.submit(AlertEvent(
                    severity="info",
                    title="Novo pedido Shopee",
                    message=f"Pedido {event.data.get('order_id', '?')} criado",
                    tags=["shopee", "order"],
                ))
            elif suffix == "order_cancelled":
                bus.submit(RefundEvent(
                    refund_id=event.data.get("order_id", "?"),
                    refund_reason=event.data.get("reason", "cancelado"),
                    buyer_id=str(event.data.get("buyer_id", "?")),
                    product_id="",
                    amount=0.0,
                    decision="manual_review",
                ))
            elif suffix == "buyer_message":
                bus.submit(AlertEvent(
                    severity="info",
                    title="Mensagem de comprador",
                    message=f"De {event.data.get('buyer_id', '?')}: {str(event.data.get('text', ''))[:200]}",
                    tags=["shopee", "chat"],
                ))
            elif suffix in ("transcoding_complete", "transcoding_progress"):
                bus.submit(MetricUpdateEvent(metrics={
                    "mediaspace_status": suffix,
                    "video_id": event.data.get("video_id", "?"),
                }))
        except Exception as e:
            warning(f"Error emitting bus event from webhook: {e}")


# Global registry
_registry: EventHandlerRegistry = EventHandlerRegistry()

# Optional event bus for typed events (injected by daemon)
_event_bus: AsyncEventBus | None = None


def set_event_bus(bus: AsyncEventBus | None) -> None:
    """Inject event bus into webhook handlers so incoming push events
    emit typed events on the bus."""
    global _event_bus
    _event_bus = bus


def get_registry() -> EventHandlerRegistry:
    """Get global event handler registry"""
    return _registry


def initialize_handlers(server) -> None:
    """Initialize and register all handlers with server"""
    _registry.register_with_server(server)


def emit_test_event(event_type: str, data: dict[str, Any]) -> WebhookEvent:
    """
    Create and process a test event (for testing).
    
    Args:
        event_type: Event type (e.g., "mediaspace.transcoding_complete")
        data: Event data
    
    Returns:
        Created WebhookEvent
    """
    event = WebhookEvent(
        event_id="test_" + str(int(__import__("time").time() * 1000)),
        event_type=event_type,
        source=event_type.split(".")[0],
        timestamp=datetime.now(UTC).isoformat(),
        data=data,
        valid=True
    )

    _registry.handle_event(event)
    return event
