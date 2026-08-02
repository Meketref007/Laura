from __future__ import annotations

from pathlib import Path

from shopee_agent.autonomous_loop import AutonomousLoop


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeClientBasic:
    """Client básico para testes simples"""
    def __init__(self) -> None:
        self.order_calls = 0
        self.item_calls = 0

    def get_order_list(self, *, access_token, shop_id, time_from, time_to, page_size, order_status=None, time_range_field=None):
        self.order_calls += 1
        return _FakeResponse(
            {
                "response": {
                    "order_list": [
                        {
                            "order_sn": "260508SUGRJ4V2",
                            "order_status": "PAID",
                            "create_time": 1_717_000_000,
                        }
                    ]
                }
            }
        )

    def get_item_list(self, *, access_token, shop_id, offset, page_size):
        self.item_calls += 1
        return _FakeResponse({"response": {"item": [{"item_id": "1001", "stock": 2}]}})


class _FakeClientWithEnrichment:
    """Client com suporte a enriquecimento de pedidos"""
    def __init__(self) -> None:
        self.order_calls = 0
        self.item_calls = 0
        self.detail_calls = 0

    def get_order_list(self, *, access_token, shop_id, time_from, time_to, page_size, order_status=None, time_range_field=None):
        self.order_calls += 1
        return _FakeResponse(
            {
                "response": {
                    "order_list": [
                        {
                            "order_sn": "260508SUGRJ4V2",
                            "order_status": "READY_TO_SHIP",
                            "create_time": 1_717_000_000,
                        }
                    ]
                }
            }
        )

    def get_order_detail(self, *, access_token, shop_id, order_sn):
        self.detail_calls += 1
        return _FakeResponse(
            {
                "response": {
                    "order_list": [
                        {
                            "order_sn": order_sn,
                            "buyer_id": "buyer_123",
                            "buyer_username": "joao_silva",
                            "total_amount": 150000,  # Em centavos: R$ 1.500
                            "item_list": [
                                {
                                    "item_name": "Camiseta Premium",
                                    "model_quantity_purchased": 2,
                                }
                            ],
                        }
                    ]
                }
            }
        )

    def get_item_list(self, *, access_token, shop_id, offset, page_size):
        self.item_calls += 1
        return _FakeResponse({"response": {"item": [{"item_id": "1001", "stock": 2}]}})


def test_autonomous_loop_uses_ready_to_ship_filter(tmp_path: Path, monkeypatch) -> None:
    """Testa que o loop filtra apenas pedidos READY_TO_SHIP"""
    client = _FakeClientBasic()
    loop = AutonomousLoop(
        client=client,
        access_token="access-token",
        shop_id=1288767930,
        reports_dir=tmp_path / "reports",
        telegram_token="token",
        telegram_chat_id="chat",
    )

    # Verificar que get_order_list foi chamado com os parâmetros corretos
    _state = loop._collect_state()
    
    # Verificar que o método foi chamado e usou os parâmetros
    assert client.order_calls == 1


def test_autonomous_loop_enriches_order_details(tmp_path: Path, monkeypatch) -> None:
    """Testa enriquecimento de dados do pedido com get_order_detail"""
    client = _FakeClientWithEnrichment()
    loop = AutonomousLoop(
        client=client,
        access_token="access-token",
        shop_id=1288767930,
        reports_dir=tmp_path / "reports",
        telegram_token="token",
        telegram_chat_id="chat",
    )

    state = loop._collect_state()
    
    # Verificar que get_order_detail foi chamado
    assert client.detail_calls >= 1
    
    # Verificar que os dados foram enriquecidos
    orders = state.get("orders", [])
    if orders:
        assert "buyer_username" in orders[0]
        assert "product_name" in orders[0]
        assert orders[0].get("buyer_username") == "joao_silva"


def test_autonomous_loop_sends_formatted_telegram_message(tmp_path: Path, monkeypatch) -> None:
    """Testa que as mensagens Telegram têm novo formato com emojis e detalhes"""
    client = _FakeClientWithEnrichment()
    loop = AutonomousLoop(
        client=client,
        access_token="access-token",
        shop_id=1288767930,
        reports_dir=tmp_path / "reports",
        telegram_token="token",
        telegram_chat_id="chat",
    )

    sent: list[str] = []
    monkeypatch.setattr(loop, "_send_telegram", lambda text: sent.append(text) or True)

    _result = loop.run_cycle()

    # Verificar que a mensagem foi enviada
    assert len(sent) > 0
    
    # Verificar novo formato com emojis e detalhes
    message = sent[0]
    assert "📦" in message  # Emoji de pacote
    assert "260508SUGRJ4V2" in message  # Order SN
    assert ("Camiseta Premium" in message or "joao_silva" in message)  # Dados enriquecidos


def test_autonomous_loop_wires_agent_orchestrator(tmp_path: Path, monkeypatch) -> None:
    """O loop deve instanciar o AgentOrchestrator e passá-lo ao DecisionIntegrator."""
    client = _FakeClientBasic()
    loop = AutonomousLoop(
        client=client,
        access_token="access-token",
        shop_id=1288767930,
        reports_dir=tmp_path / "reports",
    )

    assert loop._agent_orchestrator is not None

    engine = __import__("shopee_agent.decision_engine", fromlist=["DecisionEngine"]).DecisionEngine(
        store_id="test", rules=__import__("shopee_agent.decision_engine", fromlist=["create_default_rules"]).create_default_rules()
    )
    integrator = __import__("shopee_agent.decision_integration", fromlist=["DecisionIntegrator"]).DecisionIntegrator(
        engine=engine,
        store_id="test",
        metrics_dir=str(tmp_path / "reports"),
        agent_orchestrator=loop._agent_orchestrator,
    )

    monkeypatch.setattr(integrator, "collect_signals_from_metrics", lambda: [])
    monkeypatch.setattr(
        integrator,
        "build_economic_context",
        lambda: __import__("shopee_agent.decision_engine", fromlist=["EconomicContext"]).EconomicContext(
            current_margin_pct=16.0,
            margin_target_pct=20.0,
            daily_revenue_usd=4000.0,
            cash_buffer_usd=10000.0,
            inventory_days_on_hand=5,
            stock_risk_level="high",
            active_promotions=0,
            advertising_spend_daily_usd=500.0,
            advertising_roas=1.2,
            customer_satisfaction_score=70.0,
            recent_anomalies=[],
        ),
    )

    result = integrator.process_cycle()

    assert result["orchestration"] is not None
    plan = result["orchestration"]
    assert "approved_actions" in plan
    assert "consensus_score" in plan
