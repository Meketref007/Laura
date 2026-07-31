"""Tests for webhook event handlers."""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone


@pytest.fixture
def registry():
    from shopee_agent.webhook_handlers import EventHandlerRegistry
    return EventHandlerRegistry()


@pytest.fixture
def webhook_event():
    from shopee_agent.webhook_server import WebhookEvent
    return WebhookEvent(
        event_id="test_001",
        event_type="shopee.order_created",
        source="shopee",
        timestamp=datetime.now(timezone.utc).isoformat(),
        data={"order_id": "ORD123", "total_amount": 150.0, "buyer_id": "buyer1"},
        valid=True,
    )


def test_webhook_handler_registration(registry):
    assert len(registry.handlers) >= 5
    assert "shopee.order_created" in registry.handlers
    assert "shopee.buyer_message" in registry.handlers
    assert "mediaspace.transcoding_complete" in registry.handlers


def test_on_order_status_change(registry, webhook_event):
    with patch("shopee_agent.webhook_handlers.narrador") as mock_narrador:
        registry.handle_event(webhook_event)
        assert mock_narrador.novo_pedido.called


def test_on_buyer_message(registry):
    from shopee_agent.webhook_server import WebhookEvent
    from shopee_agent.webhook_handlers import ShopeeEventHandler
    event = WebhookEvent(
        event_id="test_002",
        event_type="shopee.buyer_message",
        source="shopee",
        timestamp=datetime.now(timezone.utc).isoformat(),
        data={"conversation_id": "conv1", "buyer_id": "buyer1", "content": "Hello"},
        valid=True,
    )
    with patch("shopee_agent.webhook_handlers._get_chat_automation") as mock_get_chat:
        mock_chat = MagicMock()
        mock_response = MagicMock()
        mock_response.should_respond = True
        mock_response.classified_intent = "greeting"
        mock_response.confidence = 0.95
        mock_chat.classify_and_respond.return_value = mock_response
        mock_get_chat.return_value = mock_chat
        with patch("shopee_agent.webhook_handlers.narrador") as mock_narrador:
            registry.handle_event(event)
            assert mock_chat.classify_and_respond.called


def test_on_refund_update(registry):
    from shopee_agent.webhook_server import WebhookEvent
    from shopee_agent.webhook_handlers import EventHandlerRegistry
    event = WebhookEvent(
        event_id="test_003",
        event_type="shopee.order_cancelled",
        source="shopee",
        timestamp=datetime.now(timezone.utc).isoformat(),
        data={"order_id": "ORD456", "reason": "buyer_request"},
        valid=True,
    )
    with patch("shopee_agent.webhook_handlers.narrador") as mock_narrador:
        registry.handle_event(event)
        assert mock_narrador.webhook_evento.called


def test_invalid_payload_handling(registry):
    from shopee_agent.webhook_server import WebhookEvent
    event = WebhookEvent(
        event_id="test_bad",
        event_type="unknown.event",
        source="unknown",
        timestamp=datetime.now(timezone.utc).isoformat(),
        data={},
        valid=False,
    )
    with patch("shopee_agent.webhook_handlers.warning") as mock_warning:
        registry.handle_event(event)
        assert mock_warning.called
