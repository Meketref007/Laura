from shopee_agent.telegram_narrator import narrador


def test_narrador_novo_pedido_uses_friendlier_language(monkeypatch):
    captured = {}

    def fake_send(kind, level, title, detail=""):
        captured["kind"] = kind
        captured["level"] = level
        captured["title"] = title
        captured["detail"] = detail

    monkeypatch.setattr(narrador, "_send", fake_send)

    narrador.novo_pedido(
        "260508SUGRJ4V2",
        1500.0,
        status="READY_TO_SHIP",
        buyer="joao_silva",
        product="Camiseta Premium",
        quantity=2,
    )

    assert captured["kind"] == "pedido"
    assert captured["title"] == "Pedido recebido: `260508SUGRJ4V2`"
    assert "Produto: Camiseta Premium" in captured["detail"]
    assert "Quantidade: 2" in captured["detail"]
    assert "Cliente: joao_silva" in captured["detail"]
    assert "Situação: pronto para envio" in captured["detail"]
    assert "Valor estimado: R$ 1500.00" in captured["detail"]
