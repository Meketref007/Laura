"""
test_webhook_server.py - Tests for webhook server and handlers
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from shopee_agent.webhook_server import (
    WebhookEvent,
    WebhookServer,
    get_webhook_server,
    initialize_webhook_server,
)
from shopee_agent.webhook_handlers import (
    MediaSpaceEventHandler,
    ShopeeEventHandler,
    EventHandlerRegistry,
    emit_test_event,
)


class TestWebhookEvent:
    """Tests for WebhookEvent"""
    
    def test_event_creation(self):
        """Verify webhook event creation"""
        event = WebhookEvent(
            event_id="evt_123",
            event_type="mediaspace.transcoding_complete",
            source="mediaspace",
            timestamp="2026-04-20T12:00:00+00:00",
            data={"video_id": "vid123", "status": "completed"}
        )
        
        assert event.event_id == "evt_123"
        assert event.event_type == "mediaspace.transcoding_complete"
        assert event.source == "mediaspace"
        assert not event.valid
    
    def test_event_to_dict(self):
        """Verify event serialization"""
        event = WebhookEvent(
            event_id="evt_123",
            event_type="test",
            source="test",
            timestamp="2026-04-20T12:00:00+00:00",
            data={"key": "value"},
            valid=True
        )
        
        data = event.to_dict()
        assert data["event_id"] == "evt_123"
        assert data["event_type"] == "test"
        assert data["valid"] is True


class TestWebhookServer:
    """Tests for WebhookServer"""
    
    def test_server_creation(self):
        """Verify webhook server creation"""
        server = WebhookServer(host="127.0.0.1", port=8765)
        assert server.host == "127.0.0.1"
        assert server.port == 8765
        assert not server.running
    
    def test_register_handler(self):
        """Verify handler registration"""
        server = WebhookServer()
        
        def test_handler(event):
            pass
        
        server.register_handler("test.event", test_handler)
        
        # Handler should be registered
        from shopee_agent.webhook_server import WebhookHandler
        assert "test.event" in WebhookHandler.handlers
    
    def test_event_queue(self):
        """Verify event queueing"""
        server = WebhookServer()
        
        event1 = WebhookEvent(
            event_id="evt_1",
            event_type="test",
            source="test",
            timestamp="2026-04-20T12:00:00+00:00",
            data={},
            valid=True
        )
        
        # Manually add to queue for testing
        from shopee_agent.webhook_server import WebhookHandler
        with WebhookHandler.lock:
            WebhookHandler.event_queue.append(event1)
        
        events = server.get_queued_events()
        assert len(events) >= 1
        
        # Test pop
        popped = server.pop_event()
        assert popped is not None
    
    def test_clear_events(self):
        """Verify event clearing"""
        server = WebhookServer()
        
        from shopee_agent.webhook_server import WebhookHandler
        with WebhookHandler.lock:
            WebhookHandler.event_queue.append(
                WebhookEvent(
                    event_id="evt_1",
                    event_type="test",
                    source="test",
                    timestamp="2026-04-20T12:00:00+00:00",
                    data={},
                    valid=True
                )
            )
        
        count = server.clear_events()
        assert count >= 1
        
        events = server.get_queued_events()
        assert len(events) == 0

    def test_process_event_writes_daily_jsonl(self, tmp_path, monkeypatch):
        """Worker processing must persist webhook events by UTC day."""
        monkeypatch.chdir(tmp_path)
        server = WebhookServer(event_log_dir=str(tmp_path / "webhooks"))

        event = WebhookEvent(
            event_id="evt_daily_1",
            event_type="order_status_push",
            source="shopee",
            timestamp="2026-05-06T12:00:00+00:00",
            data={"shop_id": 123, "order_sn": "A1"},
            valid=True,
        )

        server.process_event(event)

        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out_file = Path(tmp_path / "webhooks" / f"{day}.jsonl")
        legacy_file = Path(tmp_path / "logs" / "laura_webhook.jsonl")
        assert out_file.exists()
        assert legacy_file.exists()
        rows = [r for r in out_file.read_text(encoding="utf-8").splitlines() if r.strip()]
        legacy_rows = [r for r in legacy_file.read_text(encoding="utf-8").splitlines() if r.strip()]
        assert len(rows) == 1
        assert len(legacy_rows) == 1
        payload = json.loads(rows[0])
        legacy_payload = json.loads(legacy_rows[0])
        assert payload["event_type"] == "order_status_push"
        assert payload["shop_id"] == 123
        assert legacy_payload["event_type"] == "order_status_push"

    def test_drain_events_processes_queue(self, tmp_path):
        """Drain should consume all queued events and return processed count."""
        server = WebhookServer(event_log_dir=str(tmp_path / "webhooks"))

        from shopee_agent.webhook_server import WebhookHandler

        with WebhookHandler.lock:
            WebhookHandler.event_queue.append(
                WebhookEvent(
                    event_id="evt_drain_1",
                    event_type="order_status_push",
                    source="shopee",
                    timestamp="2026-05-06T12:00:00+00:00",
                    data={"shop_id": 1},
                    valid=True,
                )
            )
            WebhookHandler.event_queue.append(
                WebhookEvent(
                    event_id="evt_drain_2",
                    event_type="return_updates_push",
                    source="shopee",
                    timestamp="2026-05-06T12:00:01+00:00",
                    data={"shop_id": 1},
                    valid=True,
                )
            )

        drained = server.drain_events()
        assert drained == 2
        assert len(server.get_queued_events()) == 0


class TestEventHandlers:
    """Tests for event handlers"""
    
    def test_registry_creation(self):
        """Verify handler registry creation"""
        registry = EventHandlerRegistry()
        assert len(registry.handlers) > 0
    
    def test_mediaspace_handler(self):
        """Verify MediaSpace handler"""
        event = WebhookEvent(
            event_id="evt_123",
            event_type="mediaspace.transcoding_complete",
            source="mediaspace",
            timestamp="2026-04-20T12:00:00+00:00",
            data={
                "job_id": "job123",
                "video_id": "vid123",
                "status": "completed",
                "output_url": "https://example.com/video.mp4"
            },
            valid=True
        )
        
        # Should not raise
        MediaSpaceEventHandler.on_transcoding_complete(event)
    
    def test_shopee_handler(self):
        """Verify Shopee handler"""
        event = WebhookEvent(
            event_id="evt_123",
            event_type="shopee.order_created",
            source="shopee",
            timestamp="2026-04-20T12:00:00+00:00",
            data={
                "order_id": "order123",
                "shop_id": "shop456",
                "total_amount": 1000
            },
            valid=True
        )
        
        # Should not raise
        ShopeeEventHandler.on_order_created(event)
    
    def test_emit_test_event(self):
        """Verify test event emission"""
        event = emit_test_event(
            event_type="mediaspace.transcoding_complete",
            data={"video_id": "vid123", "status": "completed"}
        )
        
        assert event.event_type == "mediaspace.transcoding_complete"
        assert event.valid is True


class TestGlobalFunctions:
    """Tests for global webhook functions"""
    
    def test_get_webhook_server_singleton(self):
        """Verify webhook server is singleton"""
        server1 = get_webhook_server()
        server2 = get_webhook_server()
        assert server1 is server2
    
    def test_initialize_webhook_server(self):
        """Verify webhook server initialization"""
        # Reset for test
        import shopee_agent.webhook_server as ws_module
        ws_module._webhook_server = None
        
        server = initialize_webhook_server(port=9999)
        assert server.port == 9999
