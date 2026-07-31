"""
test_secrets_rotation.py - Tests for secrets rotation module
"""

import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shopee_agent.secrets_rotation import (
    SecretsRotationManager,
    TokenMetadata,
    TokenStatus,
)


def _make_manager():
    """Create a manager with isolated temp dir to avoid cross-test state leakage."""
    tmp = Path(f"secrets_test_{uuid.uuid4().hex[:8]}")
    return SecretsRotationManager(secrets_dir=str(tmp))


def _cleanup(manager):
    """Remove temp dir after test."""
    import shutil
    shutil.rmtree(str(manager.secrets_dir), ignore_errors=True)


class TestTokenMetadata:
    """Tests for TokenMetadata"""
    
    def test_metadata_creation(self):
        """Verify metadata creation"""
        metadata = TokenMetadata(
            token_value="test_token",
            created_at="2026-04-20T12:00:00+00:00",
            expires_at="2026-05-20T12:00:00+00:00",
            version=1,
            shop_id=123
        )
        
        assert metadata.token_value == "test_token"
        assert metadata.version == 1
        assert metadata.shop_id == 123
    
    def test_metadata_dict_conversion(self):
        """Verify metadata to_dict and from_dict"""
        metadata = TokenMetadata(
            token_value="test_token",
            created_at="2026-04-20T12:00:00+00:00",
            expires_at="2026-05-20T12:00:00+00:00",
            version=2
        )
        
        data = metadata.to_dict()
        assert data["token_value"] == "test_token"
        assert data["version"] == 2
        
        # Verify from_dict
        restored = TokenMetadata.from_dict(data)
        assert restored.token_value == metadata.token_value
        assert restored.version == metadata.version


class TestSecretsRotationManager:
    """Tests for SecretsRotationManager"""
    
    def test_manager_creation(self):
        """Verify manager initialization"""
        mgr = _make_manager()
        try:
            assert len(mgr._metadata) == 0
        finally:
            _cleanup(mgr)
    
    def test_register_token(self):
        """Verify token registration"""
        mgr = _make_manager()
        try:
            metadata = mgr.register_token(
                "test_token",
                "token_value_123",
                shop_id=456
            )
            
            assert metadata.token_value == "token_value_123"
            assert metadata.version == 1
            assert metadata.shop_id == 456
            assert metadata.status == TokenStatus.ACTIVE.value
        finally:
            _cleanup(mgr)
    
    def test_token_status_active(self):
        """Verify active token status"""
        mgr = _make_manager()
        try:
            mgr.register_token("test_token", "value", ttl_seconds=48 * 3600)
            
            status = mgr.get_token_status("test_token")
            assert status == TokenStatus.ACTIVE
        finally:
            _cleanup(mgr)
    
    def test_token_status_expired(self):
        """Verify expired token detection"""
        mgr = _make_manager()
        try:
            mgr.register_token("test_token", "value")
            mgr.update_token_expiration("test_token", 
                (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
            
            status = mgr.get_token_status("test_token")
            assert status == TokenStatus.EXPIRED
        finally:
            _cleanup(mgr)
    
    def test_token_status_expiring_soon(self):
        """Verify expiring soon detection"""
        mgr = _make_manager()
        try:
            soon = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
            mgr.register_token("test_token", "value")
            mgr.update_token_expiration("test_token", soon)
            
            status = mgr.get_token_status("test_token")
            assert status == TokenStatus.EXPIRING_SOON
        finally:
            _cleanup(mgr)
    
    def test_should_refresh(self):
        """Verify should_refresh logic"""
        mgr = _make_manager()
        try:
            mgr.register_token("test_token", "value", ttl_seconds=48 * 3600)
            
            assert not mgr.should_refresh("test_token")
            
            soon = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
            mgr.update_token_expiration("test_token", soon)
            
            assert mgr.should_refresh("test_token")
        finally:
            _cleanup(mgr)
    
    def test_rotate_token(self):
        """Verify token rotation"""
        mgr = _make_manager()
        try:
            mgr.register_token("test_token", "old_value", ttl_seconds=48 * 3600)
            
            new_metadata = mgr.rotate_token(
                "test_token",
                "new_value",
                ttl_seconds=48 * 3600
            )
            
            assert new_metadata.token_value == "new_value"
            assert new_metadata.version == 2
            assert new_metadata.status == TokenStatus.ACTIVE.value
        finally:
            _cleanup(mgr)
    
    def test_record_refresh_attempt_success(self):
        """Verify recording successful refresh"""
        mgr = _make_manager()
        try:
            mgr.register_token("test_token", "value")
            
            mgr.record_refresh_attempt("test_token", success=True)
            
            metadata = mgr._metadata["test_token"]
            assert metadata.refresh_attempts == 1
            assert metadata.refresh_errors == 0
            assert metadata.status == TokenStatus.ACTIVE.value
        finally:
            _cleanup(mgr)
    
    def test_record_refresh_attempt_failure(self):
        """Verify recording failed refresh"""
        mgr = _make_manager()
        try:
            mgr.register_token("test_token", "value")
            
            mgr.record_refresh_attempt("test_token", success=False, error="Network error")
            
            metadata = mgr._metadata["test_token"]
            assert metadata.refresh_attempts == 1
            assert metadata.refresh_errors == 1
        finally:
            _cleanup(mgr)
    
    def test_get_tokens_requiring_refresh(self):
        """Verify getting tokens needing refresh"""
        mgr = _make_manager()
        try:
            mgr.register_token("token1", "value1", ttl_seconds=48 * 3600)
            mgr.register_token("token2", "value2", ttl_seconds=48 * 3600)
            
            assert "token1" not in mgr.get_tokens_requiring_refresh()
            
            soon = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
            mgr.update_token_expiration("token1", soon)
            
            requiring = mgr.get_tokens_requiring_refresh()
            assert "token1" in requiring
        finally:
            _cleanup(mgr)
    
    def test_get_rotation_status(self):
        """Verify rotation status reporting"""
        mgr = _make_manager()
        try:
            mgr.register_token("token1", "value1")
            mgr.register_token("token2", "value2")
            
            status = mgr.get_rotation_status()
            
            assert status["total_tokens"] == 2
            assert status["active"] == 2
            assert "timestamp" in status
        finally:
            _cleanup(mgr)


class TestAutoRotation:
    """Tests for auto rotation functionality"""
    
    def test_start_stop_rotation(self):
        """Verify rotation can be started and stopped"""
        mgr = _make_manager()
        try:
            mgr.start_auto_rotation(check_interval_seconds=1)
            time.sleep(0.5)
            
            assert mgr._rotation_thread is not None
            assert mgr._rotation_thread.is_alive()
            
            mgr.stop_auto_rotation()
            time.sleep(1)
            
            assert not mgr._rotation_thread.is_alive()
        finally:
            _cleanup(mgr)
