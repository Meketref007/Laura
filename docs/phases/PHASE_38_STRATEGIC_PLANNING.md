# Phase 38: Strategic Planning

Phase 38 adds a strategic planning layer that turns long-term goals into multi-step campaigns with phases, gates, timelines, and adaptation.

## What changed

- Added `shopee_agent/strategic_planner.py`.
- Introduced `Goal`, `Gate`, `PlanPhase`, `StrategicPlan`, `GoalStack`, and `StrategicPlanner`.
- Integrated strategic planning into `DecisionIntegrator.process_cycle()`.
- Added focused tests in `tests/test_strategic_planner.py`.

## Behavior

- The planner chooses the highest-priority long-term goal from the goal stack.
- Goals are decomposed into a phased campaign with gates and dependencies.
- The plan is scheduled over time and monitored against the current economic context.
- When conditions weaken, the planner adapts the plan by adding safeguards and trimming aggressive phases.

## Notes

- This layer builds on the tactical orchestrator from Phase 37.
- The implementation is intentionally small and deterministic so it can be expanded in Phase 39.
