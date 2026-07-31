# Phase 40: Supply Chain Planning

Phase 40 adds a supply chain planning layer that turns inventory snapshots and forecasts into procurement and logistics recommendations.

## What changed

- Added `shopee_agent/supply_chain_planner.py`.
- Reads `reports/laura_inventory_monitor_latest.json` and fallbacks from `reports/store_health_*.json`.
- Produces procurement recommendations, logistics recommendations, and supply chain risks.
- Integrates into `DecisionIntegrator.process_cycle()` as an optional layer.
- Added focused tests in `tests/test_supply_chain_planner.py`.

## Behavior

- Low-stock items are converted into reorder recommendations.
- Supplier selection balances urgency, cost, lead time, and reliability.
- Forecasts can bias procurement urgency through the predictive analytics layer.
- The planner can adapt to cash pressure and short inventory cover.

## Notes

- The implementation is deterministic and uses only local reports.
- This keeps the phase safe and lightweight while leaving room for more advanced procurement logic later.
