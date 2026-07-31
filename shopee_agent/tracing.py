"""Distributed tracing for Laura — context propagation, span tracking, event emission."""

from __future__ import annotations

import functools
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from shopee_agent.logger import debug

# ── TraceContext ──────────────────────────────────────────────────────────────

@dataclass
class TraceContext:
    """A single span in a distributed trace."""

    correlation_id: str = ""
    span_id: str = ""
    parent_span_id: str = ""
    endpoint: str = ""
    operation: str = ""
    start_time: float = 0.0
    end_time: float | None = None
    status_code: int | None = None
    error: str | None = None
    tags: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.span_id:
            self.span_id = uuid.uuid4().hex[:12]
        if not self.correlation_id:
            self.correlation_id = uuid.uuid4().hex[:12]
        if not self.start_time:
            self.start_time = time.time()

    def record_success(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.end_time = time.time()

    def record_error(self, error: str) -> None:
        self.error = error
        self.end_time = time.time()

    def elapsed_ms(self) -> float:
        end = self.end_time or time.time()
        return round((end - self.start_time) * 1000, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "endpoint": self.endpoint,
            "operation": self.operation,
            "start_time": datetime.fromtimestamp(self.start_time, tz=UTC).isoformat(),
            "end_time": datetime.fromtimestamp(self.end_time, tz=UTC).isoformat() if self.end_time else None,
            "status_code": self.status_code,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms(),
        }


# ── DistributedTracer ────────────────────────────────────────────────────────

class DistributedTracer:
    """Manages active spans and emits trace events."""

    def __init__(self, event_bus: Any | None = None):
        self._lock = threading.Lock()
        self._active_spans: dict[str, TraceContext] = {}
        self._event_bus = event_bus

    def set_bus(self, event_bus: Any) -> None:
        self._event_bus = event_bus

    def start_trace(
        self,
        endpoint: str = "",
        operation: str = "",
        parent_context: TraceContext | None = None,
    ) -> TraceContext:
        ctx = TraceContext(
            correlation_id=parent_context.correlation_id if parent_context else "",
            parent_span_id=parent_context.span_id if parent_context else "",
            endpoint=endpoint,
            operation=operation,
        )
        with self._lock:
            self._active_spans[ctx.span_id] = ctx
        return ctx

    def start_child_span(
        self,
        parent_context: TraceContext,
        operation: str = "",
        endpoint: str = "",
    ) -> TraceContext:
        return self.start_trace(endpoint=endpoint, operation=operation, parent_context=parent_context)

    def end_span(
        self,
        context: TraceContext,
        status_code: int | None = None,
        error: str | None = None,
    ) -> None:
        if error:
            context.record_error(error)
        else:
            context.record_success(status_code or 200)
        with self._lock:
            self._active_spans.pop(context.span_id, None)
        debug(f"Trace {context.operation}: {context.elapsed_ms()}ms {'error' if error else 'ok'}")
        self._emit_event(context)
        _trace_store.add(context)

    def get_span_count(self) -> int:
        with self._lock:
            return len(self._active_spans)

    def get_active_spans(self) -> list[TraceContext]:
        with self._lock:
            return list(self._active_spans.values())

    def get_current_correlation_id(self) -> str:
        with self._lock:
            for ctx in self._active_spans.values():
                if ctx.correlation_id:
                    return ctx.correlation_id
        return uuid.uuid4().hex[:12]

    def _emit_event(self, context: TraceContext) -> None:
        bus = self._event_bus
        if bus is None:
            return
        try:
            from shopee_agent.event_bus import MetricUpdateEvent
            bus.submit(MetricUpdateEvent(
                event_type="metric.update",
                metrics={
                    f"trace.{context.operation}.elapsed_ms": context.elapsed_ms(),
                    f"trace.{context.operation}.status": 1 if context.error is None else 0,
                },
            ))
        except Exception:
            pass


# ── Lightweight span tracer (complementary) ──────────────────────────────────

class SpanTracer:
    """Lightweight span-based tracer that wraps DistributedTracer."""

    def __init__(self, tracer: DistributedTracer):
        self._tracer = tracer
        self._current_span_id: str | None = None

    def start_span(self, name: str, tags: dict[str, Any] | None = None) -> str:
        parent = None
        if self._current_span_id:
            with self._tracer._lock:
                parent = self._tracer._active_spans.get(self._current_span_id)
        ctx = self._tracer.start_trace(operation=name, parent_context=parent)
        if tags:
            ctx.tags.update(tags)
        self._current_span_id = ctx.span_id
        return ctx.span_id

    def end_span(self, span_id: str, status: str = "ok") -> None:
        with self._tracer._lock:
            ctx = self._tracer._active_spans.get(span_id)
        if ctx is None:
            return
        err = None if status == "ok" else status
        self._tracer.end_span(ctx, error=err)
        if self._current_span_id == span_id:
            self._current_span_id = ctx.parent_span_id or None

    def span(self, name: str, tags: dict[str, Any] | None = None) -> Callable:
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                sid = self.start_span(name, tags=tags)
                try:
                    result = func(*args, **kwargs)
                    self.end_span(sid, status="ok")
                    return result
                except Exception as exc:
                    self.end_span(sid, status=str(exc))
                    raise
            return wrapper
        return decorator


# ── Global singleton ─────────────────────────────────────────────────────────

_default_tracer = DistributedTracer()
_span_tracer = SpanTracer(_default_tracer)
_thread_local = threading.local()


class TraceStore:
    """In-memory store of completed spans for CLI inspection."""

    def __init__(self, maxlen: int = 500):
        self._spans: list[dict[str, Any]] = []
        self._maxlen = maxlen
        self._lock = threading.Lock()

    def add(self, ctx: TraceContext) -> None:
        d = ctx.to_dict()
        d["ok"] = ctx.error is None
        d["name"] = d.get("operation", "")
        d["duration_ms"] = d.get("elapsed_ms", 0.0)
        d["timestamp"] = d.get("start_time", "")
        with self._lock:
            self._spans.append(d)
            if len(self._spans) > self._maxlen:
                self._spans = self._spans[-self._maxlen:]

    def get_recent(self, n: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._spans[-n:])


_trace_store = TraceStore()


def get_trace_store() -> TraceStore:
    return _trace_store


def get_tracer() -> DistributedTracer:
    return _default_tracer


def get_correlation_id() -> str:
    if not hasattr(_thread_local, "correlation_id") or not _thread_local.correlation_id:
        _thread_local.correlation_id = _default_tracer.get_current_correlation_id()
    return _thread_local.correlation_id


def create_trace(
    endpoint: str = "",
    operation: str = "",
    parent_context: TraceContext | None = None,
) -> TraceContext:
    return _default_tracer.start_trace(endpoint=endpoint, operation=operation, parent_context=parent_context)


def get_trace_headers() -> dict[str, str]:
    cid = get_correlation_id()
    headers = {
        "X-Correlation-ID": cid,
        "X-Request-ID": cid,
    }
    sid = _span_tracer._current_span_id
    if sid:
        headers["X-Span-ID"] = sid
    return headers


def trace(name: str, tags: dict[str, Any] | None = None) -> Callable:
    """Decorator that traces a function with a span."""
    return _span_tracer.span(name, tags=tags)
