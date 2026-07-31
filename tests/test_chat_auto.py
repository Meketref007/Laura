"""
test_chat_auto.py - Testes para o módulo de respostas automáticas de chat
"""

from unittest.mock import MagicMock
import pytest

from shopee_agent.chat_auto import ChatAutomation, PREDEFINED_RESPONSES


@pytest.fixture
def mock_client():
    """Mock do cliente Shopee"""
    return MagicMock()


@pytest.fixture
def chat_automation(mock_client, tmp_path):
    """Instância de ChatAutomation para testes"""
    return ChatAutomation(
        client=mock_client,
        access_token="test_token",
        shop_id=123,
        reports_dir=tmp_path,
        use_ollama=False,
        human_approval=False,  # Resposta direta sem aprovacao humana
    )


class TestChatAutomationClassification:
    """Testes de classificação de mensagens"""

    def test_classify_rastreamento(self, chat_automation):
        """Testa classificação de mensagem sobre rastreamento"""
        msg = "Olá, onde está meu pedido? Qual o status do rastreamento?"
        result = chat_automation._classify_message_heuristic(msg)
        
        assert result.classified_intent == "rastreamento"
        assert result.should_respond is True
        assert result.confidence >= 0.8

    def test_classify_prazo(self, chat_automation):
        """Testa classificação de mensagem sobre prazo"""
        msg = "Qual é o prazo? Quantos dias leva?"
        result = chat_automation._classify_message_heuristic(msg)
        
        assert result.classified_intent == "prazo"
        assert result.should_respond is True
        assert result.confidence >= 0.8

    def test_classify_cancelamento(self, chat_automation):
        """Testa classificação de mensagem sobre cancelamento"""
        msg = "Quero cancelar meu pedido, como faço?"
        result = chat_automation._classify_message_heuristic(msg)
        
        assert result.classified_intent == "cancelamento"
        assert result.should_respond is True
        assert result.confidence >= 0.8

    def test_classify_produto_info(self, chat_automation):
        """Testa classificação de dúvida sobre produto"""
        msg = "Qual é o tamanho deste produto? Que cores tem?"
        result = chat_automation._classify_message_heuristic(msg)
        
        assert result.classified_intent == "produto_info"
        assert result.should_respond is True
        assert result.confidence >= 0.8

    def test_classify_short_message(self, chat_automation):
        """Testa classificação de mensagem muito curta"""
        msg = "oi"
        result = chat_automation._classify_message_heuristic(msg)
        
        assert result.classified_intent == "outro"
        assert result.should_respond is False

    def test_classify_unknown(self, chat_automation):
        """Testa classificação de mensagem desconhecida"""
        msg = "Quanto custa a manutenção do ar condicionado?"
        result = chat_automation._classify_message_heuristic(msg)
        
        assert result.classified_intent == "outro"
        assert result.should_respond is False


class TestChatAutomationResponses:
    """Testes de envio de respostas automáticas"""

    def test_respond_to_rastreamento(self, chat_automation, mock_client):
        """Testa envio de resposta automática para rastreamento"""
        # Mock da resposta bem-sucedida
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.send_chat_message.return_value = mock_response

        result = chat_automation.classify_and_respond(
            conversation_id="conv_123",
            buyer_id="buyer_456",
            message_text="Onde está meu pedido?",
        )

        # Verificar que a mensagem foi classificada como rastreamento
        assert result.classified_intent == "rastreamento"
        
        # Verificar que send_chat_message foi chamado
        mock_client.send_chat_message.assert_called_once()
        call_kwargs = mock_client.send_chat_message.call_args.kwargs
        assert call_kwargs["buyer_id"] == "buyer_456"
        assert "entrega" in call_kwargs["message"].lower() or "rastreamento" in call_kwargs["message"].lower()

    def test_no_response_for_short_message(self, chat_automation, mock_client):
        """Testa que não envia resposta para mensagens muito curtas"""
        result = chat_automation.classify_and_respond(
            conversation_id="conv_123",
            buyer_id="buyer_456",
            message_text="hi",
        )

        # Verificar que não enviou mensagem
        mock_client.send_chat_message.assert_not_called()
        assert result.should_respond is False

    def test_log_response_created(self, chat_automation, tmp_path):
        """Testa que o log de respostas é criado"""
        mock_client = MagicMock()
        chat_auto = ChatAutomation(
            client=mock_client,
            access_token="test_token",
            shop_id=123,
            reports_dir=tmp_path,
            use_ollama=False,
            human_approval=False,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.send_chat_message.return_value = mock_response

        chat_auto.classify_and_respond(
            conversation_id="conv_123",
            buyer_id="buyer_456",
            message_text="Onde está meu pedido?",
        )

        # Verificar que o arquivo de log foi criado
        log_path = tmp_path / "laura_chat_auto_log.jsonl"
        assert log_path.exists()

        # Ler e verificar conteúdo do log
        import json
        with log_path.open("r") as f:
            lines = f.readlines()
            assert len(lines) > 0
            first_entry = json.loads(lines[0])
            assert first_entry["conversation_id"] == "conv_123"
            assert first_entry["buyer_id"] == "buyer_456"
            assert first_entry["classified_intent"] == "rastreamento"


class TestPredefinedResponses:
    """Testes de respostas pré-definidas"""

    def test_all_predefined_responses_exist(self):
        """Testa que todas as respostas pré-definidas existem"""
        required_intents = ["rastreamento", "prazo", "cancelamento", "produto_info", "outro"]
        for intent in required_intents:
            assert intent in PREDEFINED_RESPONSES
            assert len(PREDEFINED_RESPONSES[intent]) > 0

    def test_response_formatting(self):
        """Testa que as respostas têm bom formato"""
        for intent, response in PREDEFINED_RESPONSES.items():
            if intent == "reclamacao":
                continue  # Gerado dinamicamente com OCR
            # Cada resposta deve ter pelo menos 20 caracteres
            assert len(response) >= 20, f"Response for {intent} is too short"
            # Deve ter quebra de linha ou espaçamento
            assert "\n" in response or len(response) > 100
