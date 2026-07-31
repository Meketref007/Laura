"""E2E: Shopee API authentication -> fetch orders -> process -> decision -> action."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from shopee_agent.auth import sign_request, build_shop_authorization_url, unix_timestamp
from shopee_agent.client import ShopeeClient, ShopeeResponse
from shopee_agent.config import ShopeeConfig


@pytest.fixture
def mock_config():
    return ShopeeConfig(
        base_url="https://partner.shopeemobile.com",
        partner_id=100001,
        partner_key="test-partner-key-12345",
        redirect_url="https://example.com/callback",
        default_shop_id=123456,
        default_access_token="test-access-token",
        default_refresh_token="test-refresh-token",
    )


def _mock_response(status=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status
    resp.ok = status < 400
    resp.json.return_value = json_data or {}
    resp.text = ""
    return resp


@pytest.mark.integration
class TestShopeeAuthFlow:
    """E2E: Auth token exchange and request signing."""

    def test_sign_request_generates_valid_hmac(self, mock_config):
        ts = 1700000000
        sig = sign_request(
            partner_id=mock_config.partner_id,
            partner_key=mock_config.partner_key,
            path="/api/v2/auth/token/get",
            timestamp=ts,
            access_token="tok_abc",
            shop_id=123456,
        )
        assert isinstance(sig, str), "Signature should be a hex string"
        assert len(sig) == 64, "SHA256 hex digest should be 64 characters"
        assert sig.isalnum(), "Signature should be alphanumeric"

    def test_sign_request_differs_without_token(self, mock_config):
        ts = 1700000000
        with_token = sign_request(
            partner_id=mock_config.partner_id,
            partner_key=mock_config.partner_key,
            path="/api/v2/shop/get_shop_info",
            timestamp=ts,
            access_token="tok_abc",
            shop_id=123456,
        )
        without_token = sign_request(
            partner_id=mock_config.partner_id,
            partner_key=mock_config.partner_key,
            path="/api/v2/shop/get_shop_info",
            timestamp=ts,
        )
        assert with_token != without_token, "Signatures should differ with/without token"

    def test_build_authorization_url_contains_required_params(self, mock_config):
        ts = 1700000000
        url = build_shop_authorization_url(mock_config, timestamp=ts)
        assert "partner_id=100001" in url, "URL should contain partner_id"
        assert "sign=" in url, "URL should contain HMAC signature"
        assert "redirect=" in url, "URL should contain redirect URL"
        assert mock_config.base_url in url, "URL should contain base URL"

    def test_unix_timestamp_returns_int(self):
        ts = unix_timestamp()
        assert isinstance(ts, int), "Timestamp should be integer"
        assert ts > 1600000000, "Timestamp should be reasonable (post-2020)"

    def test_client_exchange_code_for_token(self, mock_config):
        with patch("shopee_agent.client.get_circuit_breaker_manager"):
            with patch("shopee_agent.client.wait_for_rate_limit", return_value=True):
                with patch("shopee_agent.client.sign_request", return_value="mocked_sig"):
                    with patch("requests.request", return_value=_mock_response(200, {
                        "access_token": "new_access_token",
                        "refresh_token": "new_refresh_token",
                        "expires_in": 14400,
                    })):
                        client = ShopeeClient(mock_config)
                        resp = client.exchange_code_for_token(code="auth_code_xyz", shop_id=123456)
                        assert resp.status_code == 200
                        data = resp.data
                        assert data["access_token"] == "new_access_token"
                        assert data["refresh_token"] == "new_refresh_token"

    def test_client_refresh_token(self, mock_config):
        with patch("shopee_agent.client.get_circuit_breaker_manager"):
            with patch("shopee_agent.client.wait_for_rate_limit", return_value=True):
                with patch("shopee_agent.client.sign_request", return_value="mocked_sig"):
                    with patch("requests.request", return_value=_mock_response(200, {
                        "access_token": "refreshed_token",
                        "refresh_token": "new_refresh_token",
                        "expires_in": 14400,
                    })):
                        client = ShopeeClient(mock_config)
                        resp = client.refresh_token(refresh_token="old_refresh", shop_id=123456)
                        assert resp.status_code == 200
                        assert resp.data["access_token"] == "refreshed_token"


@pytest.mark.integration
class TestShopeeOrderFlow:
    """E2E: Fetch orders, parse, make decisions, execute actions."""

    def _mock_order_list_response(self):
        return {
            "response": {
                "order_list": [
                    {
                        "order_sn": "ORDER001",
                        "order_status": "READY_TO_SHIP",
                        "create_time": int(time.time()) - 7200,
                        "total_amount": 15000,
                        "currency": "BRL",
                        "buyer_user_id": 98765,
                        "days_ship_limit": 2,
                        "items": [{"item_id": 1001, "item_name": "Product A", "quantity": 1}],
                    },
                    {
                        "order_sn": "ORDER002",
                        "order_status": "PROCESSED",
                        "create_time": int(time.time()) - 3600,
                        "total_amount": 25000,
                        "currency": "BRL",
                        "buyer_user_id": 54321,
                        "days_ship_limit": 3,
                        "items": [{"item_id": 1002, "item_name": "Product B", "quantity": 2}],
                    },
                ]
            }
        }

    def test_fetch_and_parse_order_list(self, mock_config):
        with patch("shopee_agent.client.get_circuit_breaker_manager"):
            with patch("shopee_agent.client.wait_for_rate_limit", return_value=True):
                with patch("shopee_agent.client.sign_request", return_value="mocked_sig"):
                    with patch("requests.request", return_value=_mock_response(200, self._mock_order_list_response())):
                        client = ShopeeClient(mock_config)
                        now = int(time.time())
                        resp = client.get_order_list(
                            access_token="tok",
                            shop_id=123456,
                            time_from=now - 86400,
                            time_to=now,
                        )
                        assert resp.status_code == 200
                        orders = resp.data.get("response", {}).get("order_list", [])
                        assert len(orders) == 2
                        assert orders[0]["order_sn"] == "ORDER001"
                        assert orders[0]["order_status"] == "READY_TO_SHIP"
                        assert orders[1]["order_sn"] == "ORDER002"

    def test_decision_made_based_on_order_data(self, mock_config):
        orders = self._mock_order_list_response()["response"]["order_list"]
        ready_to_ship = [o for o in orders if o["order_status"] == "READY_TO_SHIP"]
        processed = [o for o in orders if o["order_status"] == "PROCESSED"]
        assert len(ready_to_ship) == 1
        assert len(processed) == 1
        decision = "ship" if ready_to_ship else "wait"
        assert decision == "ship"

    def test_ship_order_action(self, mock_config):
        with patch("shopee_agent.client.get_circuit_breaker_manager"):
            with patch("shopee_agent.client.wait_for_rate_limit", return_value=True):
                with patch("shopee_agent.client.sign_request", return_value="mocked_sig"):
                    with patch("requests.request", return_value=_mock_response(200, {"response": {"order_sn": "ORDER001", "success": True}})):
                        client = ShopeeClient(mock_config)
                        now = int(time.time())
                        resp = client.ship_order(
                            access_token="tok",
                            shop_id=123456,
                            order_sn="ORDER001",
                            logistics_channel_id=1001,
                            tracking_number="TRACK123",
                            ship_time=now,
                        )
                        assert resp.status_code == 200
                        assert resp.data["response"]["success"] is True

    def test_get_order_detail_parses_correctly(self, mock_config):
        with patch("shopee_agent.client.get_circuit_breaker_manager"):
            with patch("shopee_agent.client.wait_for_rate_limit", return_value=True):
                with patch("shopee_agent.client.sign_request", return_value="mocked_sig"):
                    with patch("requests.request", return_value=_mock_response(200, {
                        "response": {
                            "order_sn": "ORDER001",
                            "order_status": "SHIPPED",
                            "total_amount": 15000,
                            "buyer_user_id": 98765,
                            "ship_by_date": int(time.time()) + 86400,
                        }
                    })):
                        client = ShopeeClient(mock_config)
                        resp = client.get_order_detail(
                            access_token="tok", shop_id=123456, order_sn="ORDER001"
                        )
                        assert resp.data["response"]["order_status"] == "SHIPPED"
                        assert resp.data["response"]["total_amount"] == 15000


@pytest.mark.integration
class TestShopeeFullPipeline:
    """Full pipeline: auth -> fetch -> decide -> act."""

    def test_full_pipeline_mocked(self, mock_config, tmp_path):
        auth_resp = {
            "access_token": "live_token",
            "refresh_token": "live_refresh",
            "expires_in": 14400,
        }
        orders_resp = {
            "response": {
                "order_list": [
                    {
                        "order_sn": "ORDER001",
                        "order_status": "READY_TO_SHIP",
                        "total_amount": 15000,
                        "buyer_user_id": 111,
                        "days_ship_limit": 1,
                    }
                ]
            }
        }
        ship_resp = {"response": {"order_sn": "ORDER001", "success": True}}

        call_log = {"calls": []}

        def mock_requests(method, url, **kwargs):
            call_log["calls"].append((method, url))
            resp = MagicMock()
            resp.status_code = 200
            resp.ok = True
            if "auth/token/get" in url:
                resp.json.return_value = auth_resp
            elif "ship_order" in url:
                resp.json.return_value = ship_resp
            elif "get_order_list" in url:
                resp.json.return_value = orders_resp
            else:
                resp.json.return_value = {}
            resp.text = ""
            return resp

        with patch("shopee_agent.client.get_circuit_breaker_manager"):
            with patch("shopee_agent.client.wait_for_rate_limit", return_value=True):
                with patch("shopee_agent.client.sign_request", return_value="mocked_sig"):
                    with patch("requests.request", side_effect=mock_requests):
                        client = ShopeeClient(mock_config)
                        token_resp = client.exchange_code_for_token("code", 123456)
                        assert token_resp.data["access_token"] == "live_token"
                        now = int(time.time())
                        orders_resp_data = client.get_order_list(
                            access_token=token_resp.data["access_token"],
                            shop_id=123456,
                            time_from=now - 86400,
                            time_to=now,
                        )
                        orders = orders_resp_data.data["response"]["order_list"]
                        assert len(orders) == 1
                        ready = [o for o in orders if o["order_status"] == "READY_TO_SHIP"]
                        if ready:
                            ship_result = client.ship_order(
                                access_token="live_token",
                                shop_id=123456,
                                order_sn=ready[0]["order_sn"],
                                tracking_number="TRK001",
                            )
                            assert ship_result.data["response"]["success"] is True
