import json
from pathlib import Path

import pytest

from shopee_agent import autopilot_actions as aa


class DummyResp:
    def __init__(self, data):
        self.data = data
        self.status_code = 200


class FakeClient:
    def __init__(self, items=None, variations=None, base_info=None, discounts=None, returns=None):
        self._items = items or []
        self._variations = variations or {}
        self._base_info = base_info or {}
        self._discounts = discounts or []
        self._returns = returns or []
        self.price_updates = []

    def get_item_list(self, *, access_token, shop_id, offset, page_size):
        # Return one page and then stop so the action loops terminate.
        if offset > 0:
            return DummyResp({'items': []})
        return DummyResp({'items': self._items})

    def get_item_variations(self, *, access_token, shop_id, item_id):
        return DummyResp({'variations': self._variations.get(item_id, [])})

    def get_item_base_info(self, *, access_token, shop_id, item_id):
        return DummyResp(self._base_info.get(item_id, {}))

    def update_item_price(self, **kwargs):
        self.price_updates.append(kwargs)
        return DummyResp({'ok': True})

    def update_item_stock(self, **kwargs):
        return DummyResp({'ok': True})

    def get_discount_list(self, **kwargs):
        return DummyResp({'discounts': self._discounts})

    def get_return_list(self, **kwargs):
        return DummyResp({'returns': self._returns})


def read_audit_lines(path: Path):
    data = path.read_text(encoding='utf-8').splitlines()
    return [json.loads(line) for line in data if line.strip()]


def test_protect_margin_dry_run(tmp_path):
    reports = tmp_path / 'reports'
    reports.mkdir()
    # product with low margin
    pc = {'1001': 50.0}
    (reports / 'product_costs.json').write_text(json.dumps(pc), encoding='utf-8')

    items = [{'item_id': '1001'}]
    variations = {'1001': [{'variation_id': 'v1', 'current_price': 80.0}]}
    client = FakeClient(items=items, variations=variations)

    aa.protect_margin(client, reports, dry_run=True, margin_floor=0.4, increase_pct=0.05)

    audit = reports / 'stock_price_changes.jsonl'
    assert audit.exists()
    lines = read_audit_lines(audit)
    assert any(line.get('action') == 'protect_margin_reprice' for line in lines)


def test_scale_winners_dry_run(tmp_path):
    reports = tmp_path / 'reports'
    reports.mkdir()
    items = [{'item_id': '2001'}, {'item_id': '2002'}]
    base = {'2001': {'historical_sold': 100}, '2002': {'historical_sold': 50}}
    variations = {
        '2001': [{'variation_id': 'a', 'stock': 5}],
        '2002': [{'variation_id': 'b', 'stock': 10}],
    }
    client = FakeClient(items=items, variations=variations, base_info=base)

    aa.scale_winners(client, reports, dry_run=True, add_stock=20, top_n=1)

    audit = reports / 'stock_price_changes.jsonl'
    assert audit.exists()
    lines = read_audit_lines(audit)
    assert any(line.get('action') == 'scale_winners_add_stock' for line in lines)


def test_pause_and_refund_guard_dry_run(tmp_path, monkeypatch):
    reports = tmp_path / 'reports'
    reports.mkdir()

    discounts = [{'id': 1, 'name': 'disc1'}]
    returns = [{'return_sn': 'R1', 'item_id': '3001', 'quantity': 1}]
    items = []
    client = FakeClient(items=items, discounts=discounts, returns=returns)

    aa.pause_low_roas_ads(client, reports, dry_run=True)
    aa.refund_guard(client, reports, dry_run=True, window_seconds=60)

    audit = reports / 'stock_price_changes.jsonl'
    assert audit.exists()
    lines = read_audit_lines(audit)
    assert any(line.get('action') == 'pause_low_roas_ads_recommend' for line in lines)
    assert any(line.get('action', '').startswith('refund_guard') for line in lines)


def test_pause_low_roas_ads_executes_env_command(tmp_path, monkeypatch):
    reports = tmp_path / 'reports'
    reports.mkdir()

    client = FakeClient(discounts=[{'id': 1, 'name': 'disc1'}])
    calls = []

    class Completed:
        returncode = 0
        stdout = 'ok\n'
        stderr = ''

    def fake_run(cmd, capture_output, text, check):
        calls.append(cmd)
        return Completed()

    monkeypatch.setenv('LAURA_PROFITABILITY_ACTION_PAUSE_LOW_ROAS_ADS_CMD', 'echo pause')
    monkeypatch.setattr(aa.subprocess, 'run', fake_run)

    aa.pause_low_roas_ads(client, reports, dry_run=False)

    assert calls == [['bash', '-lc', 'echo pause']]
    lines = read_audit_lines(reports / 'stock_price_changes.jsonl')
    assert any(line.get('action') == 'pause_low_roas_ads_executed' for line in lines)


def test_protect_margin_uses_latest_review_targets(tmp_path):
    reports = tmp_path / 'reports'
    reports.mkdir()
    (reports / 'product_costs.json').write_text(json.dumps({'1001': 10.0}), encoding='utf-8')
    (reports / 'laura_product_margin_review_latest.json').write_text(json.dumps({
        'target_margin_floor': 0.25,
        'low_margin_entries': [
            {
                'item_id': '1001',
                'variation_id': '12',
                'price': 12.0,
                'cost': 10.0,
                'margin_pct': 16.67,
                'recommended_price': 13.33,
            }
        ],
    }), encoding='utf-8')

    client = FakeClient()
    aa.protect_margin(client, reports, dry_run=False, margin_floor=0.4, increase_pct=0.05)

    assert len(client.price_updates) == 1
    update = client.price_updates[0]
    assert update['item_id'] == '1001'
    assert update['variation_id'] == '12'
    assert update['current_price'] == pytest.approx(13.33, rel=1e-2)
    lines = read_audit_lines(reports / 'stock_price_changes.jsonl')
    assert any(line.get('source') == 'margin_review' for line in lines)
