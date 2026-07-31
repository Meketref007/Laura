"""
test_token_scheduler.py - Tests for token refresh scheduler
"""

import time
from shopee_agent.token_scheduler import TokenRefreshScheduler


class TestTokenRefreshScheduler:
    """Tests for TokenRefreshScheduler"""
    
    def test_scheduler_creation(self):
        """Verify scheduler initialization"""
        scheduler = TokenRefreshScheduler(check_interval_seconds=1)
        assert scheduler.check_interval_seconds == 1
    
    def test_register_refresh_callback(self):
        """Verify callback registration"""
        scheduler = TokenRefreshScheduler()
        
        def mock_refresh(token_name):
            return True
        
        scheduler.register_refresh_callback("test_token", mock_refresh)
        
        assert "test_token" in scheduler._refresh_callbacks
    
    def test_force_refresh(self):
        """Verify manual refresh execution"""
        scheduler = TokenRefreshScheduler()
        refresh_called = []
        
        def mock_refresh(token_name):
            refresh_called.append(token_name)
            return True
        
        scheduler.register_refresh_callback("test_token", mock_refresh)
        
        result = scheduler.force_refresh("test_token")
        
        assert result is True
        assert "test_token" in refresh_called
    
    def test_start_stop_scheduler(self):
        """Verify scheduler lifecycle"""
        scheduler = TokenRefreshScheduler(check_interval_seconds=1)
        scheduler.start()
        
        # Give thread time to start
        time.sleep(0.5)
        assert scheduler._scheduler_thread.is_alive()
        
        scheduler.stop()
        
        # Give thread time to stop
        time.sleep(1)
        assert not scheduler._scheduler_thread.is_alive()
    
    def test_backoff_logic(self):
        """Verify exponential backoff on failures"""
        scheduler = TokenRefreshScheduler()
        
        # Simulate first backoff
        scheduler._increase_backoff("token1")
        backoff1 = scheduler._backoff_counters["token1"]
        assert backoff1 == TokenRefreshScheduler.INITIAL_BACKOFF_SECONDS
        
        # Simulate second backoff
        scheduler._increase_backoff("token1")
        backoff2 = scheduler._backoff_counters["token1"]
        assert backoff2 > backoff1
        assert backoff2 <= TokenRefreshScheduler.MAX_BACKOFF_SECONDS
    
    def test_clear_backoff(self):
        """Verify backoff clearing after success"""
        scheduler = TokenRefreshScheduler()
        scheduler._increase_backoff("token1")
        
        assert scheduler._backoff_counters["token1"] > 0
        
        scheduler._clear_backoff("token1")
        
        assert scheduler._backoff_counters["token1"] == 0
