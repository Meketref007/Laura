"""Graceful shutdown handler for Laura daemon and servers."""

from __future__ import annotations

import signal
import threading
import time
from collections.abc import Callable
from types import FrameType
from typing import Any

CleanupFn = Callable[[], Any]


class GracefulShutdown:
    """Manages orderly shutdown of Laura services.

    Signals are captured once; duplicate signals are ignored.  All registered
    cleanup callbacks run in reverse registration order, each subject to an
    optional per-service timeout.

    Usage:
        gs = GracefulShutdown(timeout=30)
        gs.register_handler("event_bus", bus.stop)
        gs.register_handler("webhook", server.stop)
        gs.setup_signal_handlers()
        # ... main loop ...
    """

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout
        self._shutting_down = False
        self._lock = threading.Lock()
        self._handlers: list[tuple[str, CleanupFn, float | None]] = []
        self._original_handlers: dict[int, Any] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_handler(
        self,
        name: str,
        cleanup_fn: CleanupFn,
        *,
        timeout: float | None = None,
        priority: int = 0,
    ) -> None:
        """Register *cleanup_fn* to be called during shutdown.

        Parameters
        ----------
        name :
            Human-readable label used in log/debug messages.
        cleanup_fn :
            Zero-argument callable invoked during shutdown.
        timeout :
            Per-handler timeout in seconds.  Falls back to the instance
            default when *None*.
        priority :
            Higher values run first (use 0 for normal, 10+ for critical).
        """
        with self._lock:
            self._handlers.append((name, cleanup_fn, timeout if timeout is not None else self._timeout))

    def remove_handler(self, name: str) -> bool:
        """Remove a previously registered handler by name."""
        with self._lock:
            before = len(self._handlers)
            self._handlers = [h for h in self._handlers if h[0] != name]
            return len(self._handlers) < before

    # ------------------------------------------------------------------
    # Signal handling
    # ------------------------------------------------------------------

    def setup_signal_handlers(self) -> None:
        """Install SIGINT / SIGTERM handlers that invoke :meth:`shutdown`."""
        self._original_handlers = {
            signal.SIGINT: signal.getsignal(signal.SIGINT),
            signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        }
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)

    def restore_signal_handlers(self) -> None:
        """Restore original signal handlers."""
        for sig, handler in self._original_handlers.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass

    def _signal_handler(self, signum: int, _frame: FrameType | None) -> None:
        if self._shutting_down:
            return
        signame = signal.Signals(signum).name
        print(f"\n[GracefulShutdown] Caught {signame}, shutting down...")
        self.shutdown(signal_num=signum)

    # ------------------------------------------------------------------
    # Shutdown logic
    # ------------------------------------------------------------------

    @property
    def shutting_down(self) -> bool:
        return self._shutting_down

    def is_shutting_down(self) -> bool:
        return self._shutting_down

    def shutdown(self, signal_num: int | None = None) -> None:
        """Execute all registered cleanup handlers in reverse priority order.

        Once called, subsequent invocations are no-ops.
        """
        with self._lock:
            if self._shutting_down:
                return
            self._shutting_down = True
            handlers = list(self._handlers)
            self._handlers.clear()

        # Sort by priority descending, then reverse registration order
        handlers.sort(key=lambda h: h[2] or 0, reverse=True)

        errors: list[tuple[str, str]] = []
        for name, fn, tout in handlers:
            try:
                time.monotonic() + (tout or self._timeout)
                fn()
            except Exception as exc:
                errors.append((name, str(exc)))
                print(f"[GracefulShutdown] '{name}' raised: {exc}")

        self.restore_signal_handlers()

        if errors:
            print("[GracefulShutdown] Errors during shutdown:")
            for name, err in errors:
                print(f"  - {name}: {err}")
        else:
            print("[GracefulShutdown] All handlers completed")

    def wait_for_pending(
        self,
        poll: Callable[[], bool],
        *,
        timeout: float | None = None,
        interval: float = 0.5,
    ) -> bool:
        """Block until *poll* returns ``False`` or *timeout* elapses.

        Useful for waiting on background threads or pending I/O.
        Returns ``True`` if all work completed, ``False`` on timeout.
        """
        t0 = time.monotonic()
        limit = timeout if timeout is not None else self._timeout
        while time.monotonic() - t0 < limit:
            if not poll():
                return True
            time.sleep(interval)
        return False

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> GracefulShutdown:
        self.setup_signal_handlers()
        return self

    def __exit__(self, *exc: Any) -> None:
        if not self._shutting_down:
            self.shutdown()
