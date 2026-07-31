"""
circuit_breaker.py - Circuit breaker pattern to prevent cascading failures
Implements state machine: CLOSED -> OPEN -> HALF_OPEN -> CLOSED
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .logger import error as log_error
from .logger import info, warning


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "CLOSED"           # Normal operation
    OPEN = "OPEN"               # Failing, reject new requests
    HALF_OPEN = "HALF_OPEN"     # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""

    failure_threshold: int = 5  # Failures before opening
    success_threshold: int = 2  # Successes to close when half-open
    timeout_seconds: int = 60   # Time before trying recovery
    window_seconds: int = 60    # Time window for counting failures
    max_requests: int = 100     # Max requests per window (optional rate limiting)

    def __post_init__(self):
        if self.failure_threshold <= 0:
            raise ValueError("failure_threshold must be > 0")
        if self.success_threshold <= 0:
            raise ValueError("success_threshold must be > 0")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if self.max_requests <= 0:
            raise ValueError("max_requests must be > 0")

    @property
    def rate_per_second(self) -> float:
        """Calculate request rate per second"""
        if self.window_seconds <= 0:
            return 0.0
        return self.max_requests / self.window_seconds


class CircuitBreaker:
    """Circuit breaker for a single endpoint/operation"""

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig,
    ):
        """
        Initialize circuit breaker
        
        Args:
            name: Name/identifier for this breaker (e.g., endpoint path)
            config: CircuitBreakerConfig instance
        """
        self.name = name
        self.config = config

        # State
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: float | None = None
        self.opened_at: float | None = None

        # Thread safety
        self.lock = threading.Lock()

    def call(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any
    ) -> Any:
        """
        Execute function through circuit breaker
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
        
        Returns:
            Result of func() if allowed
        
        Raises:
            CircuitBreakerOpen: If circuit is OPEN
            Any exception raised by func()
        """
        with self.lock:
            if self.state == CircuitState.OPEN:
                # Check if timeout has elapsed (try recovery)
                if self._should_attempt_recovery():
                    self.state = CircuitState.HALF_OPEN
                    self.success_count = 0
                    info(
                        "Circuit breaker entering HALF_OPEN state",
                        breaker=self.name,
                        timeout_seconds=self.config.timeout_seconds
                    )
                else:
                    elapsed = time.time() - self.opened_at
                    raise CircuitBreakerOpen(
                        f"Circuit breaker OPEN for {self.name} "
                        f"(opened {elapsed:.0f}s ago, retry in {self.config.timeout_seconds - elapsed:.0f}s)"
                    )

            # Attempt the call
            try:
                result = func(*args, **kwargs)
            except Exception:
                self._record_failure()
                raise
            else:
                self._record_success()
                return result

    def _should_attempt_recovery(self) -> bool:
        """Check if enough time has passed to try recovery"""
        if self.opened_at is None:
            return False

        elapsed = time.time() - self.opened_at
        return elapsed >= self.config.timeout_seconds

    def _record_failure(self) -> None:
        """Record a failure and potentially open circuit"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            # Failure while testing recovery -> back to OPEN
            self.state = CircuitState.OPEN
            self.opened_at = time.time()
            log_error(
                "Circuit breaker failure during recovery attempt",
                breaker=self.name,
                state="HALF_OPEN->OPEN"
            )
        elif self.state == CircuitState.CLOSED:
            # Check if we've exceeded failure threshold
            if self.failure_count >= self.config.failure_threshold:
                self.state = CircuitState.OPEN
                self.opened_at = time.time()
                warning(
                    "Circuit breaker OPENED (failure threshold exceeded)",
                    breaker=self.name,
                    failures=self.failure_count,
                    threshold=self.config.failure_threshold,
                    timeout_seconds=self.config.timeout_seconds
                )

    def _record_success(self) -> None:
        """Record a success and potentially close circuit"""
        self.failure_count = 0  # Reset failure counter on success

        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1

            if self.success_count >= self.config.success_threshold:
                # Recovered! Close circuit
                self.state = CircuitState.CLOSED
                self.success_count = 0
                self.opened_at = None
                info(
                    "Circuit breaker CLOSED (recovered)",
                    breaker=self.name,
                    successes=self.success_count,
                    threshold=self.config.success_threshold
                )
            else:
                info(
                    "Circuit breaker in HALF_OPEN (testing recovery)",
                    breaker=self.name,
                    successes=self.success_count,
                    threshold=self.config.success_threshold
                )

    def get_status(self) -> dict[str, Any]:
        """Get current circuit breaker status"""
        with self.lock:
            elapsed_since_failure = None
            if self.last_failure_time:
                elapsed_since_failure = time.time() - self.last_failure_time

            return {
                "name": self.name,
                "state": self.state.value,
                "failure_count": self.failure_count,
                "success_count": self.success_count,
                "last_failure_seconds_ago": elapsed_since_failure,
                "config": {
                    "failure_threshold": self.config.failure_threshold,
                    "success_threshold": self.config.success_threshold,
                    "timeout_seconds": self.config.timeout_seconds,
                }
            }


