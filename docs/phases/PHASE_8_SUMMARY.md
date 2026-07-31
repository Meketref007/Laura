# PHASE 8: Learning System
**Status:** ✅ COMPLETE
**Date:** 2026-05-19

## Overview
Phase 8 introduces a continuous learning layer that evaluates decision outcomes, compares recent performance with the previous window, surfaces failure hotspots, and persists a learning note for future reflection.

## Key Deliverables

### 1. New Module: `shopee_agent/learning_system.py`
**Class:** `LearningSystem`

#### Core Methods:
- `evaluate(window_days=30, persist_note=True)` - Build a learning report from outcomes and reflection
- `weekly_report(persist_note=True)` - Convenience alias for a 7-day learning pass
- `record_feedback(title, summary, kind='feedback', metadata=None)` - Persist manual feedback as a memory note
- `search_lessons(query, limit=10)` - Reuse semantic memory for lesson retrieval

#### Features:
- Compares recent outcomes against the previous window
- Tracks success, failure, and partial rates
- Detects weak rules and failure hotspots
- Reuses `ReflectionSystem` for insights and recommendations
- Persists a `learning_cycle` note into long-term memory

### 2. CLI Command

#### Command: `learning-summary`
```bash
python3 -m shopee_agent.cli learning-summary --window-days 30
```
- Uses decision outcomes and long-term memory notes
- Optional JSON export via `--output`
- Optional `--no-persist-note` to avoid writing a learning note

## Validation
- `tests/test_learning_system.py` passed

## Notes
- This phase builds directly on the existing `DecisionOutcome`, `LongTermMemory`, `SemanticMemory`, and `ReflectionSystem` implementations.
- The module is intentionally lightweight and file-backed, matching the repository's current persistence style.
