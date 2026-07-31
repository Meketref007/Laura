from __future__ import annotations

from pathlib import Path

from shopee_agent.flash_sale_recommender import FlashSaleRecommender


class _FakeResponse:
    def __init__(self, data, status_code: int = 200):
        self.data = data
        self.status_code = status_code


class _FakeClient:
    def __init__(self) -> None:
        self.item_list_calls = 0
        self.item_perf_calls = 0
        self.add_flash_sale_calls = 0

    def get_item_list(self, *, access_token, shop_id, offset, page_size):
        self.item_list_calls += 1
        if offset > 0:
            return _FakeResponse({"response": {"item": []}})
        return _FakeResponse(
            {
                "response": {
                    "item": [
                        {"item_id": 101, "item_name": "Camiseta Premium", "stock": 25},
                        {"item_id": 202, "item_name": "Copo Branded", "stock": 8},
                    ]
                }
            }
        )

    def get_item_performance(self, *, access_token, shop_id, item_id, time_from, time_to):
        self.item_perf_calls += 1
        if item_id == 101:
            return _FakeResponse({"response": {"sales_7d": 0}})
        return _FakeResponse({"response": {"sales_7d": 12}})

    def add_flash_sale(self, *, access_token, shop_id, flash_sale_name, start_time, end_time, items):
        self.add_flash_sale_calls += 1
        return _FakeResponse(
            {
                "flash_sale_id": 999,
                "flash_sale_name": flash_sale_name,
                "items": items,
                "start_time": start_time,
                "end_time": end_time,
            }
        )


def test_generate_recommendations_identifies_stalled_stock(tmp_path: Path):
    client = _FakeClient()
    recommender = FlashSaleRecommender(
        client=client,
        access_token="token",
        shop_id=123,
        reports_dir=tmp_path,
        min_stock=20,
        discount_pct=15,
    )

    recommendation = recommender.generate_recommendations()

    assert client.item_list_calls >= 1
    assert client.item_perf_calls == 2
    assert len(recommendation.candidates) == 1
    assert recommendation.candidates[0].item_id == 101
    assert recommendation.candidates[0].discount_pct == 15

    latest = tmp_path / "laura_flash_sale_recommendation_latest.json"
    assert latest.exists()


def test_build_flash_sale_payload_and_create(tmp_path: Path):
    client = _FakeClient()
    recommender = FlashSaleRecommender(
        client=client,
        access_token="token",
        shop_id=123,
        reports_dir=tmp_path,
        min_stock=20,
        discount_pct=20,
    )

    recommendation = recommender.generate_recommendations()
    payload = recommender.build_flash_sale_payload(recommendation)

    assert payload["items"] == [{"item_id": 101, "discount_percentage": 20}]
    assert payload["flash_sale_name"].startswith("Flash Sale automática")

    result = recommender.create_flash_sale(recommendation)
    assert result["status"] == "created"
    assert client.add_flash_sale_calls == 1
    assert result["payload"]["items"] == [{"item_id": 101, "discount_percentage": 20}]
    assert (tmp_path / "laura_flash_sale_result_latest.json").exists()
