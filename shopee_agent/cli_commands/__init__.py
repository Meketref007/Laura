"""Comandos extraidos do cli.py para modulos independentes."""
from .auth_shop_cmd import register_subparsers as register_auth_shop
from .cache_cmd import register_subparsers as register_cache
from .chat_cmd import register_subparsers as register_chat
from .cleanup_cmd import handle_cleanup, register_cleanup_parser
from .email_cmd import register_subparsers as register_email
from .export_cmd import handle_export, register_export_parser
from .health_cmd import handle_health, register_health_parser
from .monitor_cmd import register_subparsers as register_monitor
from .order_cmd import register_subparsers as register_order
from .product_cmd import register_subparsers as register_product
from .report_cmd import register_subparsers as register_report
from .seller_cmd import register_subparsers as register_seller
from .watchdog_cmd import register_subparsers as register_watchdog

__all__ = [
    "register_export_parser", "handle_export",
    "register_cleanup_parser", "handle_cleanup",
    "register_health_parser", "handle_health",
    "register_auth_shop",
    "register_product",
    "register_order",
    "register_report",
    "register_chat",
    "register_seller",
    "register_email",
    "register_cache",
    "register_monitor",
    "register_watchdog",
]
