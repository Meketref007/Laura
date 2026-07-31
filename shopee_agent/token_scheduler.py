"""
token_scheduler.py - Background scheduler for automatic token refresh
"""

import threading
from collections.abc import Callable

from shopee_agent.logger import debug, error, info, warning
from shopee_agent.secrets_rotation import (
    get_rotation_manager,
)


class TokenRefreshScheduler:
    """
    Schedules and executes automatic token refreshes.
    
    Features:
    - Periodic checking for expiring tokens
    - Callback-based refresh execution
    - Failed refresh retry logic
    - Thread-safe operation
    """

    DEFAULT_CHECK_INTERVAL_SECONDS = 3600  # 1 hour
    INITIAL_BACKOFF_SECONDS = 300  # 5 minutes
    MAX_BACKOFF_SECONDS = 3600  # 1 hour

    def __init__(
        self,
        check_interval_seconds: int = DEFAULT_CHECK_INTERVAL_SECONDS
    ):
        self.check_interval_seconds = check_interval_seconds
        self._scheduler_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._refresh_callbacks: dict[str, Callable] = {}
        self._backoff_counters: dict[str, int] = {}
        self.manager = get_rotation_manager()

        info("Token refresh scheduler initialized", check_interval_seconds=check_interval_seconds)

    def register_refresh_callback(
        self,
        token_name: str,
        callback: Callable[[str], bool]
    ) -> None:
        """
        Register a callback function for token refresh.
        
        Callback signature:
            callback(token_name: str) -> bool
                Returns True on success, False on failure
        
        Args:
            token_name: Token identifier (e.g., "SHOPEE_DEFAULT_ACCESS_TOKEN")
            callback: Async refresh function
        """
        with self._lock:
            self._refresh_callbacks[token_name] = callback
            info(f"Refresh callback registered: {token_name}")

    def start(self) -> None:
        """Start the scheduling thread"""
        with self._lock:
            if self._scheduler_thread and self._scheduler_thread.is_alive():
                warning("Scheduler already running")
                return

            self._stop_event.clear()
            self._scheduler_thread = threading.Thread(
                target=self._scheduler_loop,
                daemon=True
            )
            self._scheduler_thread.start()
            info("Token refresh scheduler started")

    def stop(self) -> None:
        """Stop the scheduling thread"""
        self._stop_event.set()

        with self._lock:
            if self._scheduler_thread and self._scheduler_thread.is_alive():
                self._scheduler_thread.join(timeout=5)

        info("Token refresh scheduler stopped")

    def force_refresh(self, token_name: str) -> bool:
        """Manually trigger token refresh"""
        return self._execute_refresh(token_name)

    def _scheduler_loop(self) -> None:
        """Main scheduler loop"""
        while not self._stop_event.is_set():
            try:
                # Check for tokens needing refresh
                tokens_to_refresh = self.manager.get_tokens_requiring_refresh()

                for token_name in tokens_to_refresh:
                    # Check if we should retry this token
                    backoff = self._get_backoff(token_name)
                    if backoff > 0:
                        debug(f"Backoff active for {token_name}, retrying in {backoff}s")
                        continue

                    self._execute_refresh(token_name)

                # Wait for next check
                self._stop_event.wait(self.check_interval_seconds)

            except Exception as e:
                error("Error in scheduler loop",
                    error=str(e)
                )
                self._stop_event.wait(60)  # Brief pause on error

    def _execute_refresh(self, token_name: str) -> bool:
        """Execute token refresh via callback"""
        with self._lock:
            if token_name not in self._refresh_callbacks:
                warning(f"No refresh callback for {token_name}")
                return False

            callback = self._refresh_callbacks[token_name]

        try:
            info(f"Executing token refresh: {token_name}")

            # Mark as refreshing if token is tracked in manager
            if token_name in self.manager._metadata:
                self.manager._metadata[token_name].status = "refreshing"

            # Execute callback
            success = callback(token_name)

            if success:
                self.manager.record_refresh_attempt(token_name, success=True)
                self._clear_backoff(token_name)
                info(f"Token refresh succeeded: {token_name}")
                return True
            else:
                self.manager.record_refresh_attempt(token_name, success=False)
                self._increase_backoff(token_name)
                warning(f"Token refresh failed: {token_name}")
                return False

        except Exception as e:
            error(f"Error refreshing token: {token_name}",
                error=str(e)
            )
            self.manager.record_refresh_attempt(token_name, success=False, error=str(e))
            self._increase_backoff(token_name)
            return False

    def _get_backoff(self, token_name: str) -> int:
        """Get remaining backoff time in seconds"""
        with self._lock:
            if token_name not in self._backoff_counters:
                return 0

            backoff = self._backoff_counters[token_name]
            if backoff > 0:
                self._backoff_counters[token_name] = max(0, backoff - self.check_interval_seconds)
                return backoff

            return 0

    def _increase_backoff(self, token_name: str) -> None:
        """Increase backoff time for failed refresh"""
        with self._lock:
            current_backoff = self._backoff_counters.get(token_name, 0)

            if current_backoff == 0:
                new_backoff = self.INITIAL_BACKOFF_SECONDS
            else:
                new_backoff = min(
                    current_backoff * 2,
                    self.MAX_BACKOFF_SECONDS
                )

            self._backoff_counters[token_name] = new_backoff
            info(f"Increased backoff for {token_name}",
                backoff_seconds=new_backoff
            )

    def _clear_backoff(self, token_name: str) -> None:
        """Clear backoff for token after successful refresh"""
        with self._lock:
            self._backoff_counters[token_name] = 0


# Global instance
_scheduler: TokenRefreshScheduler | None = None


def initialize_scheduler(
    check_interval_seconds: int = TokenRefreshScheduler.DEFAULT_CHECK_INTERVAL_SECONDS
) -> TokenRefreshScheduler:
    """Initialize global scheduler"""
    global _scheduler

    if _scheduler is None:
        _scheduler = TokenRefreshScheduler(check_interval_seconds=check_interval_seconds)

    return _scheduler


def get_scheduler() -> TokenRefreshScheduler:
    """Get global scheduler"""
    global _scheduler

    if _scheduler is None:
        _scheduler = TokenRefreshScheduler()

    return _scheduler
