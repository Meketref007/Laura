from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from shopee_agent.event_bus import AsyncEventBus, DeadLetterEvent, EventBusStats
from shopee_agent.workers import DecisionWorker
from shopee_agent.workers_management import WorkersManager, _dlq_to_dict, _percentile


@pytest.fixture
def mock_bus():
    bus = MagicMock(spec=AsyncEventBus)
    bus.stats.return_value = EventBusStats(queued=10, processed=100, failed=2, retried=1, dlq_count=0)
    bus.dlq.return_value = []
    bus._running = True
    bus._handler_names = {
        "decision.signal": ["decision"],
        "cycle.complete": ["decision", "outcome"],
    }
    return bus


@pytest.fixture
def manager(mock_bus, tmp_path):
    return WorkersManager(event_bus=mock_bus, reports_dir=str(tmp_path))


class TestWorkersManager:
    def test_list_workers(self, manager):
        workers = manager.list_workers()
        assert isinstance(workers, list)
        assert len(workers) >= 2
        names = {w["name"] for w in workers}
        assert "decision" in names
        assert "outcome" in names

    def test_list_workers_no_bus(self, tmp_path):
        m = WorkersManager(event_bus=None, reports_dir=str(tmp_path))
        workers = m.list_workers()
        assert isinstance(workers, list)

    def test_get_worker_status(self, manager):
        status = manager.get_worker_status("decision")
        assert status.get("name") == "decision"
        assert "label" in status

    def test_get_worker_status_not_found(self, manager):
        status = manager.get_worker_status("nonexistent")
        assert "error" in status

    def test_pause_worker(self, manager):
        assert manager.pause_worker("decision") is True
        assert "decision" in manager._paused

    def test_pause_worker_unknown(self, manager):
        assert manager.pause_worker("unknown_worker") is False

    def test_resume_worker(self, manager):
        manager._paused.add("decision")
        assert manager.resume_worker("decision") is True
        assert "decision" not in manager._paused

    def test_resume_worker_not_paused(self, manager):
        assert manager.resume_worker("decision") is False

    def test_get_worker_stats(self, manager):
        stats = manager.get_worker_stats("decision", days=7)
        assert stats["worker"] == "decision"
        assert "total_processed" in stats
        assert "error_rate_pct" in stats

    def test_get_worker_stats_not_found(self, manager):
        stats = manager.get_worker_stats("ghost")
        assert "error" in stats

    def test_get_queue_stats(self, manager):
        stats = manager.get_queue_stats()
        assert "total_workers" in stats
        assert "running" in stats
        assert "paused" in stats
        assert stats.get("bus_queued") == 10

    def test_get_queue_stats_no_bus(self, tmp_path):
        m = WorkersManager(event_bus=None, reports_dir=str(tmp_path))
        stats = m.get_queue_stats()
        assert stats["total_workers"] >= 0

    def test_record_processed(self, manager):
        manager.record_processed("decision", latency_ms=12.5)
        assert manager._processed_counts["decision"] == 1
        assert manager._latency_buckets["decision"] == [12.5]

    def test_record_processed_no_latency(self, manager):
        manager.record_processed("decision")
        assert manager._processed_counts["decision"] == 1
        assert manager._latency_buckets.get("decision") is None

    def test_record_error(self, manager):
        manager.record_error("decision")
        assert manager._error_counts["decision"] == 1
        manager.record_error("decision")
        assert manager._error_counts["decision"] == 2

    def test_register_instance(self, manager, mock_bus):
        worker = DecisionWorker(bus=mock_bus)
        manager.register_instance(worker)
        assert "decision" in manager._instances

    def test_unregister_instance(self, manager, mock_bus):
        worker = DecisionWorker(bus=mock_bus)
        manager.register_instance(worker)
        manager.unregister_instance("decision")
        assert "decision" not in manager._instances

    def test_persistence(self, tmp_path):
        m1 = WorkersManager(event_bus=None, reports_dir=str(tmp_path))
        m1.record_processed("test_worker", 5.0)
        m1.record_error("test_worker")
        m1._save_state()

        state_file = Path(tmp_path) / "workers_state.json"
        assert state_file.exists()

        m2 = WorkersManager(event_bus=None, reports_dir=str(tmp_path))
        assert m2._processed_counts.get("test_worker") == 1
        assert m2._error_counts.get("test_worker") == 1


class TestHelpers:
    def test_percentile(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        assert _percentile(data, 50) == 5.5
        assert _percentile(data, 100) == 10.0
        assert _percentile(data, 0) == 1.0

    def test_percentile_empty(self):
        assert _percentile([], 95) == 0.0

    def test_dlq_to_dict(self):
        dl = DeadLetterEvent(
            event_type="test.event",
            handler_name="handler",
            error="some error",
            retry_count=2,
            last_attempt=None,
        )
        d = _dlq_to_dict(dl)
        assert d["event_type"] == "test.event"
        assert d["retry_count"] == 2
        assert d["last_attempt"] is None
