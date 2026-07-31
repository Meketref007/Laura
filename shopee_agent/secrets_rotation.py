"""
secrets_rotation.py - Automated credential rotation and token lifecycle management
"""

import json
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from shopee_agent.logger import error, info, warning


class TokenStatus(Enum):
    """Token lifecycle status"""
    ACTIVE = "active"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"
    REFRESHING = "refreshing"
    REFRESH_FAILED = "refresh_failed"


@dataclass
class TokenMetadata:
    """Metadata for a credential"""
    token_value: str
    created_at: str
    expires_at: str | None
    status: str = TokenStatus.ACTIVE.value
    version: int = 1
    shop_id: int | None = None
    last_refreshed_at: str | None = None
    refresh_attempts: int = 0
    refresh_errors: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TokenMetadata":
        return cls(**data)


class SecretsRotationManager:
    """
    Manages credential lifecycle, expiration, and automatic rotation.
    
    Features:
    - Track token creation and expiration
    - Automatic rotation before expiration
    - Credential versioning and history
    - Failed rotation recovery
    - Thread-safe operations
    """

    # Token expiration defaults (Shopee tokens valid ~30 days)
    DEFAULT_TOKEN_TTL_SECONDS = 30 * 24 * 3600  # 30 days
    REFRESH_THRESHOLD_SECONDS = 24 * 3600  # Refresh if < 1 day remaining
    MIN_TOKEN_TTL_SECONDS = 3600  # Minimum 1 hour validity

    def __init__(
        self,
        secrets_dir: str = "secrets",
        rotation_history_file: str = "secrets_rotation_history.jsonl"
    ):
        self.secrets_dir = Path(secrets_dir)
        self.secrets_dir.mkdir(exist_ok=True)

        self.rotation_history_file = self.secrets_dir / rotation_history_file
        self._metadata: dict[str, TokenMetadata] = {}
        self._lock = threading.RLock()
        self._rotation_thread: threading.Thread | None = None
        self._stop_rotation = threading.Event()

        self._load_metadata()
        info("Secrets rotation manager initialized",
            secrets_dir=str(self.secrets_dir),
            managed_tokens=len(self._metadata)
        )

    def register_token(
        self,
        token_name: str,
        token_value: str,
        expires_at: str | None = None,
        shop_id: int | None = None,
        ttl_seconds: int | None = None
    ) -> TokenMetadata:
        """
        Register a token for lifecycle management.
        
        Args:
            token_name: Identifier (e.g., "access_token", "refresh_token")
            token_value: The actual token/secret
            expires_at: ISO8601 expiration time (optional)
            shop_id: Shop ID for multi-shop deployments
            ttl_seconds: Override default TTL
        """
        with self._lock:
            ttl = ttl_seconds or self.DEFAULT_TOKEN_TTL_SECONDS

            if expires_at is None:
                expires_at = (
                    datetime.now(UTC) + timedelta(seconds=ttl)
                ).isoformat()

            now = datetime.now(UTC).isoformat()
            version = 1

            if token_name in self._metadata:
                version = self._metadata[token_name].version + 1

            metadata = TokenMetadata(
                token_value=token_value,
                created_at=now,
                expires_at=expires_at,
                version=version,
                shop_id=shop_id,
                status=TokenStatus.ACTIVE.value
            )

            self._metadata[token_name] = metadata
            self._record_rotation_event("token_registered", token_name, metadata)

            info(f"Token registered: {token_name}",
                version=version,
                expires_at=expires_at,
                shop_id=shop_id
            )

            return metadata

    def get_token_status(self, token_name: str) -> TokenStatus:
        """Check current status of a token"""
        with self._lock:
            if token_name not in self._metadata:
                return TokenStatus.EXPIRED

            metadata = self._metadata[token_name]

            if metadata.status == TokenStatus.REFRESHING.value:
                return TokenStatus.REFRESHING

            if metadata.status == TokenStatus.REFRESH_FAILED.value:
                return TokenStatus.REFRESH_FAILED

            if metadata.expires_at:
                # Parse expires_at flexibly; prefer timezone-aware parse
                expires = None
                try:
                    expires = datetime.fromisoformat(metadata.expires_at)
                except Exception:
                    try:
                        expires = datetime.fromisoformat(metadata.expires_at.replace("+00:00", ""))
                        expires = expires.replace(tzinfo=UTC)
                    except Exception:
                        expires = None
                now = datetime.now(UTC)
                if expires is not None:
                    seconds_remaining = (expires - now).total_seconds()
                else:
                    seconds_remaining = float("inf")

                if seconds_remaining <= 0:
                    return TokenStatus.EXPIRED
                elif seconds_remaining < self.REFRESH_THRESHOLD_SECONDS:
                    return TokenStatus.EXPIRING_SOON

            return TokenStatus.ACTIVE

    def should_refresh(self, token_name: str) -> bool:
        """Check if token should be refreshed"""
        status = self.get_token_status(token_name)
        return status in (TokenStatus.EXPIRING_SOON, TokenStatus.REFRESH_FAILED)

    def rotate_token(
        self,
        token_name: str,
        new_token_value: str,
        expires_at: str | None = None,
        ttl_seconds: int | None = None
    ) -> TokenMetadata:
        """
        Rotate to a new token value.
        
        Args:
            token_name: Token identifier
            new_token_value: New token/secret value
            expires_at: ISO8601 expiration time
            ttl_seconds: Override default TTL
        
        Returns:
            Updated TokenMetadata
        """
        with self._lock:
            if token_name not in self._metadata:
                warning(f"Attempting to rotate unregistered token: {token_name}")
                return self.register_token(
                    token_name,
                    new_token_value,
                    expires_at=expires_at,
                    ttl_seconds=ttl_seconds
                )

            old_metadata = self._metadata[token_name]

            ttl = ttl_seconds or self.DEFAULT_TOKEN_TTL_SECONDS
            if expires_at is None:
                expires_at = (
                    datetime.now(UTC) + timedelta(seconds=ttl)
                ).isoformat()

            now = datetime.now(UTC).isoformat()
            new_metadata = TokenMetadata(
                token_value=new_token_value,
                created_at=now,
                expires_at=expires_at,
                version=old_metadata.version + 1,
                shop_id=old_metadata.shop_id,
                status=TokenStatus.ACTIVE.value,
                last_refreshed_at=now
            )

            self._metadata[token_name] = new_metadata
            self._record_rotation_event("token_rotated", token_name, new_metadata)

            info(f"Token rotated: {token_name}",
                from_version=old_metadata.version,
                to_version=new_metadata.version,
                expires_at=expires_at
            )

            return new_metadata

    def record_refresh_attempt(
        self,
        token_name: str,
        success: bool = True,
        error: str | None = None
    ) -> None:
        """Record a refresh attempt (success or failure)"""
        with self._lock:
            if token_name not in self._metadata:
                return

            metadata = self._metadata[token_name]

            if success:
                metadata.status = TokenStatus.ACTIVE.value
                metadata.refresh_errors = 0
                info(f"Refresh attempt succeeded: {token_name}",
                    version=metadata.version,
                    shop_id=metadata.shop_id
                )
            else:
                metadata.refresh_errors += 1
                if metadata.refresh_errors >= 3:
                    metadata.status = TokenStatus.REFRESH_FAILED.value
                warning(f"Refresh attempt failed: {token_name}",
                    error=error,
                    attempts=metadata.refresh_attempts + 1,
                    version=metadata.version
                )

            metadata.refresh_attempts += 1
            self._record_rotation_event(
                "refresh_attempt",
                token_name,
                metadata,
                success=success,
                error=error
            )

    def update_token_expiration(
        self,
        token_name: str,
        expires_at: str,
        ttl_seconds: int | None = None
    ) -> None:
        """Update expiration time for a token"""
        with self._lock:
            if token_name not in self._metadata:
                warning(f"Token not found: {token_name}")
                return

            self._metadata[token_name].expires_at = expires_at

            if ttl_seconds:
                now = datetime.now(UTC)
                expires = None
                try:
                    expires = datetime.fromisoformat(expires_at)
                except Exception:
                    try:
                        expires = datetime.fromisoformat(expires_at.replace("+00:00", ""))
                        expires = expires.replace(tzinfo=UTC)
                    except Exception:
                        expires = None
                actual_ttl = (expires - now).total_seconds() if expires is not None else float("inf")

                if actual_ttl < self.MIN_TOKEN_TTL_SECONDS:
                    warning(f"Token TTL too short: {token_name}",
                        ttl_seconds=actual_ttl,
                        min_required=self.MIN_TOKEN_TTL_SECONDS
                    )

    def get_tokens_requiring_refresh(self) -> list[str]:
        """Get list of token names that should be refreshed"""
        with self._lock:
            return [
                name for name in self._metadata
                if self.should_refresh(name)
            ]

    def get_rotation_status(self) -> dict[str, Any]:
        """Get overall rotation status"""
        with self._lock:
            total = len(self._metadata)
            active = sum(1 for m in self._metadata.values()
                        if m.status == TokenStatus.ACTIVE.value)
            expiring_soon = sum(1 for m in self._metadata.values()
                               if m.status == TokenStatus.EXPIRING_SOON.value)
            failed = sum(1 for m in self._metadata.values()
                        if m.status == TokenStatus.REFRESH_FAILED.value)

            return {
                "timestamp": datetime.now(UTC).isoformat(),
                "total_tokens": total,
                "active": active,
                "expiring_soon": expiring_soon,
                "refresh_failed": failed,
                "requiring_refresh": len(self.get_tokens_requiring_refresh())
            }

    def start_auto_rotation(self, check_interval_seconds: int = 3600) -> None:
        """
        Start background thread for automatic token rotation.
        
        Args:
            check_interval_seconds: How often to check for expiring tokens (default 1 hour)
        """
        if self._rotation_thread and self._rotation_thread.is_alive():
            warning("Auto rotation already running")
            return

        self._stop_rotation.clear()
        self._rotation_thread = threading.Thread(
            target=self._auto_rotation_loop,
            args=(check_interval_seconds,),
            daemon=True
        )
        self._rotation_thread.start()

        info("Auto rotation started",
            check_interval_seconds=check_interval_seconds
        )

    def stop_auto_rotation(self) -> None:
        """Stop background rotation thread"""
        self._stop_rotation.set()

        if self._rotation_thread and self._rotation_thread.is_alive():
            self._rotation_thread.join(timeout=5)

        info("Auto rotation stopped")

    def _auto_rotation_loop(self, check_interval_seconds: int) -> None:
        """Background loop checking for tokens needing rotation"""
        while not self._stop_rotation.is_set():
            try:
                tokens_to_refresh = self.get_tokens_requiring_refresh()

                if tokens_to_refresh:
                    info("Tokens requiring refresh",
                        count=len(tokens_to_refresh),
                        tokens=tokens_to_refresh
                    )
                    # Caller is responsible for actual rotation via callbacks
                    self._record_rotation_event(
                        "refresh_required",
                        "auto_check",
                        {"tokens": tokens_to_refresh}
                    )

                self._stop_rotation.wait(check_interval_seconds)
            except Exception as e:
                error("Error in rotation loop",
                    error=str(e)
                )

    def _load_metadata(self) -> None:
        """Load metadata from persistent storage"""
        if not self.rotation_history_file.exists():
            return

        try:
            with open(self.rotation_history_file) as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("event_type") == "token_registered":
                            metadata_dict = data.get("metadata", {})
                            if metadata_dict:
                                token_name = data.get("token_name")
                                # Load only the latest version of each token
                                if token_name not in self._metadata or \
                                   metadata_dict.get("version", 0) > \
                                   self._metadata[token_name].version:
                                    self._metadata[token_name] = \
                                        TokenMetadata.from_dict(metadata_dict)
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            warning(f"Could not load rotation history: {e}")

    def _record_rotation_event(
        self,
        event_type: str,
        token_name: str,
        metadata: Any,
        **extra
    ) -> None:
        """Record rotation event to history file"""
        try:
            event = {
                "timestamp": datetime.now(UTC).isoformat(),
                "event_type": event_type,
                "token_name": token_name,
                "metadata": metadata.to_dict() if hasattr(metadata, "to_dict") else metadata,
            }
            event.update(extra)

            with open(self.rotation_history_file, "a") as f:
                f.write(json.dumps(event) + "\n")
        except Exception as e:
            warning(f"Could not record rotation event: {e}")


# Global instance
_rotation_manager: SecretsRotationManager | None = None


def initialize_rotation_manager(
    secrets_dir: str = "secrets",
    rotation_history_file: str = "secrets_rotation_history.jsonl"
) -> SecretsRotationManager:
    """Initialize global rotation manager"""
    global _rotation_manager

    if _rotation_manager is None:
        _rotation_manager = SecretsRotationManager(
            secrets_dir=secrets_dir,
            rotation_history_file=rotation_history_file
        )

    return _rotation_manager


def get_rotation_manager() -> SecretsRotationManager:
    """Get global rotation manager"""
    global _rotation_manager

    if _rotation_manager is None:
        _rotation_manager = SecretsRotationManager()

    return _rotation_manager
