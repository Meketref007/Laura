"""
test_retry.py - Tests for retry logic with exponential backoff
"""

import pytest
import time
from shopee_agent.retry import (
    RetryConfig,
    retry,
    RETRY_NETWORK,
    RETRY_API_TRANSIENT,
)


class TestRetryConfig:
    """Tests for RetryConfig"""
    
    def test_get_delay_increases_exponentially(self):
        """Verify delay increases exponentially"""
        config = RetryConfig(
            initial_delay_ms=100,
            max_delay_ms=5000,
            backoff_factor=2.0,
            jitter=False,  # Disable jitter for deterministic testing
        )
        
        delay_0 = config.get_delay(0)  # 100ms = 0.1s
        delay_1 = config.get_delay(1)  # 200ms = 0.2s
        delay_2 = config.get_delay(2)  # 400ms = 0.4s
        
        assert 0.09 < delay_0 < 0.11  # ~0.1s
        assert 0.19 < delay_1 < 0.21  # ~0.2s
        assert 0.39 < delay_2 < 0.41  # ~0.4s
    
    def test_get_delay_respects_max_delay(self):
        """Verify delay doesn't exceed max_delay_ms"""
        config = RetryConfig(
            initial_delay_ms=100,
            max_delay_ms=500,
            backoff_factor=2.0,
            jitter=False,
        )
        
        delay = config.get_delay(10)  # Would be 100 * 2^10 = 102400ms
        assert delay <= 0.5  # Max delay is 500ms = 0.5s
    
    def test_jitter_adds_randomness(self):
        """Verify jitter adds randomness to delay"""
        config = RetryConfig(
            initial_delay_ms=100,
            max_delay_ms=5000,
            backoff_factor=2.0,
            jitter=True,
        )
        
        delays = [config.get_delay(0) for _ in range(10)]
        # With jitter, delays should vary (not all identical)
        assert len(set(str(d)[:5] for d in delays)) > 1


class TestRetryDecorator:
    """Tests for retry decorator"""
    
    def test_succeeds_on_first_attempt(self):
        """Verify immediate success doesn't retry"""
        config = RetryConfig(max_attempts=3, jitter=False)
        call_count = 0
        
        @retry(config=config, context="test")
        def successful_function():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = successful_function()
        assert result == "success"
        assert call_count == 1  # Should only be called once
    
    def test_retries_on_failure(self):
        """Verify retry happens on exception"""
        config = RetryConfig(
            max_attempts=3,
            initial_delay_ms=10,
            jitter=False,
        )
        call_count = 0
        
        @retry(config=config, context="test")
        def failing_then_succeeding():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("First attempt fails")
            return "success"
        
        result = failing_then_succeeding()
        assert result == "success"
        assert call_count == 2  # Called once (failed) + once (succeeded)
    
    def test_exhausts_attempts_and_raises(self):
        """Verify exception raised after max attempts"""
        config = RetryConfig(
            max_attempts=2,
            initial_delay_ms=10,
            jitter=False,
        )
        call_count = 0
        
        @retry(config=config, context="test")
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ValueError("Always fails")
        
        with pytest.raises(ValueError, match="Always fails"):
            always_fails()
        
        assert call_count == 2  # Should try max_attempts times
    
    def test_only_retries_specified_exceptions(self):
        """Verify only specified exceptions trigger retry"""
        config = RetryConfig(
            max_attempts=3,
            retryable_exceptions=(ConnectionError,),  # Only retry ConnectionError
        )
        call_count = 0
        
        @retry(config=config, context="test")
        def raises_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("Not retryable")
        
        with pytest.raises(ValueError):
            raises_value_error()
        
        assert call_count == 1  # Should not retry ValueError


class TestRetryPresets:
    """Tests for preset configurations"""
    
    def test_retry_network_config(self):
        """Verify RETRY_NETWORK configuration"""
        assert RETRY_NETWORK.max_attempts == 3
        assert RETRY_NETWORK.initial_delay_ms == 50
        assert RETRY_NETWORK.max_delay_ms == 1000
        assert ConnectionError in RETRY_NETWORK.retryable_exceptions
    
    def test_retry_api_transient_config(self):
        """Verify RETRY_API_TRANSIENT configuration"""
        assert RETRY_API_TRANSIENT.max_attempts == 4
        assert RETRY_API_TRANSIENT.initial_delay_ms == 100
        assert RETRY_API_TRANSIENT.max_delay_ms == 2000


class TestRetryIntegration:
    """Integration tests for retry"""
    
    def test_retry_with_timing(self):
        """Verify backoff delay actually happens"""
        config = RetryConfig(
            max_attempts=2,
            initial_delay_ms=50,  # 50ms delay
            jitter=False,
        )
        call_times = []
        
        @retry(config=config, context="test")
        def track_timing():
            call_times.append(time.time())
            if len(call_times) < 2:
                raise ValueError("Retry me")
            return "success"
        
        result = track_timing()
        assert result == "success"
        assert len(call_times) == 2
        
        # Verify delay between calls (should be at least 50ms = 0.05s)
        time_diff = call_times[1] - call_times[0]
        assert time_diff >= 0.04  # Allow some tolerance
