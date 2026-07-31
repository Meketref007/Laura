from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from shopee_agent.paths import ANNOY_INDEX, ANNOY_META, FAISS_INDEX, FAISS_META


@dataclass(frozen=True)
class ShopeeConfig:
    base_url: str
    partner_id: int
    partner_key: str
    redirect_url: str
    default_shop_id: int | None = None
    default_access_token: str | None = None
    default_refresh_token: str | None = None
    # Vector backend configuration
    vector_backend: str = "memory"  # choices: memory, annoy
    annoy_index_path: str | None = str(ANNOY_INDEX)
    annoy_meta_path: str | None = str(ANNOY_META)
    vector_dim: int = 128
    annoy_background_build: bool = False
    annoy_build_interval: int = 60
    faiss_index_path: str | None = str(FAISS_INDEX)
    faiss_meta_path: str | None = str(FAISS_META)


class ConfigError(RuntimeError):
    pass


def _load_env_file_if_present(env_file: str = ".env") -> None:
    env_path = Path(env_file)
    if not env_path.exists() or not env_path.is_file():
        return

    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except PermissionError:
        # If the .env file exists but isn't readable by the current user,
        # silently skip loading it to avoid crashing CLI commands.
        return

    for raw_line in lines:
        line = raw_line.strip()

        if line.startswith("export "):
            line = line[len("export ") :].strip()

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not key:
            continue

        if len(value) >= 2 and (
            (value.startswith('"') and value.endswith('"'))
            or (value.startswith("'") and value.endswith("'"))
        ):
            value = value[1:-1]

        # Keep real environment precedence when variables are already exported.
        os.environ.setdefault(key, value)


def _read_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _read_optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name} must be an integer") from exc


def load_config() -> ShopeeConfig:
    _load_env_file_if_present()

    partner_id_str = _read_required("SHOPEE_PARTNER_ID")
    try:
        partner_id = int(partner_id_str)
    except ValueError as exc:
        raise ConfigError("SHOPEE_PARTNER_ID must be an integer") from exc

    return ShopeeConfig(
        base_url=os.getenv("SHOPEE_BASE_URL", "https://partner.shopeemobile.com").rstrip("/"),
        partner_id=partner_id,
        partner_key=_read_required("SHOPEE_PARTNER_KEY"),
        redirect_url=_read_required("SHOPEE_REDIRECT_URL"),
        default_shop_id=_read_optional_int("SHOPEE_DEFAULT_SHOP_ID"),
        default_access_token=os.getenv("SHOPEE_DEFAULT_ACCESS_TOKEN", "").strip() or None,
        default_refresh_token=os.getenv("SHOPEE_DEFAULT_REFRESH_TOKEN", "").strip() or None,
        vector_backend=os.getenv("LAURA_VECTOR_BACKEND", "memory").strip().lower(),
        annoy_index_path=os.getenv("LAURA_ANNOY_INDEX_PATH", str(ANNOY_INDEX)).strip() or None,
        annoy_meta_path=os.getenv("LAURA_ANNOY_META_PATH", str(ANNOY_META)).strip() or None,
        vector_dim=int(os.getenv("LAURA_VECTOR_DIM", "128") or "128"),
        annoy_background_build=(os.getenv("LAURA_ANNOY_BACKGROUND_BUILD", "0").strip() in ("1", "true", "True", "yes")),
        annoy_build_interval=int(os.getenv("LAURA_ANNOY_BUILD_INTERVAL", "60") or "60"),
        faiss_index_path=os.getenv("LAURA_FAISS_INDEX_PATH", str(FAISS_INDEX)).strip() or None,
        faiss_meta_path=os.getenv("LAURA_FAISS_META_PATH", str(FAISS_META)).strip() or None,
    )
