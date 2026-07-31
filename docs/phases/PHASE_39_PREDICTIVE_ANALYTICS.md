# Phase 39: Predictive Analytics

Phase 39 adds a lightweight predictive analytics layer that forecasts near-term business signals from existing history files and feeds them back into the decision cycle.

## What changed

- Added `shopee_agent/predictive_analytics.py`.
- Implemented forecasts for revenue, margin, ROAS, and inventory days on hand.
- Integrated predictions into `DecisionIntegrator.process_cycle()`.
- Added focused tests in `tests/test_predictive_analytics.py`.

## Behavior

- The predictor reads local history from `reports/` and produces short-horizon forecasts.
- Each forecast includes direction, confidence, risk level, and a recommendation.
- The decision cycle summary now includes a predictive snapshot when configured.

## Notes

- This phase is intentionally deterministic and dependency-light.
- Future phases can swap in heavier models or external data sources without changing the integration boundary.
