# Phase 37: Multi-Agent Orchestration

Phase 37 adds a small multi-agent layer that coordinates competing goals before actions are executed.

## What changed

- Added `shopee_agent/agent_orchestrator.py`.
- Implemented specialized agents for pricing, ads, inventory, and revenue.
- Added conflict detection and weighted consensus resolution.
- Integrated orchestration into `DecisionIntegrator.process_cycle()`.
- Added focused tests in `tests/test_agent_orchestrator.py`.

## Behavior

- Each agent proposes actions from the shared economic context.
- The orchestrator groups proposals by target, detects conflicts, and resolves them by weighted support.
- The winning actions are ordered into a simple execution schedule.

## Notes

- This is intentionally minimal and synchronous at the integration boundary.
- The design leaves room for Phase 38 strategic planning to build on top of the execution plan.
