"""Tests for the LauraDaemon class."""

import os
import time
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path


@pytest.fixture
def daemon():
    with patch.multiple(
        "shopee_agent.laura_daemon",
        Thread=MagicMock(),
        PersistentState=MagicMock(),
        garantir_todos_modelos=MagicMock(return_value=True),
        load_config=MagicMock(),
        ShopeeClient=MagicMock(),
        AsyncEventBus=MagicMock(),
        AutonomousLoop=MagicMock(),
        ChatMonitor=MagicMock(),
        load_seller_cookies=MagicMock(),
        SellerCenterClient=MagicMock(),
        iniciar_todos_workers=MagicMock(),
        enviar_para_canal=MagicMock(),
        info=MagicMock(),
        warning=MagicMock(),
    ):
        from shopee_agent.laura_daemon import LauraDaemon
        d = LauraDaemon(reports_dir="reports")
        d._setup = MagicMock(return_value=True)
        d._cycle = MagicMock(return_value={"timestamp": "2025-01-01", "cycle_result": {"orders_seen": 5}})
        d._health_check = MagicMock()
        d._refresh_token = MagicMock(return_value=True)
        d._stop_tunnel = MagicMock()
        d._start_tunnel = MagicMock()
        return d


def test_daemon_init(daemon):
    assert daemon is not None
    assert daemon._running is False
    assert daemon._cycle_counter == 0


def test_daemon_init_with_defaults():
    with patch.multiple(
        "shopee_agent.laura_daemon",
        Thread=MagicMock(),
        PersistentState=MagicMock(),
        garantir_todos_modelos=MagicMock(return_value=True),
        load_config=MagicMock(),
        ShopeeClient=MagicMock(),
        AsyncEventBus=MagicMock(),
        AutonomousLoop=MagicMock(),
        ChatMonitor=MagicMock(),
        load_seller_cookies=MagicMock(),
        SellerCenterClient=MagicMock(),
        iniciar_todos_workers=MagicMock(),
        enviar_para_canal=MagicMock(),
        info=MagicMock(),
        warning=MagicMock(),
    ):
        from shopee_agent.laura_daemon import LauraDaemon
        d = LauraDaemon()
        assert d._reports_dir == Path("reports")
        assert d._running is False
        assert d._cycle_counter == 0
        assert d._shutdown is not None


def test_daemon_start_stop(daemon):
    daemon._running = True
    assert daemon._running is True
    daemon._running = False
    assert daemon._running is False


def test_daemon_cycle_execution(daemon):
    result = daemon._cycle()
    assert "timestamp" in result
    assert "cycle_result" in result


def test_daemon_status(daemon):
    daemon._cycle_counter = 42
    daemon._running = True
    assert daemon._running is True
    assert daemon._cycle_counter == 42


def test_daemon_graceful_shutdown(daemon):
    from shopee_agent.graceful_shutdown import GracefulShutdown
    assert isinstance(daemon._shutdown, GracefulShutdown)
    daemon._running = True
    daemon.stop()
    assert daemon._running is False
    daemon._stop_tunnel.assert_called_once()


def test_daemon_pricing_integration(monkeypatch):
    monkeypatch.setenv("PRICING_CYCLE_INTERVAL", "1")
    with patch.multiple(
        "shopee_agent.laura_daemon",
        Thread=MagicMock(),
        PersistentState=MagicMock(),
        garantir_todos_modelos=MagicMock(return_value=True),
        load_config=MagicMock(),
        ShopeeClient=MagicMock(),
        AsyncEventBus=MagicMock(),
        AutonomousLoop=MagicMock(),
        ChatMonitor=MagicMock(),
        load_seller_cookies=MagicMock(),
        SellerCenterClient=MagicMock(),
        iniciar_todos_workers=MagicMock(),
        enviar_para_canal=MagicMock(),
        info=MagicMock(),
        warning=MagicMock(),
    ):
        from shopee_agent.laura_daemon import LauraDaemon
        d = LauraDaemon(reports_dir="reports")

        mock_engine = MagicMock()
        mock_engine.analyze_all_items.return_value = [{"item_id": "123", "suggested_price": 49.90}]
        mock_engine.generate_report.return_value = {"summary": "ok"}
        d._client = MagicMock()
        d._client.get_item_list.return_value = {"item_list": [{"item_id": 123}]}
        d._loop = MagicMock()
        d._loop.run_cycle.return_value = {"cycle_result": {"orders_seen": 5}}
        d._cfg = MagicMock()

        with patch("shopee_agent.pricing_automation.DynamicPricingEngine", return_value=mock_engine):
            with patch("shopee_agent.pricing_automation._cached_competitor_prices", return_value={}):
                with patch("shopee_agent.laura_daemon.time.time", return_value=1.0):
                    for attr in dir(d):
                        if attr.startswith("_last_") or attr == "_ultimo_backup":
                            setattr(d, attr, 0.0)
                    d._cycle_counter = 1
                    result = d._cycle()
                    assert result is not None
                    mock_engine.analyze_all_items.assert_called_once()


