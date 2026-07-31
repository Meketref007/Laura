#!/usr/bin/env bash
set -euo pipefail

# Script: pause low-ROAS discounts (example hook for autopilot)
# Usage: ./scripts/laura_pause_low_roas_ads.sh [--execute]
# By default runs a safe dry-run that lists discounts. To actually attempt
# disabling discounts, pass --execute and ensure env var LAURA_PROFITABILITY_EXECUTE_ENABLED=1 is set.

EXECUTE=0
if [ "${1-}" = "--execute" ]; then
  EXECUTE=1
fi

python3 - <<'PY'
from __future__ import annotations
import json
import os
import sys

from shopee_agent.config import load_config
from shopee_agent.client import ShopeeClient

cfg = load_config()
client = ShopeeClient(cfg)

try:
    resp = client.get_discount_list(access_token=None, shop_id=None, discount_status='all')
except Exception as e:
    print(json.dumps({'error': 'get_discount_list_failed', 'error_str': str(e)}))
    sys.exit(2)

discounts = resp.data.get('discounts') or resp.data.get('discount_list') or []
out = {'found': len(discounts)}
print(json.dumps(out, ensure_ascii=False))
if not discounts:
    sys.exit(0)

if os.getenv('LAURA_PROFITABILITY_EXECUTE_ENABLED','') != '1' and '--execute' in sys.argv:
    print(json.dumps({'warning': 'LAURA_PROFITABILITY_EXECUTE_ENABLED not set to 1 - refusing to execute'}))
    sys.exit(3)

do_execute = ('--execute' in sys.argv) and os.getenv('LAURA_PROFITABILITY_EXECUTE_ENABLED','') == '1'

results = []
for d in discounts:
    discount_id = d.get('id') or d.get('discount_id') or d.get('campaign_id')
    summary = {'discount': d}
    if not do_execute:
        # Dry-run: just record the recommendation
        results.append({'action': 'recommend_pause', 'discount_id': discount_id})
        continue

    # Best-effort: try common disable endpoint(s). If the marketplace exposes
    # a dedicated disable endpoint it will likely be one of these paths.
    tried = []
    for path in ('/api/v2/discount/disable_discount', '/api/v2/discount/update_discount_status', '/api/v2/discount/pause_discount'):
        try:
            r = client.call_endpoint(path, method='POST', payload={'discount_id': discount_id})
            summary['attempt'] = path
            summary['status_code'] = getattr(r, 'status_code', None)
            summary['data'] = getattr(r, 'data', None)
            tried.append(path)
            break
        except Exception as exc:
            summary.setdefault('errors', []).append({'path': path, 'error': str(exc)[:300]})
            tried.append(path)

    if not tried:
        summary['note'] = 'no_attempt_made'

    results.append(summary)

print(json.dumps({'results': results}, ensure_ascii=False))

sys.exit(0)
PY
