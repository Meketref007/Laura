"""Tests for SellerCenterAutomator (mocked browser)."""

import csv
import io
import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


@pytest.fixture
def automator():
    from shopee_agent.seller_center_full import SellerCenterAutomator
    return SellerCenterAutomator(headless=True)


@pytest.fixture
def mock_browser():
    page = MagicMock()
    page.evaluate = MagicMock(return_value=json.dumps({"products": [{"id": "123", "name": "Test Product"}]}))
    page.inner_text = MagicMock(return_value="")
    page.title = PropertyMock(return_value="Test Page")
    page.url = PropertyMock(return_value="https://seller.shopee.com.br/portal/product/list")
    return page


def test_automator_init(automator):
    assert automator is not None
    assert automator._headless is True
    assert automator.BASE_URL == "https://seller.shopee.com.br"


def test_list_products(automator, mock_browser):
    with patch.object(automator, "_browser") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = mock_browser
        products = automator.list_products()
        assert len(products) >= 1


def test_get_product_detail(automator, mock_browser):
    mock_browser.evaluate = MagicMock(return_value=json.dumps({"product": {"name": "Prod Test", "price": 29.90}}))
    with patch.object(automator, "_browser") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = mock_browser
        detail = automator.get_product_detail("item_123")
        assert detail["item_id"] == "item_123"


def test_list_orders(automator, mock_browser):
    mock_browser.evaluate = MagicMock(return_value=json.dumps({"orders": [{"order_sn": "ORD001"}]}))
    with patch.object(automator, "_browser") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = mock_browser
        orders = automator.list_orders()
        assert len(orders) >= 1


def test_get_pending_shipments(automator, mock_browser):
    mock_browser.evaluate = MagicMock(return_value=json.dumps({"orders": [{"order_sn": "ORD002", "status": "pending"}]}))
    with patch.object(automator, "_browser") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = mock_browser
        pending = automator.get_pending_shipments()
        assert isinstance(pending, list)


def test_get_account_balance(automator, mock_browser):
    mock_browser.evaluate = MagicMock(return_value=json.dumps({"balance": "R$ 1.500,00"}))
    with patch.object(automator, "_browser") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = mock_browser
        balance = automator.get_account_balance()
        assert "balance" in balance


def test_export_products_to_csv(automator, mock_browser, tmp_path):
    mock_browser.evaluate = MagicMock(return_value=json.dumps({"products": [{"id": "1", "name": "P1", "price": "10"}, {"id": "2", "name": "P2", "price": "20"}]}))
    filepath = str(tmp_path / "products.csv")
    with patch.object(automator, "_browser") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = mock_browser
        result = automator.export_products_to_csv(filepath)
        assert result == filepath
        import os
        assert os.path.exists(filepath)
        with open(filepath, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) >= 1
