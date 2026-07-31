"""
test_performance_baseline.py - Tests for performance baseline module
"""

from shopee_agent.performance_baseline import (
    PerformanceTester,
    PerformanceMetrics,
    SLA,
    PerformanceRating,
)


class TestPerformanceMetrics:
    """Tests for PerformanceMetrics"""
    
    def test_metrics_creation(self):
        """Verify metrics creation"""
        metrics = PerformanceMetrics(
            endpoint="/api/v2/test",
            method="GET"
        )
        
        assert metrics.endpoint == "/api/v2/test"
        assert metrics.method == "GET"
        assert metrics.total_requests == 0
    
    def test_get_stats_empty(self):
        """Verify stats on empty metrics"""
        metrics = PerformanceMetrics(
            endpoint="/api/v2/test",
            method="GET"
        )
        
        stats = metrics.get_stats()
        assert stats["request_count"] == 0
        assert stats["error_rate_pct"] == 0.0
    
    def test_get_stats_with_data(self):
        """Verify stats calculation"""
        metrics = PerformanceMetrics(
            endpoint="/api/v2/test",
            method="GET"
        )
        
        # Add 10 requests
        for i in range(10):
            metrics.latencies_ms.append(float(i * 100))
            metrics.success_count += 1
            metrics.total_requests += 1
        
        metrics.duration_seconds = 1.0
        
        stats = metrics.get_stats()
        assert stats["request_count"] == 10
        assert stats["success_count"] == 10
        assert stats["error_count"] == 0
        assert stats["error_rate_pct"] == 0.0
        assert stats["latency_ms"]["min"] == 0.0
        assert stats["latency_ms"]["max"] == 900.0
        assert stats["throughput_rps"] == 10.0


class TestSLA:
    """Tests for SLA"""
    
    def test_sla_creation(self):
        """Verify SLA creation"""
        sla = SLA(
            endpoint="/api/v2/test",
            p95_latency_ms=500,
            throughput_rps=100
        )
        
        assert sla.endpoint == "/api/v2/test"
        assert sla.p95_latency_ms == 500
        assert sla.throughput_rps == 100


class TestPerformanceTester:
    """Tests for PerformanceTester"""
    
    def test_tester_creation(self):
        """Verify tester creation"""
        tester = PerformanceTester(baselines_dir="baselines_test")
        assert len(tester.slas) > 0
    
    def test_register_sla(self):
        """Verify SLA registration"""
        tester = PerformanceTester(baselines_dir="baselines_test")
        
        sla = SLA(
            endpoint="/api/v2/custom",
            p95_latency_ms=1000
        )
        tester.register_sla(sla)
        
        assert "/api/v2/custom" in tester.slas
    
    def test_record_request(self):
        """Verify request recording"""
        tester = PerformanceTester(baselines_dir="baselines_test")
        
        tester.record_request(
            endpoint="/api/v2/test",
            method="GET",
            latency_ms=250,
            success=True
        )
        
        key = "GET /api/v2/test"
        assert key in tester.metrics
        assert tester.metrics[key].success_count == 1
        assert len(tester.metrics[key].latencies_ms) == 1
    
    def test_benchmark(self):
        """Verify benchmark execution"""
        tester = PerformanceTester(baselines_dir="baselines_test")
        
        request_count = [0]
        def mock_request():
            request_count[0] += 1
            return (True, 100.0 + request_count[0])  # Increasing latency
        
        result = tester.benchmark(
            endpoint="/api/v2/test",
            method="GET",
            request_func=mock_request,
            num_requests=10
        )
        
        assert result["request_count"] == 10
        assert result["success_count"] == 10
        assert result["error_count"] == 0
        assert "latency_ms" in result
        assert "sla_validation" in result
    
    def test_performance_rating_excellent(self):
        """Verify excellent rating"""
        tester = PerformanceTester(baselines_dir="baselines_test")
        
        metrics = PerformanceMetrics(
            endpoint="/api/v2/test",
            method="GET"
        )
        
        for i in range(100):
            metrics.latencies_ms.append(100.0)
        metrics.total_requests = 100
        metrics.success_count = 100
        
        tester.metrics["GET /api/v2/test"] = metrics
        
        rating = tester.get_performance_rating("/api/v2/test", "GET")
        assert rating == PerformanceRating.EXCELLENT
    
    def test_performance_rating_critical(self):
        """Verify critical rating"""
        tester = PerformanceTester(baselines_dir="baselines_test")
        
        metrics = PerformanceMetrics(
            endpoint="/api/v2/test",
            method="GET"
        )
        
        for i in range(100):
            metrics.latencies_ms.append(10000.0)
        metrics.total_requests = 100
        metrics.success_count = 100
        
        tester.metrics["GET /api/v2/test"] = metrics
        
        rating = tester.get_performance_rating("/api/v2/test", "GET")
        assert rating == PerformanceRating.CRITICAL
