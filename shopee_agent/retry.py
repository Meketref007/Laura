"""
retry.py - Retry logic with exponential backoff and jitter
Provides reusable decorators for resilient API calls
"""

from __future__ import annotations

import functools
import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

from .logger import debug, warning
from .logger import error as log_error

T = TypeVar("T")


class RetryConfig:
    """Configuration for retry behavior"""

    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay_ms: int = 100,
        max_delay_ms: int = 5000,
        backoff_factor: float = 2.0,
        jitter: bool = True,
        retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    ) -> None:
        """
        Args:
            max_attempts: Maximum number of attempts
            initial_delay_ms: Initial delay in milliseconds
            max_delay_ms: Maximum delay in milliseconds
            backoff_factor: Multiplicative factor for backoff
            jitter: Whether to add randomness to delay
            retryable_exceptions: Which exceptions to retry on
        """
        self.max_attempts = max_attempts
        self.initial_delay_ms = initial_delay_ms
        self.max_delay_ms = max_delay_ms
        self.backoff_factor = backoff_factor
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt (0-indexed)"""
        delay_ms = min(
            self.initial_delay_ms * (self.backoff_factor ** attempt),
            self.max_delay_ms
        )

        if self.jitter:
            # Add 0-100% random jitter
            jitter_ms = random.uniform(0, delay_ms * 0.1)
            delay_ms += jitter_ms

        return delay_ms / 1000.0  # Convert to seconds


DEFAULT_RETRY_CONFIG = RetryConfig(
    max_attempts=3,
    initial_delay_ms=100,
    max_delay_ms=5000,
    backoff_factor=2.0,
    jitter=True,
    retryable_exceptions=(Exception,),
)


def retry(
    config: RetryConfig | None = None,
    context: str = "",
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to retry a function with exponential backoff.
    
    Args:
        config: RetryConfig instance (uses default if None)
        context: Context string for logging (e.g., "Shopee API call")
    
    Example:
        @retry(context="Fetch products")
        def get_products(shop_id: int) -> dict:
            ...
    """
    if config is None:
        config = DEFAULT_RETRY_CONFIG

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Exception | None = None

            for attempt in range(config.max_attempts):
                try:
                    if attempt > 0:
                        debug(
                            f"Retry attempt {attempt + 1}/{config.max_attempts}",
                            function=func.__name__,
                            context=context,
                        )

                    result = func(*args, **kwargs)

                    if attempt > 0:
                        debug(
                            f"Succeeded after {attempt + 1} attempts",
                            function=func.__name__,
                            context=context,
                        )

                    return result

                except config.retryable_exceptions as exc:
                    last_exception = exc

                    if attempt < config.max_attempts - 1:
                        delay = config.get_delay(attempt)
                        warning(
                            f"Attempt {attempt + 1} failed, retrying in {delay:.2f}s",
                            function=func.__name__,
                            context=context,
                            error=str(exc)[:100],
                            delay_seconds=delay,
                        )
                        time.sleep(delay)
                    else:
                        log_error(
                            f"All {config.max_attempts} attempts failed",
                            function=func.__name__,
                            context=context,
                            error=str(exc)[:200],
                        )

            # All attempts exhausted
            if last_exception:
                raise last_exception
            raise RuntimeError(f"Unexpected error in retry logic for {func.__name__}")

        return wrapper

    return decorator


# Preset configurations for common scenarios

RETRY_NETWORK = RetryConfig(
    max_attempts=3,
    initial_delay_ms=50,
    max_delay_ms=1000,
    backoff_factor=2.0,
    jitter=True,
    retryable_exceptions=(
        ConnectionError,
        TimeoutError,
        OSError,
    ),
)

RETRY_API_TRANSIENT = RetryConfig(
    max_attempts=4,
    initial_delay_ms=100,
    max_delay_ms=2000,
    backoff_factor=2.0,
    jitter=True,
    retryable_exceptions=(Exception,),  # Catch all for API
)

RETRY_CRITICAL = RetryConfig(
    max_attempts=5,
    initial_delay_ms=200,
    max_delay_ms=5000,
    backoff_factor=2.5,
    jitter=True,
    retryable_exceptions=(Exception,),
)
