"""
Fixtures e mocks para testes offline da Laura.
Uso: pytest tests/ -v
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

# ============================================================================
# Mocks para servicos externos
# ============================================================================


@pytest.fixture(autouse=True)
def mock_env():
    """Define variaveis de ambiente minimas para testes."""
    os.environ.setdefault("LAURA_LLM_MODEL", "tinyllama")
    os.environ.setdefault("SELLER_CENTER_DRY_RUN", "1")
    os.environ.setdefault("RATING_REPLY_AUTO_SEND", "0")
    os.environ.setdefault("LAURA_ALERT_TELEGRAM_BOT_TOKEN", "test:token")


@pytest.fixture
def mock_ollama():
    """Mock do Ollama para testes."""
    with patch("shopee_agent.llm_local.LauraOllamaAnalyzer") as mock:
        instance = mock.return_value
        instance.analyze.return_value = {"raw_response": '{"intent": "outro", "confidence": 0.3}'}
        yield instance


@pytest.fixture
def mock_requests():
    """Mock do requests.session para testes."""
    with patch("requests.Session") as mock:
        session = mock.return_value
        resp = MagicMock()
        resp.status_code = 200
        resp.ok = True
        resp.json.return_value = {"ok": True}
        resp.text = ""
        session.post.return_value = resp
        session.get.return_value = resp
        yield session


@pytest.fixture
def mock_seller_center():
    """Mock do SellerCenterClient."""
    with patch("shopee_agent.seller_center.SellerCenterClient") as mock:
        client = mock.return_value
        client.is_authenticated.return_value = True
        client.get_shop_overview.return_value = {"shop_name": "Loja Teste", "status": "active"}
        client.get_shop_health.return_value = {"health_score": 85}
        client.get_financial_summary.return_value = {"total_balance": 1000.0}
        client.get_violation_records.return_value = []
        client.get_shipping_settings.return_value = {"enabled": True}
        client.get_shop_profile.return_value = {"shop_name": "Loja Teste"}
        client.get_orders.return_value = []
        client.get_ratings.return_value = []
        client.get_wallet_balance.return_value = {"available": 500.0}
        client.reply_to_rating.return_value = True
        yield client


@pytest.fixture
def mock_shopee_client():
    """Mock do ShopeeClient (Open API)."""
    with patch("shopee_agent.client.ShopeeClient") as mock:
        client = mock.return_value
        resp = MagicMock()
        resp.status_code = 200
        resp.ok = True
        resp.data = {"response": {"item_list": []}}
        client.get_item_list.return_value = resp
        client.get_order_list.return_value = resp
        client.get_conversation_list.return_value = resp
        client.send_chat_message.return_value = resp
        yield client


@pytest.fixture
def reports_dir(tmp_path):
    """Diretorio temporario para reports."""
    d = tmp_path / "reports"
    d.mkdir()
    return d
