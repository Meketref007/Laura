from __future__ import annotations

import json
from pathlib import Path

from shopee_agent.telegram_bot import LauraTelegramBot, approve_remediation_case, parse_command


def test_parse_command_with_arg() -> None:
    cmd = parse_command("/aprovar CASE-123")
    assert cmd is not None
    assert cmd.name == "/aprovar"
    assert cmd.arg == "CASE-123"


def test_parse_command_without_slash_returns_none() -> None:
    assert parse_command("status") is None


def test_approve_remediation_case_updates_history_and_audit(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    history_file = reports_dir / "laura_remediation_cases.jsonl"
    history_file.write_text(
        json.dumps(
            {
                "case_id": "case-1",
                "executed": False,
                "created_at": "2026-05-05T00:00:00+00:00",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    ok, message = approve_remediation_case("case-1", reports_dir, approved_by="tester")

    assert ok is True
    assert "Caso aprovado" in message

    saved = history_file.read_text(encoding="utf-8").splitlines()
    assert len(saved) == 1
    row = json.loads(saved[0])
    assert row["executed"] is True
    assert "Approved via Telegram" in row["result"]

    audit_file = reports_dir / "laura_remediation_audit.jsonl"
    assert audit_file.exists()
    audit_row = json.loads(audit_file.read_text(encoding="utf-8").splitlines()[-1])
    assert audit_row["action"] == "approve_remediation"
    assert audit_row["source"] == "telegram_bot"


def test_handle_text_returns_approval_prompt(tmp_path: Path) -> None:
    bot = LauraTelegramBot(
        token="token",
        allowed_chat_id=None,
        shopee_client=object(),
        access_token=None,
        shop_id=None,
        reports_dir=tmp_path / "reports",
    )

    assert "Caso case-7" in bot.handle_text("/aprovar case-7", from_user="tester")


class _ShipClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def ship_order(self, **kwargs):
        self.calls.append(kwargs)
        return object()


class _OrdersClient:
    def get_order_list(self, **kwargs):
        self.calls = getattr(self, "calls", [])
        self.calls.append(kwargs)
        return type(
            "Resp",
            (),
            {
                "data": {
                    "response": {
                        "order_list": [
                            {
                                "order_sn": "260508SUGRJ4V2",
                                "order_status": "READY_TO_SHIP",
                                "product_name": "Camiseta Premium",
                                "product_quantity": 2,
                                "buyer_username": "joao_silva",
                                "total_amount": 150000000,
                                "payment_status": "PAID",
                            }
                        ]
                    }
                }
            },
        )()


def test_handle_text_enviar_order_sn_triggers_ship_order(tmp_path: Path) -> None:
    client = _ShipClient()
    bot = LauraTelegramBot(
        token="token",
        allowed_chat_id=None,
        shopee_client=client,
        access_token="access-token",
        shop_id=1288767930,
        reports_dir=tmp_path / "reports",
    )

    message = bot.handle_text("/enviar_260508SUGRJ4V2", from_user="tester")

    assert "processado para envio" in message
    assert client.calls == [
        {
            "access_token": "access-token",
            "shop_id": 1288767930,
            "order_sn": "260508SUGRJ4V2",
        }
    ]


def test_handle_text_pedidos_formats_friendlier_summary(tmp_path: Path) -> None:
    client = _OrdersClient()
    bot = LauraTelegramBot(
        token="token",
        allowed_chat_id=None,
        shopee_client=client,
        access_token="access-token",
        shop_id=1288767930,
        reports_dir=tmp_path / "reports",
    )

    message = bot.handle_text("/pedidos 1", from_user="tester")

    assert "Pedidos recentes" in message
    assert "Número do pedido" in message or "Pedido" in message
    assert "Situacao: Pronto para envio" in message
    assert "Produto: Camiseta Premium" in message
    assert "Quantidade: 2" in message
    assert "Cliente: joao_silva" in message
    assert "Valor: R$ 1500.00" in message


def test_callback_approve_triggers_approval_and_ack(tmp_path: Path, monkeypatch) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    bot = LauraTelegramBot(
        token="token",
        allowed_chat_id=None,
        shopee_client=object(),
        access_token=None,
        shop_id=None,
        reports_dir=reports_dir,
    )

    sent_messages: list[tuple[str, str, dict | None]] = []
    callbacks: list[tuple[str, str]] = []

    def fake_send(chat_id: str, text: str, reply_markup=None):
        sent_messages.append((chat_id, text, reply_markup))

    def fake_answer(callback_id: str, text: str):
        callbacks.append((callback_id, text))

    def fake_approve(case_id: str, reports_dir: Path, approved_by: str):
        return True, f"Caso aprovado: {case_id}"

    monkeypatch.setattr("shopee_agent.telegram_bot.approve_remediation_case", fake_approve)
    monkeypatch.setattr(bot, "_send_message", fake_send)
    monkeypatch.setattr(bot, "_answer_callback", fake_answer)

    bot._handle_callback(
        {
            "id": "cb-1",
            "data": "approve:case-7",
            "from": {"username": "alice"},
            "message": {"chat": {"id": "123"}},
        }
    )

    assert callbacks == [("cb-1", "Caso aprovado: case-7")]
    assert sent_messages == [("123", "Caso aprovado: case-7", None)]
