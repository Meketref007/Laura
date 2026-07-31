"""
Testes basicos offline para os modulos principais da Laura.
Uso: pytest tests/test_core.py -v
"""
import json
from pathlib import Path

import pytest

from shopee_agent.seller_center_actions import SellerCenterActions


class TestSellerCenterActions:

    def test_list_actions_returns_dict(self):
        from shopee_agent.seller_center_actions import list_actions
        actions = list_actions()
        assert isinstance(actions, dict)
        assert len(actions) > 30
        assert "get_shop_overview" in actions
        assert "get_orders" in actions

    def test_execute_action_unknown(self):
        from shopee_agent.seller_center_actions import execute_action
        with pytest.raises(ValueError, match="Acao desconhecida"):
            execute_action("nao_existe")

    def test_execute_action_no_auth(self):
        from shopee_agent.seller_center_actions import execute_action
        result = execute_action("get_shop_overview")
        assert isinstance(result, str)


class TestDryRun:

    def test_dry_run_env_var(self):
        import os
        assert os.getenv("SELLER_CENTER_DRY_RUN") == "1"

    def test_confirm_or_dry_run_blocks(self, mock_seller_center):
        actions = SellerCenterActions(client=mock_seller_center)
        result = actions._confirm_or_dry_run("teste", {"key": "value"})
        assert result is not None
        assert "DRY RUN" in result

    def test_is_dry_run_default(self, mock_seller_center):
        actions = SellerCenterActions(client=mock_seller_center)
        assert actions._is_dry_run() is True


class TestRatingReplyQueue:

    def test_pending_queue_created(self, tmp_path, monkeypatch):
        from shopee_agent.rating_reply import _enfileirar_resposta, _PENDING_FILE
        monkeypatch.setattr("shopee_agent.rating_reply._PENDING_FILE", str(tmp_path / "pending.jsonl"))
        item = {
            "order_id": 123,
            "comment_id": 456,
            "rating_star": 3,
            "comment": "Produto ok",
            "product_name": "Teste",
        }
        _enfileirar_resposta(item)
        p = tmp_path / "pending.jsonl"
        assert p.exists()
        lines = p.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["comment_id"] == 456
        assert entry["status"] == "pending"


class TestWebhookPayload:

    def test_payload_defaults(self):
        from shopee_agent.webhooks import WebhookPayload
        p = WebhookPayload()
        assert p.text == ""
        assert p.source == "laura"
        assert p.severity == "info"

    def test_payload_with_data(self):
        from shopee_agent.webhooks import WebhookPayload
        p = WebhookPayload(text="teste", severity="critical", metadata={"key": "val"})
        assert p.text == "teste"
        assert p.metadata == {"key": "val"}
