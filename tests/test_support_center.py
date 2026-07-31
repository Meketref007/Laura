from __future__ import annotations

import json

import shopee_agent.cli as cli
from shopee_agent.support_center import SupportCenter


def test_support_center_triage_and_memory(tmp_path):
    center = SupportCenter(reports_dir=tmp_path)

    ticket = center.triage_message(
        buyer_id="buyer_123",
        message="Meu pedido está atrasado e quero cancelar ou reembolso.",
        order_id="order_1",
    )

    profile = center.load_profile("buyer_123")
    summary = center.summary(days=30)

    assert ticket.intent in {"delivery", "cancelation", "refund", "complaint"}
    assert ticket.escalate is True
    assert ticket.priority == "high"
    assert "buyer_123" == profile.buyer_id
    assert profile.interaction_count == 1
    assert profile.open_tickets == 1
    assert profile.escalation_count == 1
    assert summary.total_tickets == 1
    assert summary.open_tickets == 1
    assert summary.escalated_tickets == 1
    assert summary.intent_counts[ticket.intent] == 1
    assert summary.recent_escalations

    history_path = tmp_path / "support_tickets.jsonl"
    profiles_path = tmp_path / "support_customers.json"
    assert history_path.exists()
    assert profiles_path.exists()

    saved_profile = json.loads(profiles_path.read_text(encoding="utf-8"))
    assert "buyer_123" in saved_profile


def test_support_center_resolution_updates_profile(tmp_path):
    center = SupportCenter(reports_dir=tmp_path)
    ticket = center.triage_message(buyer_id="buyer_456", message="Qual o prazo de entrega?")

    assert center.record_resolution(ticket.ticket_id, buyer_id="buyer_456", note="Respondido no chat") is True

    profile = center.load_profile("buyer_456")
    assert profile.open_tickets == 0
    assert profile.resolved_tickets == 1


def test_support_summary_cli_outputs_json(tmp_path, monkeypatch):
    center = SupportCenter(reports_dir=tmp_path)
    center.triage_message(buyer_id="buyer_789", message="Onde está meu pedido?")
    output_path = tmp_path / "support_summary.json"

    monkeypatch.setattr(cli.sys, "argv", [
        "laura",
        "support-summary",
        "--reports-dir",
        str(tmp_path),
        "--output",
        str(output_path),
    ])

    exit_code = cli.main()

    assert exit_code == 0
    assert output_path.exists()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["total_tickets"] == 1
    assert payload["open_tickets"] == 1
    assert payload["top_buyers"][0]["buyer_id"] == "buyer_789"
