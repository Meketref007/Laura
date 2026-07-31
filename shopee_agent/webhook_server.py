"""
webhook_server.py - HTTP webhook server for async event handling
Receives and processes MediaSpace transcoding events, Shopee notifications, etc.
"""

import hashlib
import hmac
import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from shopee_agent.event_bus import AsyncEventBus
from shopee_agent.logger import debug, error, info, warning
from shopee_agent.telegram_narrator import narrador
from shopee_agent.tracing import create_trace


@dataclass
class WebhookEvent:
    """Represents a webhook event"""
    event_id: str
    event_type: str
    source: str  # mediaspace, shopee, etc.
    timestamp: str
    data: dict[str, Any]
    signature: str | None = None
    valid: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class WebhookHandler(BaseHTTPRequestHandler):
    """HTTP request handler for webhooks"""

    # Class variables shared across instances
    event_queue: list[WebhookEvent] = []
    handlers: dict[str, list[Callable]] = {}
    secret_key: str | None = None
    allow_unverified_ack: bool = False
    event_processor: Callable[[WebhookEvent], None] | None = None
    event_bus: AsyncEventBus | None = None
    lock = threading.RLock()
    invalid_signature_warning_last_ts: float = 0.0
    invalid_signature_suppressed_count: int = 0

    @staticmethod
    def _get_mini_app_data() -> dict:
        result = {
            "pedidos_hoje": 0, "receita_hoje": 0.0,
            "total_produtos": 0, "margem_media": 0.0,
            "ultimos_pedidos": [], "estoque_baixo": [],
            "custos": [], "loja_nome": "",
            "avaliacao_media": 0.0, "total_avaliacoes": 0,
            "tempo_envio_dias": 0.0, "taxa_atraso": 0.0,
            "pedidos_pendentes": 0, "pedidos_enviados": 0,
        }
        cfg = None
        client = None
        access_token = None
        shop_id = None
        try:
            from shopee_agent.client import ShopeeClient
            from shopee_agent.config import load_config
            cfg = load_config()
            client = ShopeeClient(cfg)
            access_token = cfg.default_access_token
            shop_id = cfg.default_shop_id
            if not access_token or not shop_id:
                return result
        except Exception:
            return result

        try:
            r = client.get_shop_info(access_token=access_token, shop_id=shop_id)
            if r and hasattr(r, "data") and isinstance(r.data, dict):
                result["loja_nome"] = r.data.get("shop_name", "") or ""
        except Exception:
            pass

        try:
            resp = client.get_order_list(access_token=access_token, shop_id=shop_id, limit=10)
            if resp and hasattr(resp, "data"):
                orders = resp.data.get("order_list", []) if isinstance(resp.data, dict) else []
                total = 0.0
                for o in orders[:5]:
                    amt = float(o.get("total_amount", 0) or 0)
                    total += amt
                    items = o.get("items") or [{}]
                    item_name = ""
                    if isinstance(items, list) and items:
                        item_name = items[0].get("item_name", "")
                    result["ultimos_pedidos"].append({
                        "order_sn": o.get("order_sn", ""),
                        "product": item_name,
                        "status": str(o.get("order_status", "")),
                        "status_br": str(o.get("order_status", "")).replace("_", " ").title(),
                        "valor": round(amt, 2),
                    })
                result["pedidos_hoje"] = len(orders) if isinstance(orders, list) else 0
                result["receita_hoje"] = round(total, 2)
        except Exception:
            pass

        try:
            resp = client.get_item_list(access_token=access_token, shop_id=shop_id, limit=50)
            if resp and hasattr(resp, "data"):
                items = resp.data.get("item_list", []) if isinstance(resp.data, dict) else []
                result["total_produtos"] = len(items) if isinstance(items, list) else 0
                margins = []
                final_custos = []
                for p in (items or []):
                    str(p.get("item_id", ""))
                    price = float(p.get("price", 0) or 0) / 1e5
                    stock = int(p.get("stock", 0) or 0)
                    name = p.get("item_name", "Sem nome")[:40]
                    if 0 < stock <= 5:
                        result["estoque_baixo"].append({"nome": name, "stock": stock, "preco": round(price, 2)})
                if margins:
                    result["margem_media"] = round(sum(margins) / len(margins), 1)
                result["custos"] = final_custos[:5]
        except Exception:
            pass

        try:
            from datetime import datetime, timedelta
            now = int(datetime.now(UTC).timestamp())
            yesterday = int((datetime.now(UTC) - timedelta(days=7)).timestamp())
            resp = client.get_order_list(
                access_token=access_token, shop_id=shop_id,
                time_from=yesterday, time_to=now, page_size=100,
            )
            if resp and hasattr(resp, "data"):
                orders = resp.data.get("order_list", []) if isinstance(resp.data, dict) else []
                pendentes = 0
                enviados = 0
                for o in (orders or []):
                    s = str(o.get("order_status", ""))
                    if s in ("READY_TO_SHIP", "PROCESSING"):
                        pendentes += 1
                    elif s in ("SHIPPED", "COMPLETED"):
                        enviados += 1
                result["pedidos_pendentes"] = pendentes
                result["pedidos_enviados"] = enviados
        except Exception:
            pass

        try:
            resp = client.get_shop_performance(access_token=access_token, shop_id=shop_id)
            if resp and hasattr(resp, "data") and isinstance(resp.data, dict):
                perf = resp.data.get("response", resp.data)
                if isinstance(perf, dict):
                    rating = perf.get("shop_rating") or perf.get("rating_star") or perf.get("rating", 0)
                    result["avaliacao_media"] = float(rating) if rating else 0.0
                    result["total_avaliacoes"] = int(perf.get("total_rating", 0) or perf.get("rating_count", 0) or 0)
                    result["tempo_envio_dias"] = float(perf.get("average_shipping_time", 0) or perf.get("ship_time", 0) or 0)
                    result["taxa_atraso"] = float(perf.get("late_ship_rate", 0) or perf.get("late_rate", 0) or 0)
        except Exception:
            pass

        return result

    def _send_ack(self, status: int = 202, reason: str = "accepted") -> None:
        """Send minimal JSON ack for webhook calls."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": reason}).encode("utf-8"))

    def _extract_signature(self) -> str | None:
        """Try common signature header names used by webhook providers."""
        signature = self.headers.get("X-Webhook-Signature")
        if signature:
            return signature.strip()

        signature = self.headers.get("X-Shopee-Hmac-SHA256")
        if signature:
            return signature.strip()

        signature = self.headers.get("X-Signature")
        if signature:
            return signature.strip()

        return None

    def _log_invalid_signature_warning(self, *, path: str, has_signature: bool) -> None:
        """Rate-limit invalid signature warnings to avoid noisy logs."""
        now = time.time()
        cooldown_seconds = int(os.getenv("LAURA_WEBHOOK_INVALID_SIGNATURE_LOG_COOLDOWN_SECONDS", "300"))
        elapsed = now - WebhookHandler.invalid_signature_warning_last_ts

        if elapsed >= cooldown_seconds:
            suppressed = WebhookHandler.invalid_signature_suppressed_count
            WebhookHandler.invalid_signature_suppressed_count = 0
            WebhookHandler.invalid_signature_warning_last_ts = now
            if suppressed > 0:
                warning(
                    "Invalid webhook signature",
                    path=path,
                    has_signature=has_signature,
                    suppressed_since_last=suppressed,
                )
            else:
                warning(
                    "Invalid webhook signature",
                    path=path,
                    has_signature=has_signature,
                )
            return

        WebhookHandler.invalid_signature_suppressed_count += 1

    def _normalize_event_type(self, payload: dict[str, Any]) -> str:
        """Infer a more specific Shopee event type from generic webhook envelopes."""
        raw_type = str(payload.get("event_type") or payload.get("type") or payload.get("topic") or payload.get("name") or "unknown").strip()
        source = str(payload.get("source") or "unknown").strip().lower()

        # Unwrap common envelopes where the real event is nested under data/payload/event
        for nested_key in ("data", "payload", "event"):
            nested = payload.get(nested_key)
            if isinstance(nested, dict):
                nested_type = str(nested.get("event_type") or nested.get("type") or nested.get("topic") or "").strip()
                if nested_type and nested_type not in {"unknown", "shopee_updates"}:
                    return nested_type
                if nested.get("conversation_id") or nested.get("conversationId") or nested.get("sender_id") or nested.get("message") or nested.get("text"):
                    return "shopee.buyer_message"
                if any(key in nested for key in ("order_id", "order_sn", "rating", "rating_id", "message_type", "comment")):
                    if nested.get("message_type") or nested.get("expires_at"):
                        return "shopee.seller_response_required"
                    if nested.get("rating") is not None or nested.get("rating_id") or nested.get("comment"):
                        return "shopee.buyer_rating"
                    if nested.get("order_id") or nested.get("order_sn"):
                        return "shopee.order_created"

        # If the envelope itself carries order/review fields, infer a Shopee event type.
        if source == "shopee" or raw_type in {"unknown", "shopee_updates"}:
            if payload.get("message_type") or payload.get("expires_at"):
                return "shopee.seller_response_required"
            if payload.get("rating") is not None or payload.get("rating_id") or payload.get("comment"):
                return "shopee.buyer_rating"
            if payload.get("conversation_id") or payload.get("conversationId") or payload.get("sender_id") or payload.get("message") or payload.get("text"):
                return "shopee.buyer_message"
            if payload.get("order_id") or payload.get("order_sn") or payload.get("ordersn"):
                return "shopee.order_created"

        return raw_type or "unknown"

    def do_POST(self):
        """Handle POST requests"""
        try:
            # Parse path
            path = urlparse(self.path).path

            # Internal maintenance endpoint: drain currently queued events
            if path == "/drain":
                drained = 0
                while True:
                    with self.lock:
                        if not self.event_queue:
                            break
                        event = self.event_queue.pop(0)
                    processor = self.event_processor
                    if processor is not None:
                        try:
                            processor(event)
                        except Exception as exc:
                            warning(f"Webhook drain processor error: {exc}")
                    drained += 1

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "drained_events": drained}).encode("utf-8"))
                return

            # Get content length
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length <= 0:
                if self.allow_unverified_ack:
                    warning("Webhook verify without body accepted", path=path)
                    self._send_ack(status=202, reason="accepted_verify")
                    return
                self.send_error(400, "No content")
                return

            # Read body
            body = self.rfile.read(content_length)
            signature = self._extract_signature()
            signature_valid = True

            # Verify signature if secret is set
            if self.secret_key:
                signature_valid = self._verify_signature(body, signature)
                if not signature_valid:
                    self._log_invalid_signature_warning(path=path, has_signature=bool(signature))
                    if not self.allow_unverified_ack:
                        self.send_error(401, "Invalid signature")
                        return

            # Parse JSON
            try:
                data = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                warning("Webhook invalid JSON payload", path=path)
                if self.allow_unverified_ack:
                    self._send_ack(status=202, reason="accepted_non_json")
                    return
                self.send_error(400, "Invalid JSON")
                return

            # Create event
            event_type = self._normalize_event_type(data)
            event_data = data.get("data", {}) if isinstance(data.get("data", {}), dict) else {}
            if not event_data:
                event_data = data.get("payload", {}) if isinstance(data.get("payload", {}), dict) else {}
            if not event_data:
                event_data = data.get("event", {}) if isinstance(data.get("event", {}), dict) else {}
            if not event_data:
                event_data = data

            event = WebhookEvent(
                event_id=data.get("event_id", str(int(time.time() * 1000))),
                event_type=event_type,
                source=data.get("source", "unknown"),
                timestamp=data.get("timestamp", datetime.now(UTC).isoformat()),
                data=event_data,
                signature=signature,
                valid=signature_valid
            )

            # Create trace for webhook
            trace = create_trace(
                endpoint=path,
                operation=f"webhook_{event.event_type}"
            )

            debug(f"Webhook received: {event.event_type}",
                event_id=event.event_id,
                source=event.source,
                correlation_id=trace.correlation_id
            )
            # Pass source and signature validity to the narrator so it can apply filters
            narrador.webhook_evento(
                event.event_type,
                f"Fonte: `{event.source}` | Event ID: `{event.event_id}`",
                source=event.source,
                valid=event.valid,
            )

            # Queue event
            with self.lock:
                self.event_queue.append(event)

            # Call handlers
            self._dispatch_event(event)

            # Send response
            self.send_response(202)  # Accepted
            self.send_header("Content-Type", "application/json")
            self.end_headers()

            response = {
                "status": "accepted",
                "event_id": event.event_id
            }
            self.wfile.write(json.dumps(response).encode("utf-8"))

            trace.record_success(status_code=202)

        except Exception as e:
            error(f"Error processing webhook: {str(e)}")
            self.send_error(500, "Internal server error")

    def _serve_file(self, filepath: str, content_type: str = "text/html") -> None:
        try:
            with open(filepath, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404, "File not found")

    def do_GET(self):
        """Handle GET requests (health check / mini-app)"""
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {"status": "ok", "queued_events": len(self.event_queue)}
            self.wfile.write(json.dumps(response).encode("utf-8"))
        elif self.path in ("/mini-app", "/mini-app/"):
            mini_app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini_app.html")
            self._serve_file(mini_app_path)
        elif self.path == "/mini-app/data":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            data = self._get_mini_app_data()
            self.wfile.write(json.dumps(data).encode("utf-8"))
        else:
            self.send_error(404, "Not found")

    def _verify_signature(self, body: bytes, signature: str | None) -> bool:
        """Verify webhook signature"""
        if not signature or not self.secret_key:
            return False

        normalized_signature = signature.strip()
        if normalized_signature.startswith("sha256="):
            normalized_signature = normalized_signature[len("sha256="):]

        expected_signature = hmac.new(
            self.secret_key.encode(),
            body,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(normalized_signature, expected_signature)

    def _dispatch_event(self, event: WebhookEvent) -> None:
        """Dispatch event to registered handlers"""
        if self.event_bus is not None:
            self.event_bus.submit(event)
            return

        with self.lock:
            event_handlers = self.handlers.get(event.event_type, [])
            event_handlers += self.handlers.get("*", [])

        for handler in event_handlers:
            try:
                handler(event)
            except Exception as e:
                warning(f"Handler error for {event.event_type}: {str(e)}")

    def log_message(self, format, *args):
        """Suppress default logging"""
        pass


class WebhookServer:
    """
    Webhook server for receiving async events.
    
    Features:
    - HTTP server listening on configurable port
    - Event queuing and processing
    - Handler registration by event type
    - Signature verification
    - Background thread for processing
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        secret_key: str | None = None,
        allow_unverified_ack: bool = False,
        event_log_dir: str = "reports/webhooks",
        async_worker_count: int = 2,
        max_retries: int = 5,
        retry_delay: float = 10.0,
    ):
        self.host = host
        self.port = port
        self.secret_key = secret_key
        self.allow_unverified_ack = allow_unverified_ack
        self.event_log_dir = Path(event_log_dir)
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.legacy_event_log_path = Path.cwd() / "logs" / "laura_webhook.jsonl"
        self.event_bus = AsyncEventBus(worker_count=async_worker_count)
        self.event_log_dir.mkdir(parents=True, exist_ok=True)
        self.legacy_event_log_path.parent.mkdir(parents=True, exist_ok=True)

        # Set class variables
        WebhookHandler.secret_key = secret_key
        WebhookHandler.allow_unverified_ack = allow_unverified_ack
        WebhookHandler.handlers = {}
        WebhookHandler.event_queue = []
        WebhookHandler.event_bus = self.event_bus

        self.server: HTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.worker_thread: threading.Thread | None = None
        self.running = False

        # Bind queue processor so handler and worker can consume queued events.
        WebhookHandler.event_processor = self.process_event

        info("Webhook server initialized",
            host=host,
            port=port,
            allow_unverified_ack=allow_unverified_ack
        )

    def register_handler(
        self,
        event_type: str,
        handler: Callable[[WebhookEvent], None]
    ) -> None:
        """
        Register a handler for an event type.
        
        Args:
            event_type: Event type to handle (e.g., "mediaspace.transcoding_complete")
            handler: Callable that receives WebhookEvent
        """
        if event_type not in WebhookHandler.handlers:
            WebhookHandler.handlers[event_type] = []

        WebhookHandler.handlers[event_type].append(handler)
        if self.event_bus is not None:
            self.event_bus.register_handler(event_type, handler)
        info(f"Handler registered: {event_type}")

    def start(self) -> None:
        """Start the webhook server in background thread"""
        if self.running:
            warning("Webhook server already running")
            return

        self.running = True
        self.event_bus.start()
        self.thread = threading.Thread(target=self._run_server, daemon=True)
        self.thread.start()
        self.worker_thread = threading.Thread(target=self._event_worker_loop, daemon=True)
        self.worker_thread.start()

        info(f"Webhook server started on {self.host}:{self.port}")

    def stop(self) -> None:
        """Stop the webhook server"""
        self.running = False

        if self.server:
            self.server.shutdown()
            self.server.server_close()

        if self.thread:
            self.thread.join(timeout=5)

        if self.worker_thread:
            self.worker_thread.join(timeout=5)

        if self.event_bus is not None:
            self.event_bus.stop()

        info("Webhook server stopped")

    def _run_server(self) -> None:
        """Run HTTP server in background thread, with auto-reconnect."""
        retries = 0
        while self.running and retries < self.max_retries:
            try:
                self.server = HTTPServer((self.host, self.port), WebhookHandler)
                info(f"Webhook server listening on {self.host}:{self.port}")
                self.server.serve_forever()
            except OSError as e:
                retries += 1
                wait = self.retry_delay * (2 ** (retries - 1))
                warning(f"Webhook server bind failed (attempt {retries}/{self.max_retries}): {e}",
                       retry_in_seconds=wait)
                if retries < self.max_retries:
                    time.sleep(wait)
                else:
                    error("Webhook server max retries reached, giving up")
            except Exception as e:
                error(f"Webhook server error: {str(e)}")
                if self.running:
                    retries += 1
                    wait = self.retry_delay
                    warning(f"Webhook server restarting in {wait}s (attempt {retries}/{self.max_retries})")
                    time.sleep(wait)

    def get_queued_events(self) -> list[WebhookEvent]:
        """Get all queued events"""
        with WebhookHandler.lock:
            events = WebhookHandler.event_queue.copy()
        return events

    def pop_event(self) -> WebhookEvent | None:
        """Remove and return first queued event"""
        with WebhookHandler.lock:
            if WebhookHandler.event_queue:
                return WebhookHandler.event_queue.pop(0)
        return None

    def clear_events(self) -> int:
        """Clear all queued events"""
        with WebhookHandler.lock:
            count = len(WebhookHandler.event_queue)
            WebhookHandler.event_queue.clear()
        return count

    def log_event(self, event: WebhookEvent) -> None:
        """Log event to file for audit trail"""
        try:
            log_file = self.event_log_dir / f"{event.source}_events.jsonl"

            with open(log_file, "a") as f:
                f.write(json.dumps(event.to_dict()) + "\n")
        except Exception as e:
            warning(f"Could not log event: {str(e)}")

    def process_event(self, event: WebhookEvent) -> None:
        """Persist queued webhook event and optionally notify Telegram."""
        self._log_event_daily(event)
        self._notify_important_event(event)

    def drain_events(self) -> int:
        """Process all currently queued events immediately."""
        drained = 0
        while True:
            event = self.pop_event()
            if event is None:
                break
            self.process_event(event)
            drained += 1
        return drained

    def _event_worker_loop(self) -> None:
        """Continuously consume queued events and process them."""
        while self.running:
            event = self.pop_event()
            if event is None:
                time.sleep(0.5)
                continue
            try:
                self.process_event(event)
            except Exception as exc:
                warning(f"Webhook worker failed to process event: {exc}")

    def _log_event_daily(self, event: WebhookEvent) -> None:
        """Append event to reports/webhooks/YYYY-MM-DD.jsonl."""
        try:
            day = datetime.now(UTC).strftime("%Y-%m-%d")
            record = {
                "timestamp": datetime.now(UTC).isoformat(),
                "event_id": event.event_id,
                "event_type": event.event_type,
                "source": event.source,
                "shop_id": event.data.get("shop_id") if isinstance(event.data, dict) else None,
                "valid": event.valid,
                "data": event.data,
            }
            serialized = json.dumps(record, ensure_ascii=True) + "\n"

            daily_log_file = self.event_log_dir / f"{day}.jsonl"
            with daily_log_file.open("a", encoding="utf-8") as f:
                f.write(serialized)

            with self.legacy_event_log_path.open("a", encoding="utf-8") as f:
                f.write(serialized)
        except Exception as exc:
            warning(f"Could not write daily webhook log: {exc}")

    def _notify_important_event(self, event: WebhookEvent) -> None:
        """Send Telegram notification for priority webhook events."""
        if event.event_type not in {"order_status_push", "return_updates_push"}:
            return

        try:
            shop_id = ""
            if isinstance(event.data, dict):
                raw_shop_id = event.data.get("shop_id") or event.data.get("shopid") or ""
                shop_id = str(raw_shop_id).strip()
            detail = f"shop_id={shop_id}" if shop_id else f"event_id={event.event_id}"
            narrador.webhook_evento(event.event_type, detail, source=event.source, valid=event.valid)
        except Exception as exc:
            warning(f"Could not notify Telegram for webhook event: {exc}")


# Global instance
_webhook_server: WebhookServer | None = None


def initialize_webhook_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    secret_key: str | None = None,
    allow_unverified_ack: bool = False,
) -> WebhookServer:
    """Initialize or reconfigure global webhook server"""
    global _webhook_server

    if _webhook_server is None:
        _webhook_server = WebhookServer(
            host=host,
            port=port,
            secret_key=secret_key,
            allow_unverified_ack=allow_unverified_ack,
        )
    else:
        # Update existing instance settings
        _webhook_server.secret_key = secret_key
        _webhook_server.allow_unverified_ack = allow_unverified_ack
        WebhookHandler.secret_key = secret_key
        WebhookHandler.allow_unverified_ack = allow_unverified_ack
        info("Webhook server reconfigured",
            allow_unverified_ack=allow_unverified_ack,
            has_secret=bool(secret_key),
        )

    return _webhook_server


def get_webhook_server() -> WebhookServer:
    """Get global webhook server"""
    global _webhook_server

    if _webhook_server is None:
        _webhook_server = WebhookServer()

    return _webhook_server