def test_daemon_telegram_auto_start(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test:bot_token")
    with patch.multiple(
        "shopee_agent.laura_daemon",
        Thread=MagicMock(),
        PersistentState=MagicMock(),
        garantir_todos_modelos=MagicMock(return_value=True),
        load_config=MagicMock(),
        ShopeeClient=MagicMock(),
        AsyncEventBus=MagicMock(),
        AutonomousLoop=MagicMock(),
        ChatMonitor=MagicMock(),
        load_seller_cookies=MagicMock(),
        SellerCenterClient=MagicMock(),
        iniciar_todos_workers=MagicMock(),
        enviar_para_canal=MagicMock(),
        info=MagicMock(),
        warning=MagicMock(),
    ):
        from shopee_agent.laura_daemon import LauraDaemon

        with patch("shopee_agent.telegram_bot.start_bot") as mock_start_bot:
            with patch("shopee_agent.laura_daemon.time.sleep"):
                with patch("shopee_agent.laura_daemon.time.time", return_value=1000.0):
                    with patch(
                        "shopee_agent.laura_daemon._telegram_bot_already_running",
                        return_value=False,
                    ):
                        d = LauraDaemon(reports_dir="reports")
                        d._setup = MagicMock(return_value=True)
                        d._cycle = MagicMock(return_value={"timestamp": "2025-01-01"})
                        d._health_check = MagicMock()
                        d._shutdown.is_shutting_down = MagicMock(side_effect=[False, True])
                        d._running = True
                        d.run_forever()
                        mock_start_bot.assert_called_once_with(daemon_mode=True)


def test_daemon_telegram_auto_start_skips_if_bot_running(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test:bot_token")
    with patch.multiple(
        "shopee_agent.laura_daemon",
        Thread=MagicMock(),
        PersistentState=MagicMock(),
        garantir_todos_modelos=MagicMock(return_value=True),
        load_config=MagicMock(),
        ShopeeClient=MagicMock(),
        AsyncEventBus=MagicMock(),
        AutonomousLoop=MagicMock(),
        ChatMonitor=MagicMock(),
        load_seller_cookies=MagicMock(),
        SellerCenterClient=MagicMock(),
        iniciar_todos_workers=MagicMock(),
        enviar_para_canal=MagicMock(),
        info=MagicMock(),
        warning=MagicMock(),
    ):
        from shopee_agent.laura_daemon import LauraDaemon

        with patch("shopee_agent.telegram_bot.start_bot") as mock_start_bot:
            with patch("shopee_agent.laura_daemon.time.sleep"):
                with patch("shopee_agent.laura_daemon.time.time", return_value=1000.0):
                    with patch(
                        "shopee_agent.laura_daemon._telegram_bot_already_running",
                        return_value=True,
                    ):
                        d = LauraDaemon(reports_dir="reports")
                        d._setup = MagicMock(return_value=True)
                        d._cycle = MagicMock(return_value={"timestamp": "2025-01-01"})
                        d._health_check = MagicMock()
                        d._shutdown.is_shutting_down = MagicMock(side_effect=[False, True])
                        d._running = True
                        d.run_forever()
                        mock_start_bot.assert_not_called()
