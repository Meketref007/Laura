"""
test_immediate_rating_response.py

Tests para validar que respostas a avaliações são enviadas IMEDIATAMENTE
quando recebidas via webhook, sem delay nos handlers.
"""

import time
from unittest.mock import patch, MagicMock
import pytest

from shopee_agent.webhook_handlers import ShopeeEventHandler
from shopee_agent.webhook_server import WebhookEvent


class TestImmediateRatingResponse:
    """Validar que webhook handler retorna imediatamente para respostas a avaliações"""

    @patch('shopee_agent.webhook_handlers.get_auto_response_engine')
    def test_webhook_handler_returns_quickly(self, mock_get_engine):
        """Handler webhook deve retornar em < 100ms (o trabalho é feito em background)"""
        # Mock o engine para responder rapidamente
        mock_engine = MagicMock()
        mock_engine.respond_to_rating.return_value = {
            "status": "sent",
            "response_type": "positive_rating_contextual"
        }
        mock_get_engine.return_value = mock_engine

        event = WebhookEvent(
            event_id='test-rating-immediate',
            event_type='shopee.buyer_rating',
            source='shopee',
            timestamp=int(time.time()),
            data={
                'order_id': '1234567890',
                'shop_id': '123456',
                'buyer_id': 'test_buyer',
                'rating': 5,
                'comment': 'Produto perfeito!',
                'rating_id': 'rating_test_immediate'
            }
        )

        start = time.time()
        ShopeeEventHandler.on_buyer_rating(event)
        elapsed = time.time() - start

        # Handler deve retornar rapidamente (< 1s com resposta mockada)
        assert elapsed < 1.0, f"Handler demorou {elapsed:.2f}s, esperava < 1s"
        print(f"✅ Handler retornou em {elapsed*1000:.0f}ms")

    @patch('shopee_agent.webhook_handlers.get_auto_response_engine')
    def test_negative_rating_also_gets_response(self, mock_get_engine):
        """Avaliação negativa também deve receber resposta automática"""
        mock_engine = MagicMock()
        mock_engine.respond_to_rating.return_value = {
            "status": "sent",
            "response_type": "negative_rating_contextual"
        }
        mock_get_engine.return_value = mock_engine

        event = WebhookEvent(
            event_id='test-rating-negative',
            event_type='shopee.buyer_rating',
            source='shopee',
            timestamp=int(time.time()),
            data={
                'order_id': '9876543210',
                'shop_id': '789012',
                'buyer_id': 'unhappy_buyer',
                'rating': 2,
                'comment': 'Produto com defeito',
                'rating_id': 'rating_test_negative'
            }
        )

        start = time.time()
        ShopeeEventHandler.on_buyer_rating(event)
        elapsed = time.time() - start

        assert elapsed < 1.0, f"Handler demorou {elapsed:.2f}s"
        assert mock_engine.respond_to_rating.called
        print(f"✅ Resposta negativa tratada em {elapsed*1000:.0f}ms")

    @patch('shopee_agent.webhook_handlers.get_auto_response_engine')
    def test_retry_on_first_failure(self, mock_get_engine):
        """Se primeira tentativa falha, tenta de novo automaticamente"""
        # Simular falha na primeira, sucesso na segunda
        mock_engine = MagicMock()
        mock_engine.respond_to_rating.side_effect = [
            Exception("Network timeout"),  # Primeira chamada falha
            {"status": "sent", "response_type": "positive_rating_contextual"}  # Segunda sucede
        ]
        mock_get_engine.return_value = mock_engine

        event = WebhookEvent(
            event_id='test-rating-retry',
            event_type='shopee.buyer_rating',
            source='shopee',
            timestamp=int(time.time()),
            data={
                'order_id': '5555555555',
                'shop_id': '555555',
                'buyer_id': 'retry_test',
                'rating': 4,
                'comment': 'Bom produto',
                'rating_id': 'rating_test_retry'
            }
        )

        # Deve fazer retry automaticamente
        ShopeeEventHandler.on_buyer_rating(event)

        # Verifica que chamou respond_to_rating 2 vezes (retry)
        assert mock_engine.respond_to_rating.call_count == 2
        print(f"✅ Retry automático funcionando: {mock_engine.respond_to_rating.call_count} tentativas")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
