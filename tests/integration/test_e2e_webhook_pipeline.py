"""E2E: Webhook receive -> process -> chat response -> notification."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from shopee_agent.webhook_server import WebhookEvent, WebhookHandler, WebhookServer
from shopee_agent.webhook_handlers import (
    EventHandlerRegistry,
    ShopeeEventHandler,
    MediaSpaceEventHandler,
    emit_test_event,
    _registry,
)
from shopee_agent.telegram_narrator import LauraTelegramNarrator, narrador


@pytest.fixture
def mock_telegram():
    with patch.object(narrador, "_should_send", return_value=False):
        yield narrador


@pytest.fixture
def mock_narrador():
    with patch("shopee_agent.webhook_handlers.narrador") as mock:
        yield mock


@pytest.fixture
def mock_narrador_server():
    with patch("shopee_agent.webhook_server.narrador") as mock:
        yield mock


@pytest.mark.integration
class TestWebhookParsing:
    """E2E: Webhook payload parsing and event creation."""

    def test_webhook_event_creation(self):
        event = WebhookEvent(
            event_id="evt_001",
            event_type="shopee.order_created",
            source="shopee",
            timestamp=datetime.now(timezone.utc).isoformat(),
            data={"order_id": "12345", "total_amount": 15000},
            valid=True,
        )
        assert event.event_id == "evt_001"
        assert event.event_type == "shopee.order_created"
        assert event.data["order_id"] == "12345"
        d = event.to_dict()
        assert d["event_type"] == "shopee.order_created"

    def test_webhook_event_without_signature(self):
        event = WebhookEvent(
            event_id="evt_002",
            event_type="mediaspace.transcoding_complete",
            source="mediaspace",
            timestamp=datetime.now(timezone.utc).isoformat(),
            data={"job_id": "j_001", "status": "completed"},
        )
        assert event.signature is None
        assert event.valid is False

    def test_extract_order_ref_with_various_keys(self):
        assert ShopeeEventHandler._extract_order_ref({"order_id": "123"}) == "123"
        assert ShopeeEventHandler._extract_order_ref({"order_sn": "SNAP456"}) == "SNAP456"
        assert ShopeeEventHandler._extract_order_ref({"ordersn": "ORD789"}) == "ORD789"
        assert ShopeeEventHandler._extract_order_ref({"id": "ID001"}) == "ID001"
        assert ShopeeEventHandler._extract_order_ref({}) == "?"

    def test_extract_amount_with_various_keys(self):
        assert ShopeeEventHandler._extract_amount({"total_amount": 100.50}) == 100.50
        assert ShopeeEventHandler._extract_amount({"amount": 200}) == 200.0
        assert ShopeeEventHandler._extract_amount({"paid_amount": 150.75}) == 150.75
        assert ShopeeEventHandler._extract_amount({}) == 0.0


@pytest.mark.integration
class TestWebhookHandlerDispatch:
    """E2E: Handler registration and dispatch."""

    @pytest.fixture
    def registry(self, mock_narrador):
        return EventHandlerRegistry()

    def test_register_handler_called_for_event(self, registry):
        handler = MagicMock()
        registry.register("test.event", handler)
        event = WebhookEvent(
            event_id="evt_dispatch",
            event_type="test.event",
            source="test",
            timestamp=datetime.now(timezone.utc).isoformat(),
            data={"key": "value"},
        )
        registry.handle_event(event)
        handler.assert_called_once_with(event)

    def test_no_handler_for_unknown_event(self, registry):
        event = WebhookEvent(
            event_id="evt_unknown",
            event_type="unknown.type",
            source="unknown",
            timestamp=datetime.now(timezone.utc).isoformat(),
            data={},
        )
        registry.handle_event(event)

    def test_mediaspace_transcoding_handler(self, registry):
        event = WebhookEvent(
            event_id="evt_ms_001",
            event_type="mediaspace.transcoding_complete",
            source="mediaspace",
            timestamp=datetime.now(timezone.utc).isoformat(),
            data={"job_id": "j001", "video_id": "v001", "status": "completed", "output_url": "https://example.com/video.mp4"},
        )
        registry.handle_event(event)

    def test_shopee_order_created_handler(self, registry, mock_narrador):
        event = WebhookEvent(
            event_id="evt_shop_001",
            event_type="shopee.order_created",
            source="shopee",
            timestamp=datetime.now(timezone.utc).isoformat(),
            data={"order_id": "ORD001", "total_amount": 25000, "buyer_id": "buyer123"},
        )
        registry.handle_event(event)
        assert mock_narrador.novo_pedido.called

    def test_shopee_buyer_rating_handler(self, registry, mock_narrador):
        with patch("shopee_agent.webhook_handlers.get_auto_response_engine") as mock_engine:
            mock_engine.return_value.respond_to_rating.return_value = {"status": "generated_only", "response_type": "auto"}
            event = WebhookEvent(
                event_id="evt_rating_001",
                event_type="shopee.buyer_rating",
                source="shopee",
                timestamp=datetime.now(timezone.utc).isoformat(),
                data={"order_id": "ORD001", "buyer_id": "buyer1", "rating": 5, "comment": "Great!"},
            )
            registry.handle_event(event)
            assert mock_narrador.webhook_evento.called

    def test_shopee_buyer_message_handler(self, registry, mock_narrador):
        with patch("shopee_agent.webhook_handlers._get_chat_automation", return_value=None):
            event = WebhookEvent(
                event_id="evt_chat_001",
                event_type="shopee.buyer_message",
                source="shopee",
                timestamp=datetime.now(timezone.utc).isoformat(),
                data={"conversation_id": "conv1", "buyer_id": "buyer1", "text": "Onde esta meu pedido?"},
            )
            registry.handle_event(event)
            assert mock_narrador.webhook_evento.called

    def test_shopee_order_cancelled_handler(self, registry, mock_narrador):
        event = WebhookEvent(
            event_id="evt_cancel_001",
            event_type="shopee.order_cancelled",
            source="shopee",
            timestamp=datetime.now(timezone.utc).isoformat(),
            data={"order_id": "ORD001", "reason": "buyer_request"},
        )
        registry.handle_event(event)
        assert mock_narrador.webhook_evento.called

    def test_shopee_seller_response_required_handler(self, registry, mock_narrador):
        with patch("shopee_agent.webhook_handlers.get_auto_response_engine") as mock_engine:
            event = WebhookEvent(
                event_id="evt_seller_001",
                event_type="shopee.seller_response_required",
                source="shopee",
                timestamp=datetime.now(timezone.utc).isoformat(),
                data={"order_id": "ORD001", "buyer_id": "buyer1", "message_type": "rating_response_required"},
            )
            registry.handle_event(event)
            assert mock_narrador.alerta.called

    def test_multiple_handlers_same_event_type(self, registry):
        handler_a = MagicMock()
        handler_b = MagicMock()
        registry.register("multi.test", handler_a)
        registry.register("multi.test", handler_b)
        event = WebhookEvent(
            event_id="evt_multi",
            event_type="multi.test",
            source="test",
            timestamp=datetime.now(timezone.utc).isoformat(),
            data={},
        )
        registry.handle_event(event)


@pytest.mark.integration
class TestWebhookChatPipeline:
    """E2E: Webhook -> chat automation pipeline."""

    def test_chat_automation_triggered_by_buyer_message(self, mock_narrador):
        with patch("shopee_agent.webhook_handlers._get_chat_automation") as mock_get_auto:
            mock_auto = MagicMock()
            mock_response = MagicMock()
            mock_response.should_respond = True
            mock_response.classified_intent = "tracking"
            mock_response.response_text = "Seu pedido foi enviado!"
            mock_response.confidence = 0.95
            mock_auto.classify_and_respond.return_value = mock_response
            mock_get_auto.return_value = mock_auto

            event = WebhookEvent(
                event_id="evt_chat_auto",
                event_type="shopee.buyer_message",
                source="shopee",
                timestamp=datetime.now(timezone.utc).isoformat(),
                data={"conversation_id": "conv1", "buyer_id": "buyer1", "text": "Cadastrou?"},
            )
            registry = EventHandlerRegistry()
            registry.handle_event(event)
            assert mock_auto.classify_and_respond.called

    def test_emit_test_event_creates_and_handles(self, mock_narrador):
        event = emit_test_event("shopee.order_created", {"order_id": "TEST001", "total_amount": 1000})
        assert event.event_type == "shopee.order_created"
        assert event.data["order_id"] == "TEST001"
        assert event.event_id.startswith("test_")

    def test_friendly_order_status_translation(self):
        from shopee_agent.webhook_handlers import _friendly_order_status
        assert "pronto para envio" in _friendly_order_status("READY_TO_SHIP")
        assert "cancelado" in _friendly_order_status("CANCELLED")
        assert "enviado" in _friendly_order_status("SHIPPED")
        assert "concluído" in _friendly_order_status("COMPLETED")
        assert "não informado" in _friendly_order_status("")
        assert "não informado" in _friendly_order_status(None)


@pytest.mark.integration
class TestTelegramNotificationIntegration:
    """E2E: Telegram notification from webhook events."""

    def test_telegram_narrator_creates_message(self):
        narrator = LauraTelegramNarrator()
        with patch.object(narrator, "_should_send", return_value=True):
            with patch.object(narrator, "_post_message") as mock_post:
                narrator.novo_pedido("ORD001", 150.00, status="READY_TO_SHIP", buyer="João", product="Produto X")
                assert mock_post.called

    def test_webhook_evento_sends_notification(self):
        narrator = LauraTelegramNarrator()
        with patch.object(narrator, "_should_send", return_value=True):
            with patch.object(narrator, "_post_message") as mock_post:
                narrator.webhook_evento("shopee.order_created", "Novo pedido ORD001")
                assert mock_post.called

    def test_telegram_rate_limiting(self):
        narrator = LauraTelegramNarrator()
        with patch.object(narrator, "_should_send", return_value=True):
            with patch.object(narrator, "_post_message") as mock_post:
                narrator.webhook_evento("shopee.order_created", "Event 1")
                narrator.webhook_evento("shopee.order_created", "Event 2")
                assert mock_post.call_count >= 1

    def test_telegram_disabled_when_no_token(self):
        with patch.dict("os.environ", {"LAURA_ALERT_TELEGRAM_BOT_TOKEN": "", "LAURA_TELEGRAM_NARRATOR": "1"}, clear=True):
            narrator = LauraTelegramNarrator()
            assert narrator._should_send("INFO") is False

    def test_telegram_post_message_handles_errors(self):
        narrator = LauraTelegramNarrator()
        with patch.object(narrator, "_session") as mock_session:
            mock_session.post.side_effect = Exception("Network error")
            narrator._post_message("test")


@pytest.mark.integration
class TestWebhookServerIntegration:
    """E2E: Webhook server lifecycle and event processing."""

    def test_webhook_server_init(self, mock_narrador_server):
        server = WebhookServer(host="127.0.0.1", port=0, allow_unverified_ack=True, event_log_dir=str(Path(".")))
        assert server.host == "127.0.0.1"
        assert server.allow_unverified_ack is True

    def test_register_handler_on_server(self, mock_narrador_server):
        server = WebhookServer(host="127.0.0.1", port=0, allow_unverified_ack=True, event_log_dir=str(Path(".")))
        handler = MagicMock()
        server.register_handler("test.event", handler)
        assert "test.event" in WebhookHandler.handlers

    def test_queue_and_pop_event(self, mock_narrador_server):
        server = WebhookServer(host="127.0.0.1", port=0, allow_unverified_ack=True, event_log_dir=str(Path(".")))
        event = WebhookEvent(
            event_id="q_001",
            event_type="test",
            source="test",
            timestamp=datetime.now(timezone.utc).isoformat(),
            data={},
        )
        with WebhookHandler.lock:
            WebhookHandler.event_queue.append(event)
        popped = server.pop_event()
        assert popped is not None
        assert popped.event_id == "q_001"

    def test_clear_events(self, mock_narrador_server):
        server = WebhookServer(host="127.0.0.1", port=0, allow_unverified_ack=True, event_log_dir=str(Path(".")))
        with WebhookHandler.lock:
            WebhookHandler.event_queue.append(
                WebhookEvent(event_id="c_001", event_type="test", source="test", timestamp="", data={})
            )
        count = server.clear_events()
        assert count == 1

    def test_drain_events(self, mock_narrador_server):
        server = WebhookServer(host="127.0.0.1", port=0, allow_unverified_ack=True, event_log_dir=str(Path(".")))
        with patch.object(server, "process_event"):
            with WebhookHandler.lock:
                WebhookHandler.event_queue.append(
                    WebhookEvent(event_id="d_001", event_type="test", source="test", timestamp="", data={})
                )
            drained = server.drain_events()
            assert drained == 1

    def test_log_event_to_file(self, mock_narrador_server, tmp_path):
        server = WebhookServer(host="127.0.0.1", port=0, allow_unverified_ack=True, event_log_dir=str(tmp_path / "webhooks"))
        event = WebhookEvent(
            event_id="log_001",
            event_type="test.event",
            source="test",
            timestamp=datetime.now(timezone.utc).isoformat(),
            data={"key": "value"},
        )
        server.log_event(event)
        log_file = tmp_path / "webhooks" / "test_events.jsonl"
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "log_001" in content


from pathlib import Path
