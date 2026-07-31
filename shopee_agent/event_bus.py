"""
Async event bus for Phase 36 + typed event system.

Provides a small background worker pool that can dispatch events to sync or
async handlers without blocking the caller thread.
Supports retry with backoff, dead-letter queue, and event journal (WAL).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .logger import debug, info, warning

EventHandler = Callable[[Any], Any]
_STOP_SENTINEL = object()


# --- Typed Event System ---

@dataclass
class Event:
    """Base event with timestamp and source tracking."""
    event_type: str = ""
    timestamp: datetime | None = None
    source: str = ""
    data: Any = None

    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now(UTC)


@dataclass
class DecisionSignalEvent(Event):
    """Emitted when a new decision signal arrives for processing."""
    event_type: str = "decision.signal"
    signal: Any = None
    context: Any = None


@dataclass
class DecisionExecutedEvent(Event):
    """Emitted after a decision has been executed."""
    event_type: str = "decision.executed"
    decision_id: str = ""
    rule_id: str = ""
    status: str = ""
    result: Any = None


@dataclass
class OutcomeRecordedEvent(Event):
    """Emitted when an outcome is recorded for a decision."""
    event_type: str = "outcome.recorded"
    decision_id: str = ""
    rule_id: str = ""
    outcome_type: str = ""
    impact_realized: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GOAPPlanExecutedEvent(Event):
    """Emitted when a GOAP plan is executed during a decision cycle."""
    event_type: str = "goap.plan_executed"
    actions: list[str] = field(default_factory=list)
    total_cost: float = 0.0
    results: list[dict[str, Any]] = field(default_factory=list)
    all_ok: bool = False
    state_snapshot: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now(UTC)


@dataclass
class CycleCompleteEvent(Event):
    """Emitted after each daemon/autonomous cycle completes."""
    event_type: str = "cycle.complete"
    cycle_number: int = 0
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class AlertEvent(Event):
    """Emitted for system alerts that need notification."""
    event_type: str = "alert"
    severity: str = "info"
    title: str = ""
    message: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class MetricUpdateEvent(Event):
    """Emitted when system metrics are updated."""
    event_type: str = "metric.update"
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class RefundEvent(Event):
    """Emitted for refund-related events."""
    event_type: str = "refund"
    refund_id: str = ""
    order_id: str = ""
    refund_reason: str = ""
    buyer_id: str = ""
    product_id: str = ""
    amount: float = 0.0
    decision: str = ""  # auto_approve | manual_review | reject
    status: str = "pending"
    requested_at: str = ""


@dataclass
class DeadLetterEvent:
    """Wraps a failed event with retry metadata for the DLQ."""
    event: Any = None
    error: str = ""
    retry_count: int = 0
    last_attempt: datetime | None = None
    event_type: str = ""
    handler_name: str = ""


@dataclass
class EventBusStats:
    queued: int = 0
    processed: int = 0
    failed: int = 0
    retried: int = 0
    dlq_count: int = 0


_CRITICAL_EVENT_TYPES = {"alert"}

_MAX_RETRIES = 3
_RETRY_BACKOFF_SEC = 1.0


def _event_to_dict(event: Any) -> dict[str, Any]:
    """Convert an event to a JSON-serializable dict."""
    if hasattr(event, "__dataclass_fields__"):
        d = {}
        for f_name in event.__dataclass_fields__:
            val = getattr(event, f_name)
            if isinstance(val, datetime):
                d[f_name] = val.isoformat()
            elif isinstance(val, BaseException):
                d[f_name] = str(val)
            else:
                try:
                    json.dumps(val)
                    d[f_name] = val
                except (TypeError, ValueError):
                    d[f_name] = str(val)
        return d
    return {"raw": str(event)}


class AsyncEventBus:
    """Background event bus with priority queue, retry, DLQ, and WAL support."""

    def __init__(
        self,
        worker_count: int = 2,
        queue_maxsize: int = 0,
        max_retries: int = _MAX_RETRIES,
        retry_backoff: float = _RETRY_BACKOFF_SEC,
        journal_path: str | None = None,
    ):
        if worker_count <= 0:
            raise ValueError("worker_count must be > 0")

        self.worker_count = worker_count
        self.queue_maxsize = queue_maxsize
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self._handlers: dict[str, list[EventHandler]] = {}
        self._handler_names: dict[str, list[str]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[Any] | None = None
        self._high_queue: asyncio.Queue[Any] | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._ready = threading.Event()
        self._stats = EventBusStats()
        self._stats_lock = threading.Lock()
        self._dlq: list[DeadLetterEvent] = []
        self._dlq_lock = threading.Lock()

        # Event journal (WAL)
        self._journal_path: Path | None = None
        if journal_path:
            self._journal_path = Path(journal_path)
            self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        self._journal_file: Any | None = None
        self._journal_lock = threading.Lock()

    def register_handler(self, event_type: str, handler: EventHandler, name: str = "") -> None:
        self._handlers.setdefault(event_type, []).append(handler)
        self._handler_names.setdefault(event_type, []).append(name or getattr(handler, "__name__", "?"))

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._ready.clear()
        self._open_journal()
        self._thread = threading.Thread(target=self._run_thread, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)
        info("Async event bus started", worker_count=self.worker_count)

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        loop = self._loop
        queue = self._queue
        high_queue = self._high_queue
        if loop and queue is not None:
            for _ in range(self.worker_count):
                asyncio.run_coroutine_threadsafe(queue.put(_STOP_SENTINEL), loop)
            if high_queue is not None:
                for _ in range(self.worker_count):
                    asyncio.run_coroutine_threadsafe(high_queue.put(_STOP_SENTINEL), loop)

        if self._thread:
            self._thread.join(timeout=5)

        self._close_journal()
        info("Async event bus stopped")

    def submit(self, event: Any) -> None:
        """Submit an event for background processing.
        Falls back to synchronous dispatch when the bus is not running.
        """
        self._journal_write(event)

        if not self._running:
            self._dispatch_sync(event)
            return

        loop = self._loop
        queue = self._queue
        high_queue = self._high_queue
        if loop is None or queue is None:
            self._dispatch_sync(event)
            return

        is_critical = getattr(event, "event_type", None) in _CRITICAL_EVENT_TYPES
        target = high_queue if is_critical and high_queue is not None else queue
        asyncio.run_coroutine_threadsafe(target.put(event), loop)
        with self._stats_lock:
            self._stats.queued += 1

    def emit(self, event_type: str, data: Any = None, source: str = "system") -> None:
        """Convenience API: build and submit an Event."""
        event = Event(event_type=event_type, data=data, source=source)
        self.submit(event)

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        if not self._running or self._loop is None or self._queue is None:
            return True

        async def _both_joined():
            await self._queue.join()
            if self._high_queue is not None:
                await self._high_queue.join()

        future = asyncio.run_coroutine_threadsafe(_both_joined(), self._loop)
        try:
            future.result(timeout=timeout)
            return True
        except Exception:
            return False

    def stats(self) -> EventBusStats:
        with self._stats_lock:
            return EventBusStats(
                queued=self._stats.queued,
                processed=self._stats.processed,
                failed=self._stats.failed,
                retried=self._stats.retried,
                dlq_count=len(self._dlq),
            )

    def dlq(self) -> list[DeadLetterEvent]:
        with self._dlq_lock:
            return list(self._dlq)

    def replay_dlq(self, max_events: int = 0) -> int:
        """Re-enqueue events from the dead-letter queue.
        Returns the number of events replayed.
        """
        with self._dlq_lock:
            to_replay = self._dlq[:]
            if max_events > 0:
                to_replay = to_replay[:max_events]
            self._dlq = self._dlq[len(to_replay):]

        for dl in to_replay:
            self.submit(dl.event)
        info(f"Replayed {len(to_replay)} events from DLQ")
        return len(to_replay)

    # ------------------------------------------------------------------
    # Journal (WAL)
    # ------------------------------------------------------------------

    def _open_journal(self) -> None:
        if self._journal_path is None:
            return
        try:
            self._journal_file = self._journal_path.open("a", encoding="utf-8")
        except Exception as e:
            warning(f"Failed to open event journal: {e}")

    def _close_journal(self) -> None:
        if self._journal_file is not None:
            try:
                self._journal_file.close()
            except Exception:
                pass
            self._journal_file = None

    def _journal_write(self, event: Any) -> None:
        if self._journal_file is None:
            return
        try:
            entry = {
                "ts": datetime.now(UTC).isoformat(),
                "event_type": getattr(event, "event_type", "?"),
                "data": _event_to_dict(event),
            }
            with self._journal_lock:
                self._journal_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
                self._journal_file.flush()
        except Exception as e:
            warning(f"Event journal write failed: {e}")

    # ------------------------------------------------------------------
    # Thread / async internals
    # ------------------------------------------------------------------

    def _run_thread(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._queue = asyncio.Queue(maxsize=self.queue_maxsize)
        self._high_queue = asyncio.Queue(maxsize=self.queue_maxsize)
        self._ready.set()

        try:
            loop.run_until_complete(self._run_workers())
        finally:
            try:
                pending = asyncio.all_tasks(loop=loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            finally:
                loop.close()
                self._loop = None
                self._queue = None
                self._high_queue = None

    async def _run_workers(self) -> None:
        workers = [asyncio.create_task(self._worker_loop(worker_index)) for worker_index in range(self.worker_count)]
        await asyncio.gather(*workers)

    async def _worker_loop(self, worker_index: int) -> None:
        assert self._queue is not None
        assert self._high_queue is not None
        while True:
            from_high = False
            event = None
            try:
                event = self._high_queue.get_nowait()
                from_high = True
            except asyncio.QueueEmpty:
                try:
                    event = await asyncio.wait_for(self._high_queue.get(), timeout=0.5)
                    from_high = True
                except TimeoutError:
                    event = await self._queue.get()
            if event is _STOP_SENTINEL:
                return
            try:
                await self._dispatch_with_retry(event, worker_index)
                with self._stats_lock:
                    self._stats.processed += 1
            except Exception as exc:
                self._send_to_dlq(event, str(exc))
                with self._stats_lock:
                    self._stats.failed += 1
                warning("Async event worker failed and sent to DLQ", worker=worker_index, error=str(exc))
            finally:
                if from_high:
                    self._high_queue.task_done()
                else:
                    self._queue.task_done()

    async def _dispatch_with_retry(self, event: Any, worker_index: int) -> None:
        last_exc: Exception | None = None
        for attempt in range(1 + self.max_retries):
            try:
                await self._dispatch_async(event, worker_index)
                return
            except Exception as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    with self._stats_lock:
                        self._stats.retried += 1
                    wait = self.retry_backoff * (2 ** attempt)
                    warning(
                        "Retrying event dispatch",
                        worker=worker_index,
                        attempt=attempt + 1,
                        max_retries=self.max_retries,
                        error=str(exc),
                        backoff=wait,
                    )
                    await asyncio.sleep(wait)
        if last_exc is not None:
            raise last_exc

    async def _dispatch_async(self, event: Any, worker_index: int) -> None:
        event_type = getattr(event, "event_type", None) or "*"
        handlers = list(self._handlers.get(event_type, [])) + list(self._handlers.get("*", []))

        if not handlers:
            debug("Async event bus had no handlers", worker=worker_index, event_type=event_type)
            return

        for handler in handlers:
            result = handler(event)
            if inspect.isawaitable(result):
                await result

    def _dispatch_sync(self, event: Any) -> None:
        event_type = getattr(event, "event_type", None) or "*"
        handlers = list(self._handlers.get(event_type, [])) + list(self._handlers.get("*", []))

        for handler in handlers:
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    asyncio.run(result)  # type: ignore[arg-type]
                with self._stats_lock:
                    self._stats.processed += 1
            except Exception as exc:
                self._send_to_dlq(event, str(exc))
                with self._stats_lock:
                    self._stats.failed += 1
                warning("Async event bus sync dispatch failed", error=str(exc), event_type=event_type)

    def _send_to_dlq(self, event: Any, error: str) -> None:
        dl_entry = DeadLetterEvent(
            event=event,
            error=str(error),
            retry_count=self.max_retries,
            last_attempt=datetime.now(UTC),
            event_type=getattr(event, "event_type", "?"),
        )
        with self._dlq_lock:
            self._dlq.append(dl_entry)
            self._stats.dlq_count = len(self._dlq)


_default_bus: AsyncEventBus | None = None


def get_event_bus(worker_count: int = 2) -> AsyncEventBus:
    """Return the process-wide default event bus (created lazily)."""
    global _default_bus
    if _default_bus is None:
        _default_bus = AsyncEventBus(worker_count=worker_count)
        _default_bus.start()
    return _default_bus
