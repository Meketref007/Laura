"""Testes end-to-end do pipeline LLM: keyword matching -> intent -> execucao."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


# Mock da classe LauraTelegramBot para testar _match_keywords
class MockTelegramBot:
    """Simula o suficiente do LauraTelegramBot para testar _match_keywords."""
    _seller_client = MagicMock()

    def _confirm_or_dry_run(self, desc, data):
        return None

    def _execute_seller_action(self, action_name, **params):
        return f"EXECUTED:{action_name}"


# Import the real _match_keywords method
from shopee_agent.telegram_bot import LauraTelegramBot


@pytest.fixture
def bot():
    """Cria uma instancia mockada do bot para testar."""
    b = LauraTelegramBot.__new__(LauraTelegramBot)
    b._seller_client = MagicMock()
    b.seller_actions = MagicMock()
    b.reports_dir = Path("reports")
    b.access_token = "test_token"
    b.shop_id = 123
    b._confirmations = {}
    b.client = MagicMock()
    return b


class TestKeywordMatching:
    def test_holiday_mode_on(self, bot):
        result = bot._match_keywords("ativar modo férias")
        assert result is not None
        assert result[0] == "holiday_mode"
        assert result[1]["on"] is True

    def test_holiday_mode_off(self, bot):
        result = bot._match_keywords("desativar modo férias")
        assert result is not None
        assert result[0] == "holiday_mode"
        assert result[1]["on"] is False

    def test_enable_pickup(self, bot):
        result = bot._match_keywords("ativar retirada pelo comprador")
        assert result is not None
        assert result[0] == "enable_pickup"
        assert result[1]["enable"] is True

    def test_disable_pickup(self, bot):
        result = bot._match_keywords("desativar retirada")
        assert result is not None
        assert result[0] == "enable_pickup"
        assert result[1]["enable"] is False

    def test_reply_to_rating(self, bot):
        result = bot._match_keywords("responder avaliação do pedido 123456789 dizendo obrigado")
        assert result is not None
        assert result[0] == "reply_to_rating"
        assert "comment" in result[1]

    def test_get_status(self, bot):
        result = bot._match_keywords("qual o status da loja")
        assert result is not None
        assert result[0] == "get_status"

    def test_get_orders(self, bot):
        result = bot._match_keywords("mostrar pedidos")
        assert result is not None
        assert result[0] == "get_orders"

    def test_get_inventory(self, bot):
        result = bot._match_keywords("estoque baixo")
        assert result is not None
        assert result[0] == "get_inventory"

    def test_get_financial(self, bot):
        result = bot._match_keywords("qual a margem de lucro")
        assert result is not None
        assert result[0] == "get_financial_summary"

    def test_get_products(self, bot):
        result = bot._match_keywords("meus produtos")
        assert result is not None
        assert result[0] == "get_products"

    def test_get_ratings(self, bot):
        result = bot._match_keywords("avaliações dos clientes")
        assert result is not None
        assert result[0] == "get_ratings"

    def test_get_violations(self, bot):
        result = bot._match_keywords("violações da loja")
        assert result is not None
        assert result[0] == "get_violations"

    def test_get_todo_summary(self, bot):
        result = bot._match_keywords("tarefas pendentes")
        assert result is not None
        assert result[0] == "get_todo_summary"

    def test_get_wallet_balance(self, bot):
        result = bot._match_keywords("saldo da carteira")
        assert result is not None
        assert result[0] == "get_wallet_balance"

    def test_get_chat_messages(self, bot):
        result = bot._match_keywords("mensagens do chat")
        assert result is not None
        assert result[0] == "get_chat_messages"

    def test_get_returns(self, bot):
        result = bot._match_keywords("devoluções")
        assert result is not None
        assert result[0] == "get_returns"

    def test_get_campaigns(self, bot):
        result = bot._match_keywords("campanhas de marketing")
        assert result is not None
        assert result[0] == "get_campaigns"

    def test_get_vouchers(self, bot):
        result = bot._match_keywords("cupons de desconto")
        assert result is not None
        assert result[0] == "get_vouchers"

    def test_get_flash_sales(self, bot):
        result = bot._match_keywords("flash sale")
        assert result is not None
        assert result[0] == "get_flash_sales"

    def test_get_pickup_settings(self, bot):
        result = bot._match_keywords("configuração de retirada")
        assert result is not None
        assert result[0] == "get_pickup_settings"

    def test_get_appeals(self, bot):
        result = bot._match_keywords("recursos de penalidades")
        assert result is not None
        assert result[0] == "get_appeals"

    def test_get_account_health(self, bot):
        result = bot._match_keywords("saúde da conta")
        assert result is not None
        assert result[0] == "get_account_health"

    def test_get_shop_overview(self, bot):
        result = bot._match_keywords("visão geral da loja")
        assert result is not None
        assert result[0] == "get_shop_overview"

    def test_get_rating_dashboard(self, bot):
        result = bot._match_keywords("dashboard de avaliação")
        assert result is not None
        assert result[0] == "get_rating_dashboard"

    def test_list_actions(self, bot):
        result = bot._match_keywords("o que voce faz")
        assert result is not None
        assert result[0] == "list_actions"

    def test_get_help(self, bot):
        result = bot._match_keywords("ajuda")
        assert result is not None
        assert result[0] == "get_help"

    def test_ship_order(self, bot):
        result = bot._match_keywords("enviar pedido 12345678")
        assert result is not None
        assert result[0] == "ship_order"
        assert result[1]["order_sn"] == "12345678"

    def test_update_shipping_setting(self, bot):
        result = bot._match_keywords("configurar frete")
        assert result is not None
        assert result[0] == "update_shipping_setting"

    def test_update_shop_profile(self, bot):
        result = bot._match_keywords("atualizar perfil da loja")
        assert result is not None
        assert result[0] == "update_shop_profile"

    def test_get_shipping_settings(self, bot):
        result = bot._match_keywords("como está o frete")
        assert result is not None
        assert result[0] == "get_shipping_settings"

    def test_pre_order_all(self, bot):
        result = bot._match_keywords("pré-venda de 3 dias")
        assert result is not None
        assert result[0] == "pre_order_all"
        assert result[1]["days"] == 3

    def test_get_email(self, bot):
        result = bot._match_keywords("ver emails")
        assert result is not None
        assert result[0] == "get_email"

    def test_get_product_shipping_channels(self, bot):
        result = bot._match_keywords("canais de envio do produto 123456789")
        assert result is not None
        assert result[0] == "get_product_shipping_channels"
        assert result[1]["item_id"] == 123456789

    def test_set_product_shipping_channel_enable(self, bot):
        result = bot._match_keywords("ativar xpress no produto 123456789")
        assert result is not None
        assert result[0] == "set_product_shipping_channel"
        assert result[1]["item_id"] == 123456789
        assert result[1]["enable"] is True
        assert "xpress" in result[1]["channel"].lower()

    def test_set_product_shipping_channel_disable(self, bot):
        result = bot._match_keywords("desativar retirada no produto 123456789")
        assert result is not None
        assert result[0] == "set_product_shipping_channel"
        assert result[1]["item_id"] == 123456789
        assert result[1]["enable"] is False
        assert "retirada" in result[1]["channel"].lower()

    # --- Bulk shipping channel tests ---

    def test_set_channel_for_all_products_enable(self, bot):
        result = bot._match_keywords("ativar retirada em todos os meus produtos")
        assert result is not None
        assert result[0] == "set_channel_for_all_products"
        assert result[1]["enable"] is True
        assert "retirada" in result[1]["channel"].lower()

    def test_set_channel_for_all_products_disable(self, bot):
        result = bot._match_keywords("desativar xpress em todos os produtos")
        assert result is not None
        assert result[0] == "set_channel_for_all_products"
        assert result[1]["enable"] is False
        assert "xpress" in result[1]["channel"].lower()

    def test_set_channel_for_all_products_without_channel_name(self, bot):
        result = bot._match_keywords("ativar em todos os produtos")
        assert result is not None
        assert result[0] == "set_channel_for_all_products"
        assert result[1]["enable"] is True
        # Default channel is Shopee Xpress

    def test_set_channel_for_all_products_flow(self, bot):
        intent, params = bot._match_keywords("ativar retirada em todos os produtos")
        assert intent == "set_channel_for_all_products"

        response = bot._execute_intent(intent, params)
        assert "Confirmar" in response
        assert "todos" in response.lower()
        assert "retirada" in response.lower()


class TestRagFlow:
    """Testa o fluxo completo: keyword -> intent -> execute -> confirmacao."""

    def test_enable_pickup_flow(self, bot):
        intent, params = bot._match_keywords("ativar retirada")
        assert intent == "enable_pickup"
        assert params["enable"] is True

        response = bot._execute_intent(intent, params)
        assert "Confirmar" in response
        assert "ativar" in response.lower()
        assert "retirada" in response.lower()

    def test_disable_pickup_flow(self, bot):
        intent, params = bot._match_keywords("desativar retirada")
        assert intent == "enable_pickup"
        assert params["enable"] is False

    def test_reply_to_rating_flow(self, bot):
        intent, params = bot._match_keywords("responder avaliação do pedido 123456789")
        assert intent == "reply_to_rating"
        response = bot._execute_intent(intent, params)
        assert "Confirmar" in response
        assert "responder" in response.lower()

    def test_update_shipping_flow(self, bot):
        intent, params = bot._match_keywords("configurar frete")
        assert intent == "update_shipping_setting"
        response = bot._execute_intent(intent, params)
        assert "Confirmar" in response

    def test_read_intent_executes_immediately(self, bot):
        """Leituras nao devem pedir confirmacao."""
        with patch.object(bot, '_execute_seller_action', return_value="OK"):
            intent, params = bot._match_keywords("visão geral da loja")
            response = bot._execute_intent(intent, params)
            assert response is not None


class TestPreOrderAll:
    """Testa o fluxo de colocar todos os produtos sob encomenda (minimo 3 dias na Open API)."""

    def _item_list(self, ids):
        return MagicMock(data={"items": [{"item_id": i} for i in ids]})

    def test_defaults_to_minimum_3_days(self, bot):
        bot.client.get_item_list.return_value = self._item_list([1, 2])
        response = bot._execute_pre_order_all()
        assert "3" in response
        calls = bot.client.update_item.call_args_list
        assert len(calls) == 2
        for call in calls:
            kwargs = call.kwargs
            assert kwargs["days_to_ship"] == 3
            assert kwargs["is_pre_order"] is True

    def test_raises_low_days_to_minimum_3(self, bot):
        bot.client.get_item_list.return_value = self._item_list([1])
        bot._execute_pre_order_all(days=2)
        call = bot.client.update_item.call_args
        assert call.kwargs["days_to_ship"] == 3
        assert call.kwargs["is_pre_order"] is True

    def test_respects_days_greater_than_3(self, bot):
        bot.client.get_item_list.return_value = self._item_list([1])
        bot._execute_pre_order_all(days=5)
        assert bot.client.update_item.call_args.kwargs["days_to_ship"] == 5

    def test_paginates_through_all_items(self, bot):
        bot.client.get_item_list.side_effect = [
            self._item_list(list(range(1, 51))),
            self._item_list(list(range(51, 61))),
        ]
        response = bot._execute_pre_order_all(days=3)
        assert bot.client.update_item.call_count == 60
        assert "60" in response

    def test_keyword_without_days_defaults_to_3(self, bot):
        result = bot._match_keywords("colocar todos sob encomenda")
        assert result is not None
        assert result[0] == "pre_order_all"
        assert result[1]["days"] == 3

    def test_keyword_with_days(self, bot):
        result = bot._match_keywords("pre-venda de 7 dias")
        assert result is not None
        assert result[0] == "pre_order_all"
        assert result[1]["days"] == 7
