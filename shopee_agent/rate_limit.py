"""
rate_limit.py - Rate limiting with token bucket algorithm
Prevents API throttling and respects rate limits per endpoint
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .logger import debug, warning


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting"""
    max_requests: int  # Max requests in the window
    window_seconds: int  # Time window in seconds

    @property
    def rate_per_second(self) -> float:
        """Calculate rate in requests per second"""
        return self.max_requests / self.window_seconds


class TokenBucket:
    """Token bucket for rate limiting"""

    def __init__(self, config: RateLimitConfig) -> None:
        """
        Initialize token bucket
        
        Args:
            config: RateLimitConfig with max_requests and window_seconds
        """
        self.config = config
        self.tokens = float(config.max_requests)  # Start with full bucket
        self.last_refill = time.time()
        self.lock = threading.Lock()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time"""
        now = time.time()
        elapsed = now - self.last_refill

        # Calculate tokens to add: elapsed_time * rate
        rate = self.config.rate_per_second
        tokens_to_add = elapsed * rate

        self.tokens = min(
            self.config.max_requests,  # Cap at max
            self.tokens + tokens_to_add
        )
        self.last_refill = now

    def consume(self, tokens: int = 1) -> bool:
        """
        Try to consume tokens
        
        Args:
            tokens: Number of tokens to consume (default 1)
        
        Returns:
            True if tokens were available and consumed, False otherwise
        """
        with self.lock:
            self._refill()

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def wait_and_consume(self, tokens: int = 1, timeout_seconds: float | None = None) -> bool:
        """
        Wait for tokens to become available, then consume
        
        Args:
            tokens: Number of tokens to consume
            timeout_seconds: Max time to wait (None = no timeout)
        
        Returns:
            True if tokens were consumed, False if timeout
        """
        start_time = time.time()

        while True:
            if self.consume(tokens):
                return True

            if timeout_seconds is not None:
                elapsed = time.time() - start_time
                if elapsed >= timeout_seconds:
                    return False

            # Sleep a tiny bit before retrying
            time.sleep(0.01)

    def get_status(self) -> dict[str, float]:
        """Get current bucket status"""
        with self.lock:
            self._refill()
            return {
                "tokens_available": self.tokens,
                "tokens_max": self.config.max_requests,
                "fill_percentage": (self.tokens / self.config.max_requests) * 100,
            }


class EndpointRateLimiter:
    """Rate limiter for multiple endpoints"""

    def __init__(self) -> None:
        """Initialize endpoint rate limiter"""
        self.buckets: dict[str, TokenBucket] = {}
        self.configs: dict[str, RateLimitConfig] = {}
        self.lock = threading.Lock()

    def set_limit(self, endpoint: str, config: RateLimitConfig) -> None:
        """
        Set rate limit for an endpoint
        
        Args:
            endpoint: Endpoint path (e.g., "/api/v2/product/get_item_list")
            config: RateLimitConfig with limits
        """
        with self.lock:
            self.configs[endpoint] = config
            self.buckets[endpoint] = TokenBucket(config)
            debug(
                "Rate limit configured",
                endpoint=endpoint,
                max_requests=config.max_requests,
                window_seconds=config.window_seconds,
            )

    def consume(self, endpoint: str, tokens: int = 1) -> bool:
        """
        Try to consume tokens for an endpoint
        
        Args:
            endpoint: Endpoint path
            tokens: Number of tokens to consume
        
        Returns:
            True if allowed, False if rate limited
        """
        with self.lock:
            if endpoint not in self.buckets:
                # No limit set for this endpoint
                return True

            bucket = self.buckets[endpoint]

        return bucket.consume(tokens)

    def wait_and_consume(
        self,
        endpoint: str,
        tokens: int = 1,
        timeout_seconds: float | None = None
    ) -> bool:
        """
        Wait for tokens and consume them
        
        Args:
            endpoint: Endpoint path
            tokens: Number of tokens to consume
            timeout_seconds: Max time to wait
        
        Returns:
            True if consumed, False if timeout or rate limited
        """
        with self.lock:
            if endpoint not in self.buckets:
                # No limit set for this endpoint
                return True

            bucket = self.buckets[endpoint]

        if bucket.wait_and_consume(tokens, timeout_seconds):
            return True

        warning(
            "Rate limit exceeded",
            endpoint=endpoint,
            tokens_requested=tokens,
            timeout_seconds=timeout_seconds,
        )
        return False

    def get_status(self) -> dict[str, dict[str, float]]:
        """Get status of all endpoints"""
        with self.lock:
            status = {}
            for endpoint, bucket in self.buckets.items():
                status[endpoint] = bucket.get_status()
            return status


# Default rate limiter instance
_default_limiter = EndpointRateLimiter()


# Shopee API rate limits (conservative estimates)
SHOPEE_RATE_LIMITS = {
    # Product endpoints
    "/api/v2/product/get_item_list": RateLimitConfig(max_requests=100, window_seconds=60),
    "/api/v2/product/get_item_detail": RateLimitConfig(max_requests=100, window_seconds=60),
    "/api/v2/product/get_item_base_info": RateLimitConfig(max_requests=100, window_seconds=60),
    "/api/v2/product/get_item_variations": RateLimitConfig(max_requests=100, window_seconds=60),

    # Order endpoints
    "/api/v2/order/get_order_list": RateLimitConfig(max_requests=100, window_seconds=60),
    "/api/v2/order/get_order_detail": RateLimitConfig(max_requests=100, window_seconds=60),

    # Logistics endpoints
    "/api/v2/logistics/get_channel_list": RateLimitConfig(max_requests=50, window_seconds=60),
    "/api/v2/logistics/get_logistics_info": RateLimitConfig(max_requests=50, window_seconds=60),
    "/api/v2/logistics/get_tracking_number": RateLimitConfig(max_requests=50, window_seconds=60),

    # Auth endpoints (conservative)
    "/api/v2/auth/token/get": RateLimitConfig(max_requests=10, window_seconds=60),
    "/api/v2/auth/access_token/get": RateLimitConfig(max_requests=10, window_seconds=60),

    # MediaSpace (video uploads are slower)
    "/api/v2/media_space/init_video_upload": RateLimitConfig(max_requests=20, window_seconds=60),
    "/api/v2/media_space/upload_video_part": RateLimitConfig(max_requests=50, window_seconds=60),
    "/api/v2/media_space/complete_video_upload": RateLimitConfig(max_requests=20, window_seconds=60),
}


def initialize_default_limits() -> None:
    """Initialize default Shopee rate limits"""
    for endpoint, config in SHOPEE_RATE_LIMITS.items():
        _default_limiter.set_limit(endpoint, config)


def get_limiter() -> EndpointRateLimiter:
    """Get the default rate limiter instance"""
    return _default_limiter


def check_rate_limit(endpoint: str) -> bool:
    """
    Check if request is allowed for endpoint
    
    Args:
        endpoint: API endpoint path
    
    Returns:
        True if allowed, False if rate limited
    """
    return _default_limiter.consume(endpoint)


def wait_for_rate_limit(
    endpoint: str,
    timeout_seconds: float = 10.0
) -> bool:
    """
    Wait for rate limit to allow request
    
    Args:
        endpoint: API endpoint path
        timeout_seconds: Max time to wait
    
    Returns:
        True if allowed within timeout, False if timeout
    """
    return _default_limiter.wait_and_consume(endpoint, timeout_seconds=timeout_seconds)
