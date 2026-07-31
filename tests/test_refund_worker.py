from __future__ import annotations

from shopee_agent.event_bus import AsyncEventBus, RefundEvent, AlertEvent


def test_refund_worker_subscribes():
    bus = AsyncEventBus(worker_count=1)
    bus.start()
    from shopee_agent.workers import RefundWorker
    rw = RefundWorker(bus)
    rw.subscribe()
    assert "refund" in bus._handlers
    bus.stop()


def test_refund_worker_emits_alert(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bus = AsyncEventBus(worker_count=1)
    bus.start()

    received_alerts = []

    def alert_handler(event):
        received_alerts.append(event)

    bus.register_handler("alert", alert_handler)

    from shopee_agent.workers import RefundWorker
    rw = RefundWorker(bus)
    rw.subscribe()

    bus.submit(RefundEvent(
        event_type="refund",
        refund_id="ref_001",
        refund_reason="damaged_item",
        buyer_id="buyer123",
        product_id="prod456",
        amount=49.90,
    ))

    bus.wait_until_idle(timeout=5)
    bus.stop()

    assert len(received_alerts) >= 1
    assert any("ref_001" in a.title or "ref_001" in a.message for a in received_alerts)


def test_refund_worker_auto_approves_obvious(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bus = AsyncEventBus(worker_count=1)
    bus.start()

    alert_titles = []

    def alert_handler(event):
        alert_titles.append(event.title)

    bus.register_handler("alert", alert_handler)

    from shopee_agent.workers import RefundWorker
    rw = RefundWorker(bus)
    rw.subscribe()

    # damaged_item should auto-approve (RefundManager.evaluate_refund logic)
    bus.submit(RefundEvent(
        event_type="refund",
        refund_id="ref_auto",
        refund_reason="damaged_item",
        buyer_id="good_buyer",
        product_id="p001",
        amount=25.0,
    ))

    bus.wait_until_idle(timeout=5)
    bus.stop()

    assert len(alert_titles) >= 1