class CircuitBreakerOpen(Exception):
    """Exception raised when circuit is open"""
    pass


class EndpointCircuitBreaker:
    """Manager for multiple circuit breakers"""

    def __init__(self):
        """Initialize circuit breaker manager"""
        self.breakers: dict[str, CircuitBreaker] = {}
        self.lock = threading.Lock()

    def get_or_create(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None
    ) -> CircuitBreaker:
        """
        Get or create a circuit breaker
        
        Args:
            name: Breaker name/identifier
            config: CircuitBreakerConfig (uses default if None)
        
        Returns:
            CircuitBreaker instance
        """
        if config is None:
            config = CircuitBreakerConfig()

        with self.lock:
            if name not in self.breakers:
                self.breakers[name] = CircuitBreaker(name, config)
            return self.breakers[name]

    def call(
        self,
        name: str,
        func: Callable[..., Any],
        *args: Any,
        config: CircuitBreakerConfig | None = None,
        **kwargs: Any
    ) -> Any:
        """
        Execute function through circuit breaker
        
        Args:
            name: Breaker name
            func: Function to execute
            *args: Function arguments
            config: CircuitBreakerConfig (optional)
            **kwargs: Function keyword arguments
        
        Returns:
            Result of func()
        """
        breaker = self.get_or_create(name, config)
        return breaker.call(func, *args, **kwargs)

    def get_status(self) -> dict[str, dict]:
        """Get status of all breakers"""
        with self.lock:
            status = {}
            for name, breaker in self.breakers.items():
                status[name] = breaker.get_status()
            return status

    def reset_breaker(self, name: str) -> bool:
        """
        Manually reset a circuit breaker
        
        Args:
            name: Breaker name
        
        Returns:
            True if reset, False if not found
        """
        with self.lock:
            if name in self.breakers:
                self.breakers[name].state = CircuitState.CLOSED
                self.breakers[name].failure_count = 0
                self.breakers[name].success_count = 0
                self.breakers[name].opened_at = None
                info("Circuit breaker manually reset", breaker=name)
                return True
            return False


# Default circuit breaker manager instance
_default_breaker_manager = EndpointCircuitBreaker()


# Shopee API circuit breaker configs (conservative)
SHOPEE_CIRCUIT_CONFIGS = {
    # Product endpoints
    "/api/v2/product/get_item_list": CircuitBreakerConfig(
        failure_threshold=3, success_threshold=2, timeout_seconds=30
    ),
    "/api/v2/product/get_item_detail": CircuitBreakerConfig(
        failure_threshold=3, success_threshold=2, timeout_seconds=30
    ),

    # Auth endpoints (stricter - only 2 failures before opening)
    "/api/v2/auth/token/get": CircuitBreakerConfig(
        failure_threshold=2, success_threshold=1, timeout_seconds=60
    ),
    "/api/v2/auth/access_token/get": CircuitBreakerConfig(
        failure_threshold=2, success_threshold=1, timeout_seconds=60
    ),

    # MediaSpace endpoints
    "/api/v2/media_space/upload_video_part": CircuitBreakerConfig(
        failure_threshold=5, success_threshold=2, timeout_seconds=45
    ),
}


def initialize_default_circuit_breakers() -> None:
    """Initialize default Shopee circuit breakers"""
    for endpoint, config in SHOPEE_CIRCUIT_CONFIGS.items():
        _default_breaker_manager.get_or_create(endpoint, config)


def get_circuit_breaker_manager() -> EndpointCircuitBreaker:
    """Get the default circuit breaker manager"""
    return _default_breaker_manager
