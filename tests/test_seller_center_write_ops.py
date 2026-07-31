"""
Testes para write operations do Seller Center.
Usa mocks — nao afeta a loja real.
"""
import pytest
from shopee_agent.seller_center_actions import SellerCenterActions


class TestSellerCenterWriteOps:

    def test_dry_run_blocks_writes_by_default(self, mock_seller_center):
        """DRY_RUN=true (padrao) deve bloquear writes."""
        actions = SellerCenterActions(client=mock_seller_center)
        result = actions.update_shipping_setting( days_to_ship=3 )
        assert "DRY RUN" in result
        assert "nao executada" in result
        mock_seller_center.post.assert_not_called()

    def test_reply_to_rating_dry_run(self, mock_seller_center):
        actions = SellerCenterActions(client=mock_seller_center)
        result = actions.reply_to_rating(order_id=123, comment_id=456, comment="Obrigado!")
        assert "DRY RUN" in result
        mock_seller_center.reply_to_rating.assert_not_called()

    def test_update_shop_profile_dry_run(self, mock_seller_center):
        actions = SellerCenterActions(client=mock_seller_center)
        result = actions.update_shop_profile( shop_name="Nova Loja" )
        assert "DRY RUN" in result

    def test_reply_to_rating_sends_when_dry_run_off(self, mock_seller_center, monkeypatch):
        monkeypatch.setenv("SELLER_CENTER_DRY_RUN", "0")
        actions = SellerCenterActions(client=mock_seller_center)
        result = actions.reply_to_rating(order_id=123, comment_id=456, comment="Obrigado!")
        assert "DRY RUN" not in result
        mock_seller_center.reply_to_rating.assert_called_once_with(123, 456, "Obrigado!")
