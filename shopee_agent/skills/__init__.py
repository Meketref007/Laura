"""Skills package for Shopee agent."""
from . import loader, registry
from .loader import discover_and_register

discover_and_register()

__all__ = ["registry", "loader", "discover_and_register"]
