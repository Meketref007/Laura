from __future__ import annotations


import pytest

import shopee_agent.cli as cli


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeRevenueClient:
    def __init__(self):
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.list_calls = 0

    def get_order_list(self, **kwargs):
        self.calls.append(("get_order_list", kwargs))
        self.list_calls += 1
        if self.list_calls > 1:
            return _FakeResponse({"response": {"order_list": [], "next_cursor": ""}})
        return _FakeResponse(
            {
                "response": {
                    "order_list": [
                        {
                            "order_sn": "260501TEST0001",
                            "buyer_total_amount": 18.5,
                        }
                    ],
                    "next_cursor": "next",
                }
            }
        )

    def get_order_detail(self, **kwargs):
        self.calls.append(("get_order_detail", kwargs))
        return _FakeResponse(
            {
                "response": {
                    "order_items": [
                        {"item_id": "1001", "quantity": 2},
                    ]
                }
            }
        )

    def get_escrow_detail(self, **kwargs):
        self.calls.append(("get_escrow_detail", kwargs))
        return _FakeResponse({"response": {"buyer_total_amount": 18.5}})


def test_ingest_order_revenue_uses_update_time_and_product_costs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    monkeypatch.setattr(cli, "_PRODUCT_COSTS_PATH", reports_dir / "product_costs.json")
    cli._save_product_cost("1001", 3.25)

    client = _FakeRevenueClient()
    event = cli._ingest_order_revenue_report(
        client,
        access_token="token",
        shop_id=123,
        days=90,
        page_size=50,
        max_orders=10,
    )

    assert event["revenue"] == pytest.approx(18.5)
    assert event["cogs"] == pytest.approx(6.5)
    assert event["paid_orders"] == 1
    assert event["orders_seen"] == 1
    assert event["sample_orders"][0]["amount"] == pytest.approx(18.5)

    first_call = client.calls[0]
    assert first_call[0] == "get_order_list"
    assert first_call[1]["order_status"] == "COMPLETED"
    assert first_call[1]["time_range_field"] == "update_time"
