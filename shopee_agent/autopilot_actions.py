from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import load_config


def _append_audit(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(obj, ensure_ascii=True) + "\n")


def _load_margin_review_targets(reports_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    review_path = reports_dir / 'laura_product_margin_review_latest.json'
    if not review_path.exists():
        return {}, []

    try:
        report = json.loads(review_path.read_text(encoding='utf-8'))
    except Exception:
        return {}, []

    if not isinstance(report, dict):
        return {}, []

    targets = report.get('low_margin_entries')
    if not isinstance(targets, list):
        targets = []

    return report, [entry for entry in targets if isinstance(entry, dict)]


def protect_margin(client, reports_dir: Path, dry_run: bool = True, margin_floor: float = 0.25, increase_pct: float = 0.05) -> None:
    costs_file = reports_dir / 'product_costs.json'
    costs = {}
    if costs_file.exists():
        try:
            costs = json.loads(costs_file.read_text(encoding='utf-8'))
        except Exception:
            costs = {}

    audit = reports_dir / 'stock_price_changes.jsonl'

    review_report, review_targets = _load_margin_review_targets(reports_dir)
    if review_targets:
        review_floor = review_report.get('target_margin_floor')
        if isinstance(review_floor, (int, float)) and 0 < float(review_floor) < 1:
            margin_floor = float(review_floor)

        for entry in review_targets:
            item_id = entry.get('item_id')
            if item_id is None:
                continue
            variation_id = entry.get('variation_id')
            price = entry.get('price')
            recommended_price = entry.get('recommended_price')
            try:
                price_f = float(price)
            except Exception:
                continue
            try:
                new_price = float(recommended_price) if recommended_price is not None else round(price_f * (1.0 + increase_pct), 2)
            except Exception:
                new_price = round(price_f * (1.0 + increase_pct), 2)
            if new_price <= 0:
                continue

            margin_pct = entry.get('margin_pct')
            audit_entry = {
                'timestamp': datetime.now(UTC).isoformat(),
                'action': 'protect_margin_reprice',
                'source': 'margin_review',
                'item_id': item_id,
                'variation_id': variation_id,
                'old_price': price_f,
                'new_price': round(new_price, 2),
                'target_margin_floor': margin_floor,
                'margin_pct': margin_pct,
                'dry_run': dry_run,
            }
            _append_audit(audit, audit_entry)
            if not dry_run:
                try:
                    r = client.update_item_price(access_token=None, shop_id=None, item_id=item_id, variation_id=variation_id, current_price=round(new_price, 2))
                    audit_entry['response'] = getattr(r, 'data', None)
                except Exception as e:
                    audit_entry['error'] = str(e)
                _append_audit(audit, audit_entry)
        return

    offset = 0
    page = 50
    while True:
        resp = client.get_item_list(access_token=None, shop_id=None, offset=offset, page_size=page)
        if getattr(resp, 'status_code', None) not in (200, None) and resp.status_code != 200:
            break
        items = (resp.data.get('items') if resp and isinstance(resp.data, dict) else []) or []
        if not items:
            break
        for item in items:
            item_id = item.get('item_id')
            if item_id is None:
                continue
            vresp = client.get_item_variations(access_token=None, shop_id=None, item_id=item_id)
            if getattr(vresp, 'status_code', None) not in (200, None) and vresp.status_code != 200:
                continue
            variations = (vresp.data.get('variations') if vresp and isinstance(vresp.data, dict) else []) or []
            for v in variations:
                vid = v.get('variation_id')
                price = v.get('current_price') or v.get('price') or v.get('original_price')
                try:
                    price_f = float(price)
                except Exception:
                    continue
                cost = costs.get(str(item_id))
                if cost is None:
                    continue
                try:
                    cost_f = float(cost)
                except Exception:
                    continue
                if price_f <= 0:
                    continue
                margin = (price_f - cost_f) / price_f
                if margin < margin_floor:
                    new_price = round(price_f * (1.0 + increase_pct), 2)
                    entry = {
                        'timestamp': datetime.now(UTC).isoformat(),
                        'action': 'protect_margin_reprice',
                        'item_id': item_id,
                        'variation_id': vid,
                        'old_price': price_f,
                        'new_price': new_price,
                        'dry_run': dry_run,
                    }
                    _append_audit(audit, entry)
                    if not dry_run:
                        try:
                            r = client.update_item_price(access_token=None, shop_id=None, item_id=item_id, variation_id=vid, current_price=new_price)
                            entry['response'] = getattr(r, 'data', None)
                        except Exception as e:
                            entry['error'] = str(e)
                        _append_audit(audit, entry)
        offset += page


def scale_winners(client, reports_dir: Path, dry_run: bool = True, add_stock: int = 20, top_n: int = 10) -> None:
    audit = reports_dir / 'stock_price_changes.jsonl'
    offset = 0
    page = 50
    candidates: list[tuple[int, Any]] = []
    while True:
        resp = client.get_item_list(access_token=None, shop_id=None, offset=offset, page_size=page)
        if getattr(resp, 'status_code', None) not in (200, None) and resp.status_code != 200:
            break
        items = (resp.data.get('items') if resp and isinstance(resp.data, dict) else []) or []
        if not items:
            break
        for item in items:
            item_id = item.get('item_id')
            base = client.get_item_base_info(access_token=None, shop_id=None, item_id=item_id)
            sold = 0
            if getattr(base, 'status_code', None) in (200, None):
                sold = int(base.data.get('historical_sold') or base.data.get('sold') or 0)
            candidates.append((sold, item_id))
        offset += page
    candidates.sort(reverse=True)
    for sold, item_id in candidates[:top_n]:
        vresp = client.get_item_variations(access_token=None, shop_id=None, item_id=item_id)
        if getattr(vresp, 'status_code', None) not in (200, None) and vresp.status_code != 200:
            continue
        variations = (vresp.data.get('variations') if vresp and isinstance(vresp.data, dict) else []) or []
        for v in variations:
            vid = v.get('variation_id')
            stock = v.get('stock')
            try:
                stock_i = int(stock)
            except Exception:
                continue
            new_stock = stock_i + add_stock
            entry = {
                'timestamp': datetime.now(UTC).isoformat(),
                'action': 'scale_winners_add_stock',
                'item_id': item_id,
                'variation_id': vid,
                'old_stock': stock_i,
                'new_stock': new_stock,
                'dry_run': dry_run,
            }
            _append_audit(audit, entry)
            if not dry_run:
                try:
                    r = client.update_item_stock(access_token=None, shop_id=None, item_id=item_id, variation_id=vid, stock=new_stock)
                    entry['response'] = getattr(r, 'data', None)
                except Exception as e:
                    entry['error'] = str(e)
                _append_audit(audit, entry)


def pause_low_roas_ads(client, reports_dir: Path, dry_run: bool = True) -> None:
    audit = reports_dir / 'stock_price_changes.jsonl'
    resp = client.get_discount_list(access_token=None, shop_id=None, discount_status='all')
    if getattr(resp, 'status_code', None) not in (200, None) and resp.status_code != 200:
        return
    discounts = resp.data.get('discounts') or resp.data.get('discount_list') or []
    pause_cmd = os.getenv('LAURA_PROFITABILITY_ACTION_PAUSE_LOW_ROAS_ADS_CMD', '').strip()
    for d in discounts:
        entry = {
            'timestamp': datetime.now(UTC).isoformat(),
            'action': 'pause_low_roas_ads_recommend',
            'discount': d,
            'dry_run': dry_run,
        }
        if dry_run or not pause_cmd:
            _append_audit(audit, entry)
            continue

        try:
            completed = subprocess.run(
                ['bash', '-lc', pause_cmd],
                capture_output=True,
                text=True,
                check=False,
            )
            entry['command'] = pause_cmd
            entry['returncode'] = completed.returncode
            if completed.stdout:
                entry['stdout'] = completed.stdout[-500:]
            if completed.stderr:
                entry['stderr'] = completed.stderr[-500:]
            entry['action'] = 'pause_low_roas_ads_executed'
        except Exception as exc:
            entry['action'] = 'pause_low_roas_ads_failed'
            entry['error'] = str(exc)
        _append_audit(audit, entry)


def refund_guard(client, reports_dir: Path, dry_run: bool = True, window_seconds: int = 60 * 60 * 24) -> None:
    audit = reports_dir / 'stock_price_changes.jsonl'
    now = int(datetime.now(UTC).timestamp())
    since = now - window_seconds
    resp = client.get_return_list(access_token=None, shop_id=None, time_from=since, time_to=now, page_size=50)
    if getattr(resp, 'status_code', None) not in (200, None) and resp.status_code != 200:
        return
    returns = resp.data.get('returns') or resp.data.get('return_list') or []
    if not returns:
        return
    # send a Telegram notification if configured
    token = os.getenv('LAURA_ALERT_TELEGRAM_BOT_TOKEN')
    chat = os.getenv('LAURA_ALERT_TELEGRAM_CHAT_ID')
    if not token or not chat:
        # still write an audit recommending review
        entry = {
            'timestamp': datetime.now(UTC).isoformat(),
            'action': 'refund_guard_recommend',
            'returns_count': len(returns),
            'dry_run': dry_run,
        }
        _append_audit(audit, entry)
        return
    lines = [f"Refund guard: {len(returns)} recent returns needing review"]
    for r in returns[:10]:
        lines.append(f"- {r.get('return_sn')}: item {r.get('item_id')} qty {r.get('quantity')}")
    msg = '\n'.join(lines)
    try:
        import requests

        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data={'chat_id': chat, 'text': msg}, timeout=10)
        entry = {
            'timestamp': datetime.now(UTC).isoformat(),
            'action': 'refund_guard_notify',
            'returns_count': len(returns),
            'dry_run': dry_run,
        }
        _append_audit(audit, entry)
    except Exception:
        entry = {
            'timestamp': datetime.now(UTC).isoformat(),
            'action': 'refund_guard_notify_failed',
            'returns_count': len(returns),
            'dry_run': dry_run,
        }
        _append_audit(audit, entry)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--action', required=True, choices=['protect_margin', 'scale_winners', 'pause_low_roas_ads', 'refund_guard'])
    parser.add_argument('--reports-dir', default=os.getenv('REPORTS_DIR', 'reports'))
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--add-stock', type=int, default=20)
    args = parser.parse_args(argv)

    reports_dir = Path(args.reports_dir)
    cfg = load_config()
    # create client from cfg in normal runs
    from .client import ShopeeClient

    client = ShopeeClient(cfg)

    if args.action == 'protect_margin':
        protect_margin(client, reports_dir, dry_run=args.dry_run)
    elif args.action == 'scale_winners':
        scale_winners(client, reports_dir, dry_run=args.dry_run, add_stock=args.add_stock)
    elif args.action == 'pause_low_roas_ads':
        pause_low_roas_ads(client, reports_dir, dry_run=args.dry_run)
    elif args.action == 'refund_guard':
        refund_guard(client, reports_dir, dry_run=args.dry_run)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
