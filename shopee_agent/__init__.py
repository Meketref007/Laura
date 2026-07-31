"""Lazy package init — heavy submodules load on first attribute access.

Importing ``shopee_agent`` (or any submodule, e.g. ``shopee_agent.cli``) used
to eagerly import chat_auto + laura_daemon + seller_center, which pulls in
requests, playwright-adjacent tooling and the full autonomous stack (~0.4s).
Everything is now deferred until the attribute is actually used, cutting CLI
startup time to well under 0.5s.
"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY_ATTRS: dict[str, str] = {
    "ChatAutomation": "shopee_agent.chat_auto",
    "ChatMonitor": "shopee_agent.chat_monitor",
    "ShopeeClient": "shopee_agent.client",
    "ShopeeResponse": "shopee_agent.client",
    "ShopeeConfig": "shopee_agent.config",
    "load_config": "shopee_agent.config",
    "LauraDaemon": "shopee_agent.laura_daemon",
    "SellerCenterClient": "shopee_agent.seller_center",
    "SellerCenterCookie": "shopee_agent.seller_center",
    "SellerCenterSession": "shopee_agent.seller_center",
    "load_cookies": "shopee_agent.seller_center",
    "save_cookies": "shopee_agent.seller_center",
    "enviar_para_canal": "shopee_agent.vilu_workers",
    "analisar_reclamacao": "shopee_agent.vision",
    "descrever": "shopee_agent.vision",
    "ocr": "shopee_agent.vision",
    "iniciar_todos_workers": "shopee_agent.worker_bots",
    "parar_todos_workers": "shopee_agent.worker_bots",
}

__all__ = [
    "ShopeeClient", "ShopeeResponse",
    "ShopeeConfig", "load_config",
    "SellerCenterClient", "SellerCenterSession", "SellerCenterCookie",
    "load_cookies", "save_cookies",
    "ChatMonitor", "ChatAutomation",
    "LauraDaemon",
    "iniciar_todos_workers", "parar_todos_workers",
    "enviar_para_canal",
    "ocr", "descrever", "analisar_reclamacao",
]


def __getattr__(name: str) -> Any:
    """Import a re-exported symbol on first access (PEP 562)."""
    mod_name = _LAZY_ATTRS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(mod_name)
    value = getattr(mod, name)
    globals()[name] = value  # cache for subsequent lookups
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_ATTRS) | {"__all__"})
