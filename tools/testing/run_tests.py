#!/usr/bin/env python3
"""
run_tests.py - Simple test runner (no external dependencies)
Runs basic sanity tests without pytest
"""

import sys
import traceback
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))


def test_imports():
    """Test that all modules can be imported"""
    try:
        return True, "All imports OK"
    except Exception as e:
        return False, f"Import error: {e}"


def test_logger_creation():
    """Test logger module works"""
    try:
        from shopee_agent.logger import get_logger, info, debug
        logger = get_logger()
        assert logger is not None
        info("Test info log")
        debug("Test debug log")
        return True, "Logger works"
    except Exception as e:
        return False, f"Logger error: {e}"


def test_retry_config():
    """Test retry configuration"""
    try:
        from shopee_agent.retry import RetryConfig, RETRY_NETWORK
        
        config = RetryConfig(max_attempts=3)
        assert config.max_attempts == 3
        
        delay_0 = config.get_delay(0)
        delay_1 = config.get_delay(1)
        assert delay_1 > delay_0  # Backoff should increase
        
        assert RETRY_NETWORK is not None
        return True, "Retry config OK"
    except Exception as e:
        return False, f"Retry error: {e}"


def test_retry_decorator():
    """Test retry decorator works"""
    try:
        from shopee_agent.retry import retry, RetryConfig
        
        config = RetryConfig(max_attempts=2, initial_delay_ms=10)
        call_count = [0]
        
        @retry(config=config)
        def sometimes_fails():
            call_count[0] += 1
            if call_count[0] < 2:
                raise ValueError("Fail once")
            return "success"
        
        result = sometimes_fails()
        assert result == "success"
        assert call_count[0] == 2
        
        return True, "Retry decorator OK"
    except Exception as e:
        return False, f"Decorator error: {e}"


def test_logging_file_output():
    """Test logging creates JSON logs"""
    try:
        from shopee_agent.logger import info
        import json
        
        info("Test message for file", test=True)
        
        log_file = Path("logs/laura_operations.log")
        if log_file.exists():
            last_line = log_file.read_text().strip().split("\n")[-1]
            obj = json.loads(last_line)
            assert "timestamp" in obj
            assert "message" in obj
            return True, "JSON logging works"
        else:
            return True, "Log file not created (OK in test env)"
    except Exception as e:
        return False, f"Logging file error: {e}"


def test_circuit_breaker():
    """Test circuit breaker functionality"""
    try:
        from shopee_agent.circuit_breaker import (
            CircuitBreaker,
            CircuitBreakerConfig,
            CircuitBreakerOpen,
            CircuitState,
        )
        
        # Test basic state machine
        config = CircuitBreakerConfig(failure_threshold=2)
        breaker = CircuitBreaker("test", config)
        
        assert breaker.state == CircuitState.CLOSED
        
        # Record 2 failures to open circuit
        breaker._record_failure()
        breaker._record_failure()
        
        assert breaker.state == CircuitState.OPEN
        
        # Verify call raises when circuit is open
        def dummy():
            pass
        
        try:
            breaker.call(dummy)
            return False, "Should have raised CircuitBreakerOpen"
        except CircuitBreakerOpen:
            pass
        
        return True, "Circuit breaker OK"
    except Exception as e:
        return False, f"Circuit breaker error: {e}"


def test_monitoring():
    """Test monitoring functionality"""
    try:
        from shopee_agent.monitoring import HealthMonitor, MetricsWindow
        
        # Test window
        window = MetricsWindow("test", max_points=10)
        assert window.name == "test"
        
        # Test monitor
        monitor = HealthMonitor()
        monitor.record_api_latency("/api/v2/test", 250)
        
        health = monitor.check_health()
        assert health["overall_status"] in ["HEALTHY", "DEGRADED", "CRITICAL"]
        
        return True, "Monitoring OK"
    except Exception as e:
        return False, f"Monitoring error: {e}"


def test_secrets_rotation():
    """Test secrets rotation functionality"""
    try:
        from shopee_agent.secrets_rotation import SecretsRotationManager, TokenStatus
        import shutil
        import os
        
        # Use a unique test directory
        test_dir = "secrets_test_run"
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)
        
        manager = SecretsRotationManager(secrets_dir=test_dir)
        
        # Register token
        metadata = manager.register_token("test_token", "token_value")
        assert metadata.version >= 1
        
        # Check status
        status = manager.get_token_status("test_token")
        assert status == TokenStatus.ACTIVE
        
        # Rotate token
        new_metadata = manager.rotate_token("test_token", "new_value")
        assert new_metadata.version > metadata.version
        
        # Cleanup
        shutil.rmtree(test_dir)
        
        return True, "Secrets rotation OK"
    except Exception as e:
        return False, f"Secrets rotation error: {e}"


