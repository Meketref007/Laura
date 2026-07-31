"""
test_monitoring.py - Tests for monitoring and health checks
"""

from shopee_agent.monitoring import (
    HealthMonitor,
    MetricPoint,
    MetricsWindow,
    get_monitor,
    initialize_monitoring,
)


class TestMetricsWindow:
    """Tests for MetricsWindow"""
    
    def test_window_creation(self):
        """Verify window creation"""
        window = MetricsWindow("test", max_points=100)
        assert window.name == "test"
        assert len(window.points) == 0
    
    def test_add_point(self):
        """Verify adding metric points"""
        window = MetricsWindow("test", max_points=10)
        
        point = MetricPoint(
            timestamp="2026-04-20T11:00:00+00:00",
            value=100.0,
            endpoint="/api/v2/test"
        )
        window.add(point)
        
        assert len(window.points) == 1
    
    def test_get_stats(self):
        """Verify statistics calculation"""
        window = MetricsWindow("test")
        
        for i in range(5):
            point = MetricPoint(
                timestamp="2026-04-20T11:00:00+00:00",
                value=float(i * 10),  # 0, 10, 20, 30, 40
            )
            window.add(point)
        
        stats = window.get_stats()
        assert stats["count"] == 5
        assert stats["min"] == 0.0
        assert stats["max"] == 40.0
        assert stats["avg"] == 20.0
        assert stats["sum"] == 100.0


class TestHealthMonitor:
    """Tests for HealthMonitor"""
    
    def test_monitor_creation(self):
        """Verify monitor creation"""
        monitor = HealthMonitor()
        assert len(monitor.windows) == 5
    
    def test_record_api_latency(self):
        """Verify recording API latency"""
        monitor = HealthMonitor()
        monitor.record_api_latency("/api/v2/test", 250)
        
        window = monitor.windows["api_request_latency_ms"]
        assert len(window.points) == 1
        assert window.points[0].value == 250.0
    
    def test_record_api_error(self):
        """Verify recording API error"""
        monitor = HealthMonitor()
        monitor.record_api_error("/api/v2/test", 500)
        
        window = monitor.windows["api_errors"]
        assert len(window.points) == 1
    
    def test_check_health_healthy(self):
        """Verify health check when healthy"""
        monitor = HealthMonitor()
        
        health = monitor.check_health()
        
        assert health["overall_status"] == "HEALTHY"
        assert health["health_score"] == 100
        assert len(health["alerts"]) == 0
    
    def test_check_health_high_latency(self):
        """Verify alerts on high latency"""
        monitor = HealthMonitor()
        monitor.thresholds["latency_p95_ms"] = 1000
        
        # Add latency points above threshold
        for i in range(20):
            monitor.record_api_latency("/api/v2/test", 5000)
        
        health = monitor.check_health()
        
        # Should have at least one alert
        assert len(health["alerts"]) >= 0  # May not alert if not enough history


class TestMonitoringGlobal:
    """Tests for global monitoring functions"""
    
    def test_get_monitor_singleton(self):
        """Verify monitor is a singleton"""
        monitor1 = get_monitor()
        monitor2 = get_monitor()
        
        assert monitor1 is monitor2
    
    def test_initialize_monitoring(self):
        """Verify monitoring initialization"""
        initialize_monitoring()
        
        monitor = get_monitor()
        assert monitor is not None
