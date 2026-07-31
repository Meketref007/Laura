"""
test_circuit_breaker.py - Tests for circuit breaker pattern
"""

import pytest
import time
from shopee_agent.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpen,
    CircuitState,
    EndpointCircuitBreaker,
)


class TestCircuitBreakerConfig:
    """Tests for CircuitBreakerConfig"""
    
    def test_config_creation(self):
        """Verify config creation with defaults"""
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 5
        assert config.success_threshold == 2
        assert config.timeout_seconds == 60
    
    def test_config_rate_calculation(self):
        """Verify rate calculation"""
        config = CircuitBreakerConfig(max_requests=10, window_seconds=5)
        assert config.rate_per_second == 2.0
    
    def test_config_validation(self):
        """Verify config validation"""
        with pytest.raises(ValueError):
            CircuitBreakerConfig(failure_threshold=0)
        
        with pytest.raises(ValueError):
            CircuitBreakerConfig(timeout_seconds=-1)


class TestCircuitBreakerStates:
    """Tests for circuit breaker state machine"""
    
    def test_initial_state_closed(self):
        """Verify circuit starts in CLOSED state"""
        config = CircuitBreakerConfig()
        breaker = CircuitBreaker("test", config)
        assert breaker.state == CircuitState.CLOSED
    
    def test_opens_after_failures(self):
        """Verify circuit opens after failure threshold"""
        config = CircuitBreakerConfig(failure_threshold=2)
        breaker = CircuitBreaker("test", config)
        
        # Record 2 failures
        breaker._record_failure()
        breaker._record_failure()
        
        assert breaker.state == CircuitState.OPEN
    
    def test_half_open_after_timeout(self):
        """Verify circuit enters HALF_OPEN after timeout"""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            timeout_seconds=1
        )
        breaker = CircuitBreaker("test", config)
        
        # Open the circuit
        breaker._record_failure()
        assert breaker.state == CircuitState.OPEN
        
        # Wait for timeout
        time.sleep(1.1)
        
        # Should be ready for HALF_OPEN
        assert breaker._should_attempt_recovery()
    
    def test_closes_after_successful_recovery(self):
        """Verify circuit closes after successful recovery in HALF_OPEN"""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            success_threshold=1
        )
        breaker = CircuitBreaker("test", config)
        
        # Open circuit
        breaker._record_failure()
        assert breaker.state == CircuitState.OPEN
        
        # Manually move to HALF_OPEN
        breaker.state = CircuitState.HALF_OPEN
        breaker.success_count = 0
        
        # Record success
        breaker._record_success()
        
        # Should be closed
        assert breaker.state == CircuitState.CLOSED


class TestCircuitBreakerCall:
    """Tests for executing functions through circuit breaker"""
    
    def test_call_succeeds_normally(self):
        """Verify normal call succeeds"""
        config = CircuitBreakerConfig()
        breaker = CircuitBreaker("test", config)
        
        def always_success():
            return "ok"
        
        result = breaker.call(always_success)
        assert result == "ok"
        assert breaker.state == CircuitState.CLOSED
    
    def test_call_raises_when_open(self):
        """Verify call raises when circuit is open"""
        config = CircuitBreakerConfig(failure_threshold=1)
        breaker = CircuitBreaker("test", config)
        
        # Open the circuit
        breaker._record_failure()
        
        def some_function():
            return "ok"
        
        with pytest.raises(CircuitBreakerOpen):
            breaker.call(some_function)
    
    def test_call_records_failures(self):
        """Verify failures are recorded through call"""
        config = CircuitBreakerConfig(failure_threshold=2)
        breaker = CircuitBreaker("test", config)
        
        def always_fails():
            raise ValueError("Always fails")
        
        # First call - failure recorded, circuit still closed
        with pytest.raises(ValueError):
            breaker.call(always_fails)
        assert breaker.state == CircuitState.CLOSED
        
        # Second call - failure opens circuit
        with pytest.raises(ValueError):
            breaker.call(always_fails)
        assert breaker.state == CircuitState.OPEN


class TestEndpointCircuitBreaker:
    """Tests for managing multiple circuit breakers"""
    
    def test_get_or_create(self):
        """Verify get_or_create works"""
        manager = EndpointCircuitBreaker()
        
        config = CircuitBreakerConfig()
        breaker1 = manager.get_or_create("endpoint1", config)
        breaker2 = manager.get_or_create("endpoint1")  # Should return same
        
        assert breaker1 is breaker2
    
    def test_multiple_breakers(self):
        """Verify multiple breakers can be managed"""
        manager = EndpointCircuitBreaker()
        config = CircuitBreakerConfig()
        
        b1 = manager.get_or_create("ep1", config)
        b2 = manager.get_or_create("ep2", config)
        
        assert b1 is not b2
        
        status = manager.get_status()
        assert "ep1" in status
        assert "ep2" in status
    
    def test_reset_breaker(self):
        """Verify breaker can be reset"""
        manager = EndpointCircuitBreaker()
        config = CircuitBreakerConfig(failure_threshold=1)
        
        breaker = manager.get_or_create("test", config)
        breaker._record_failure()
        assert breaker.state == CircuitState.OPEN
        
        # Reset
        assert manager.reset_breaker("test") is True
        assert breaker.state == CircuitState.CLOSED
        
        # Reset non-existent
        assert manager.reset_breaker("nonexistent") is False


class TestCircuitBreakerIntegration:
    """Integration tests for circuit breaker"""
    
    def test_failing_function_opens_circuit(self):
        """Verify failing function eventually opens circuit"""
        config = CircuitBreakerConfig(failure_threshold=2)
        breaker = CircuitBreaker("test", config)
        
        fail_count = [0]
        
        def sometimes_fails():
            fail_count[0] += 1
            if fail_count[0] <= 2:
                raise ValueError("Fail")
            return "success"
        
        # First two calls fail and open circuit
        for i in range(2):
            with pytest.raises(ValueError):
                breaker.call(sometimes_fails)
        
        assert breaker.state == CircuitState.OPEN
        
        # Third call should be rejected
        with pytest.raises(CircuitBreakerOpen):
            breaker.call(sometimes_fails)
        
        # fail_count shouldn't increment (call was rejected)
        assert fail_count[0] == 2