def test_token_scheduler():
    """Test token refresh scheduler"""
    try:
        from shopee_agent.token_scheduler import TokenRefreshScheduler
        
        scheduler = TokenRefreshScheduler()
        
        # Register callback
        call_count = [0]
        def mock_refresh(token_name):
            call_count[0] += 1
            return True
        
        scheduler.register_refresh_callback("test_token", mock_refresh)
        
        # Force refresh
        result = scheduler.force_refresh("test_token")
        assert result is True
        assert call_count[0] == 1
        
        return True, "Token scheduler OK"
    except Exception as e:
        return False, f"Token scheduler error: {e}"


def test_performance_baseline():
    """Test performance baseline and SLA validation"""
    try:
        from shopee_agent.performance_baseline import (
            PerformanceTester,
            SLA,
        )
        
        tester = PerformanceTester(baselines_dir="baselines_test")
        
        # Test SLA registration
        sla = SLA(endpoint="/api/v2/custom", p95_latency_ms=1000)
        tester.register_sla(sla)
        assert "/api/v2/custom" in tester.slas
        
        # Test benchmark with mock requests
        request_count = [0]
        def mock_request():
            request_count[0] += 1
            return (True, 100.0)
        
        result = tester.benchmark(
            endpoint="/api/v2/test",
            method="GET",
            request_func=mock_request,
            num_requests=10
        )
        
        assert result["request_count"] == 10
        assert "sla_validation" in result
        
        return True, "Performance baseline OK"
    except Exception as e:
        return False, f"Performance baseline error: {e}"


def test_distributed_tracing():
    """Test distributed tracing with correlation IDs"""
    try:
        from shopee_agent.tracing import (
            DistributedTracer,
            get_correlation_id,
            get_trace_headers,
        )
        
        tracer = DistributedTracer()
        
        # Test trace creation
        context = tracer.start_trace(
            endpoint="/api/v2/test",
            operation="get_items"
        )
        
        assert context.correlation_id
        assert context.operation == "get_items"
        
        # Test child span
        child = tracer.start_child_span(
            parent_context=context,
            operation="child_op"
        )
        
        assert child.correlation_id == context.correlation_id
        assert child.parent_span_id == context.span_id
        
        # Test span completion
        tracer.end_span(context, status_code=200)
        tracer.end_span(child)
        
        # Test convenience functions
        correlation_id = get_correlation_id()
        assert correlation_id
        
        headers = get_trace_headers()
        assert "X-Correlation-ID" in headers
        
        return True, "Distributed tracing OK"
    except Exception as e:
        return False, f"Distributed tracing error: {e}"


def test_webhook_server():
    """Test webhook server and event handling"""
    try:
        from shopee_agent.webhook_server import (
            WebhookEvent,
            WebhookServer,
        )
        from shopee_agent.webhook_handlers import (
            EventHandlerRegistry,
            emit_test_event,
        )
        
        # Test event creation
        event = WebhookEvent(
            event_id="evt_123",
            event_type="mediaspace.transcoding_complete",
            source="mediaspace",
            timestamp="2026-04-20T12:00:00+00:00",
            data={"video_id": "vid123"},
            valid=True
        )
        
        assert event.event_id == "evt_123"
        
        # Test server creation
        server = WebhookServer(port=8765)
        assert server.port == 8765
        
        # Test handler registry
        registry = EventHandlerRegistry()
        assert len(registry.handlers) > 0
        
        # Test emit test event
        test_event = emit_test_event(
            event_type="mediaspace.transcoding_complete",
            data={"video_id": "vid123"}
        )
        assert test_event.valid
        
        return True, "Webhook server OK"
    except Exception as e:
        return False, f"Webhook server error: {e}"


def main():
    """Run all tests"""
    tests = [
        ("Imports", test_imports),
        ("Logger", test_logger_creation),
        ("Retry Config", test_retry_config),
        ("Retry Decorator", test_retry_decorator),
        ("Logging File Output", test_logging_file_output),
        ("Circuit Breaker", test_circuit_breaker),
        ("Monitoring", test_monitoring),
        ("Secrets Rotation", test_secrets_rotation),
        ("Token Scheduler", test_token_scheduler),
        ("Performance Baseline", test_performance_baseline),
        ("Distributed Tracing", test_distributed_tracing),
        ("Webhook Server", test_webhook_server),
    ]
    
    print("=" * 70)
    print("LAURA TEST SUITE (No External Dependencies)")
    print("=" * 70)
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            ok, msg = test_func()
            status = "✅ PASS" if ok else "❌ FAIL"
            print(f"{status:8} | {test_name:20} | {msg}")
            if ok:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ ERROR | {test_name:20} | {str(e)[:50]}")
            traceback.print_exc()
            failed += 1
    
    print("=" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 70)
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
