# Phase 34: Decision Engine v1

**Status**: ✅ MVP Complete - 17/17 Tests Passing  
**Date**: 2026-05-14  
**Version**: 1.0.0  
**Focus**: Bridging AI COO → AI CEO transition

---

## 🎯 Executive Summary

The Decision Engine is the central nervous system that transforms Laura from a distributed automation system (AI COO) into an autonomous strategic agent (AI CEO).

**What Changed**:
- Before: Autonomous loop ran 40+ independent scripts
- Now: Central decision engine coordinates all major actions
- Result: Prioritized, auditable, economically-aware automation

**Key Achievement**: First layer of centralized strategic reasoning while maintaining operational reliability.

---

## 🏗️ Architecture

### Four Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                      DECISION ENGINE v1                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. SIGNAL PROCESSOR                                        │
│     ↓ Aggregates metrics/alerts/webhooks                    │
│     → Generates DecisionSignal objects                      │
│                                                              │
│  2. RULE EVALUATOR                                          │
│     ↓ Applies business rules + guardrails                   │
│     → Scores decisions (impact, risk, confidence)           │
│                                                              │
│  3. DECISION GENERATOR                                      │
│     ↓ Creates prioritized action plans                      │
│     → Outputs: APPROVED, REJECTED, or PENDING               │
│                                                              │
│  4. AUDIT LOGGER                                            │
│     ↓ Records every decision + reasoning                    │
│     → JSONL format for compliance + learning                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

```
Laura Monitoring (existing)
    ↓
    ├─ laura_profitability_latest.json
    ├─ laura_metrics.jsonl
    ├─ laura_webhook_ready_audit.jsonl
    └─ laura_profitability_state.json
         ↓
    SIGNAL PROCESSOR
         ↓
    DecisionSignal[] + EconomicContext
         ↓
    RULE EVALUATOR
         ↓
    Apply guardrails (margin floor, cash buffer, risk limits)
         ↓
    DECISION GENERATOR
         ↓
    Decision[] with APPROVED/REJECTED/PENDING status
         ↓
    AUDIT LOGGER
         ↓
    reports/decision_log.jsonl (append-only)
         ↓
    AUTONOMOUS LOOP
         ↓
    Execute approved decisions
         ↓
    Update state, monitor outcomes
```

---

## 📊 Data Models

### DecisionSignal
Input to the system. Represents an event that might require action.

```python
@dataclass
class DecisionSignal:
    source: str           # "metrics", "alerts", "webhook", "manual"
    signal_type: str      # "anomaly", "opportunity", "risk", "routine"
    data: Dict            # Payload with metric specifics
    timestamp: datetime
    context: Optional[Dict]  # Additional metadata
```

**Examples**:
- Margin dropped 5% → signal_type="anomaly"
- ROAS degraded 20% → signal_type="opportunity"
- Inventory at 2 days → signal_type="risk"

### EconomicContext
Current operational state used for decision-making.

```python
@dataclass
class EconomicContext:
    current_margin_pct: float         # e.g., 15.0%
    margin_target_pct: float          # e.g., 18.0%
    daily_revenue_usd: float          # e.g., 5000.0
    cash_buffer_usd: float            # e.g., 50000.0
    inventory_days_on_hand: int       # e.g., 15
    stock_risk_level: str             # "critical", "high", "normal", "excess"
    advertising_roas: float           # e.g., 2.5
    customer_satisfaction_score: float # e.g., 85.0
    recent_anomalies: List[str]       # Historical context
```

### Decision
Core output. Represents a single autonomous action to take.

```python
@dataclass
class Decision:
    decision_id: str              # Unique identifier
    decision_type: DecisionType   # PRICING, ADS, INVENTORY, etc.
    title: str                    # Human-readable name
    recommended_action: str       # What to do
    priority: DecisionPriority    # CRITICAL, HIGH, NORMAL, LOW
    
    # Scoring (normalized 0-1)
    impact_score: float           # Expected financial impact
    risk_score: float             # Probability of negative outcome
    confidence_score: float       # Model confidence
    
    # Status
    status: DecisionStatus        # PENDING, APPROVED, REJECTED, EXECUTED
    guardrails_passed: Dict[str, bool]  # Compliance checks
    
    # Audit trail
    reasoning: str                # Why this decision
    assumptions: List[str]        # What we assumed
    alternative_actions: List[str] # Other options considered
```

### DecisionRule
Business rule. Condition → Action mapping.

```python
@dataclass
class DecisionRule:
    rule_id: str
    decision_type: DecisionType
    name: str
    description: str
    
    # When to apply
    condition: str
    priority_boost: int
    
    # Guardrails
    risk_threshold: RiskLevel
    max_daily_executions: Optional[int]
    estimated_impact: Dict[str, float]  # {"margin": 0.05}
```

---

## 🧠 Decision Types (v1)

### 1. PRICING
Adjusting prices to protect or optimize margin.

**Trigger**: Margin dropped >5%, or ROAS opportunity detected  
**Rule**: `pricing_margin_protect`  
**Action**: Recommend price adjustments  
**Guardrails**: 
- Don't go below margin floor (80% of target)
- Max discount 30%

**Example Decision**:
```json
{
  "title": "Margin Protection Pricing",
  "recommended_action": "Adjust pricing to improve margin (target: 18.0%)",
  "impact_score": 0.05,
  "risk_score": 0.2,
  "confidence_score": 0.75
}
```

### 2. ADS
Optimize advertising spend and campaigns.

**Trigger**: ROAS degraded >20% vs baseline  
**Rule**: `ads_roas_optimize`  
**Action**: Pause low-ROAS campaigns, redistribute budget  
**Guardrails**:
- Min ROAS > 1.5
- Max daily change < 30%
- Preserve brand visibility

### 3. INVENTORY
Stock management and restocking.

**Trigger**: Days on hand < safety stock (critical)  
**Rule**: `inventory_stockout_prevent`  
**Action**: Trigger restocking order  
**Guardrails**:
- Only if cash buffer > $10K
- Max 1 restock per day
- Escalate if < 1 day remaining

### 4. CUSTOMER_SERVICE (Future)
Auto-response routing and escalation.

### 5. ALERTS (Future)
Alert routing based on severity and business context.

### 6. EXPERIMENTS (Future)
A/B test execution and control.

---

## 🛡️ Guardrails (Risk Management)

Every decision is checked against operational guardrails before approval.

| Guardrail | Threshold | Purpose |
|-----------|-----------|---------|
| **margin_floor** | 80% of target | Financial safety |
| **cash_buffer** | $1,000 minimum | Operational continuity |
| **inventory_health** | NOT critical | Prevent stockout actions in crisis |
| **acceptable_risk** | Risk score < 0.6 | Avoid high-risk decisions |
| **reasonable_confidence** | Confidence > 0.5 | Only execute well-understood decisions |
| **roas_acceptable** | ROAS ≥ 1.5 | Ad efficiency check |

**Decision Flow**:
```
Generate Decision
    ↓
Evaluate all guardrails
    ↓
If ALL pass → Status = APPROVED
If ANY fail → Status = REJECTED (with reason)
    ↓
Log decision (with guardrail details)
    ↓
Autonomous loop can execute APPROVED only
```

---

## 🔄 Decision Lifecycle

### State Transitions

```
PENDING
  ↓
  ├─→ APPROVED (all guardrails passed)
  │     ↓
  │     └─→ EXECUTED (action completed)
  │
  └─→ REJECTED (guardrails failed)
```

### Execution Flow

1. **Signal Received**: Metric anomaly detected
2. **Decision Generated**: Engine applies rules
3. **Guardrails Evaluated**: Compliance checks
4. **Decision Logged**: JSONL record created
5. **Autonomous Loop Queries**: Pulls APPROVED decisions
6. **Action Executed**: Route to appropriate Laura module
7. **Outcome Tracked**: Monitor success/failure

---

## 🎮 CLI Commands

Decision Engine is fully integrated into Laura CLI.

### Check Pending Decisions
```bash
laura decision-status --priority critical
```

Shows all pending decisions, filterable by priority.

**Output**:
```
═══════════════════════════════════════════════════
  LAURA DECISION ENGINE - STATUS
═══════════════════════════════════════════════════

Store: default
Rules: 3
Pending Decisions: 5
Critical: 2

5 Pending Decisions:

┌────┬──────────┬──────────┬────────┬────────────┬──────────┐
│ ID │ Type     │ Priority │ Impact │ Confidence │ Status   │
├────┼──────────┼──────────┼────────┼────────────┼──────────┤
│ de │ pricing  │ CRITICAL │ 0.05   │ 0.75       │ approved │
│ c9 │ ads      │ HIGH     │ 0.15   │ 0.68       │ approved │
│ ... │ ...     │ ...      │ ...    │ ...        │ ...      │
└────┴──────────┴──────────┴────────┴────────────┴──────────┘
```

### View Decision History
```bash
laura decision-history --days 7 --type pricing
```

Audit trail of all decisions made in last 7 days, filterable by type.

### Get Decision Details
```bash
laura decision-detail dec_a1b2c3d4
```

Full reasoning, assumptions, alternative actions, guardrail status.

### Run Decision Cycle
```bash
laura decision-cycle
```

Execute one complete evaluation cycle:
1. Collect signals
2. Build context
3. Generate decisions
4. Log results

### View Quality Metrics
```bash
laura decision-metrics --days 30
```

Quality scorecard:
- Total decisions
- Approval rate
- Average impact/confidence
- Breakdown by type
- Overall quality score (0-100)

---

## 📈 Integration with Autonomous Loop

The autonomous loop now has three execution modes:

### Mode 1: Direct Automation (existing)
```
Script runs → API call → Result
(e.g., laura_profitability_autopilot.sh)
```

### Mode 2: Guided by Decision Engine (NEW)
```
Script runs → Queries Decision Engine → Gets prioritized actions
→ API calls → Result logged
```

Example integration:
```python
# In autonomous_loop.py
integrator = DecisionIntegrator(engine, store_id)

# During cycle
integrator.collect_signals_from_metrics()
decisions = integrator.process_cycle()

# Get high-priority decisions
critical_actions = integrator.get_pending_actions(
    min_priority=DecisionPriority.CRITICAL
)

# Execute them
for decision in critical_actions:
    execute_decision(decision)
    integrator.mark_decision_executed(decision.decision_id)
```

### Mode 3: Strategic Planning (future)
Decision engine plans multi-step campaigns with dependencies and milestones.

---

## 📊 Decision Log Format

Every decision is appended to `reports/decision_log.jsonl` (one decision per line).

```json
{
  "decision_id": "dec_a1b2c3d4",
  "decision_type": "pricing",
  "rule_id": "pricing_margin_protect",
  "title": "Margin Protection Pricing",
  "priority": "critical",
  "impact_score": 0.05,
  "risk_score": 0.20,
  "confidence_score": 0.75,
  "status": "approved",
  "created_at": "2026-05-14T10:30:45.123456",
  "executed_at": "2026-05-14T10:31:02.654321",
  "reasoning": "Rule 'Margin Protection Pricing' triggered...",
  "assumptions": [
    "Current margin: 15.0%",
    "Margin target: 18.0%",
    "ROAS: 2.50"
  ],
  "guardrails_passed": {
    "margin_floor": true,
    "cash_buffer": true,
    "inventory_healthy": true,
    "acceptable_risk": true,
    "reasonable_confidence": true
  }
}
```

---

## 🚀 Deployment (Phase 34)

### What's Live Now

✅ **Decision Engine Core**
- 3 default rules (pricing, ads, inventory)
- Full scoring system
- Guardrail evaluation
- Audit logging

✅ **Integration Layer**
- Signal collection from metrics
- Economic context aggregation
- CLI commands
- Audit trails

✅ **Testing**
- 17 unit tests (100% passing)
- Coverage: Engine, rules, guardrails, logging, retrieval

### What to Do Next

**Week 1 (Integration)**:
- Hook Decision Engine into autonomous_loop.py
- Test with 1 week of real data
- Tune guardrail thresholds

**Week 2 (Expansion)**:
- Add 5 more decision rules
- Implement DecisionExecutor callbacks
- Build feedback loop (outcomes → learn)

**Week 3 (Optimization)**:
- Add Memory Layer (simple store of recent decisions)
- Implement decay/ranking of past actions
- Begin A/B testing rule effectiveness

**Week 4 (Phase 35)**:
- Migrate to event-driven architecture (workers + queue)
- Multi-agent orchestration
- RAG for decision reasoning

---

## Phase 35: Memory & Learning Layer (Detailed)

**Goal:** Enable the Decision Engine to learn from executed decisions so rules improve over time.

### Scope (Phase 35 MVP)
- `DecisionOutcome` model stored in `reports/decision_outcomes.jsonl` (JSONL)
- `MemoryLayer` (in `shopee_agent/decision_memory.py`) that records outcomes, computes rule effectiveness, and ranks similar past decisions
- Integrate `MemoryLayer` into `DecisionEngine` so every executed decision is recorded
- CLI commands: `laura decision-outcomes` (view) and `laura decision-learn` (compute effectiveness, optional in-memory updates)
- Unit tests for `MemoryLayer` and light integration tests

### Data Model: `DecisionOutcome`
Fields:
- `decision_id`, `rule_id`, `executed_at`, `outcome_type` (executed|success|partial|failure|reverted)
- `impact_realized`, `margin_change`, `revenue_change`, `satisfaction_change`
- `reversals`, `feedback`, `metadata`

### Learning primitives (MVP)
- `get_rule_effectiveness(rule_id) -> float` (0-1), counts successes/partials/failures
- `predict_outcome_for_rule(rule_id) -> float`, mean realized impact
- `rank_similar_decisions(signal) -> List[DecisionOutcome]` for case-based reasoning

### CLI
- `laura decision-outcomes --limit N`: display recent outcomes
- `laura decision-learn [--apply-updates]`: compute rule effectiveness; `--apply-updates` adjusts in-memory rule estimates (Phase 35 only)

### Success Criteria
- 95% of executed decisions are recorded in `reports/decision_outcomes.jsonl`
- `get_rule_effectiveness` produces meaningful signals (smoke-tested)
- Learning pass can suggest safe small adjustments to `estimated_impact` and `priority_boost`

### Next Steps After MVP
- Enrich outcomes automatically from observability pipelines (metrics job)
- Persist learned rule updates to disk / DB and version them
- Add decay/weighting (recent outcomes > old)
- Add periodic learning worker (cron or background worker)

---

---

## 📝 Example Usage

### Basic Engine Usage

```python
from shopee_agent.decision_engine import (
    DecisionEngine,
    DecisionSignal,
    EconomicContext,
    create_default_rules,
)

# Initialize
engine = DecisionEngine(
    store_id="my_store",
    rules=create_default_rules(),
    log_path="reports/decision_log.jsonl",
)

# Create a signal (e.g., from metrics)
signal = DecisionSignal(
    source="metrics.profitability",
    signal_type="anomaly",
    data={
        "metric": "margin_drop",
        "baseline_margin": 18.0,
        "current_margin": 13.0,
        "anomaly_severity": 0.5,
    },
)

# Build context
context = EconomicContext(
    current_margin_pct=13.0,
    margin_target_pct=18.0,
    daily_revenue_usd=5000.0,
    cash_buffer_usd=50000.0,
    inventory_days_on_hand=15,
    stock_risk_level="normal",
    active_promotions=2,
    advertising_spend_daily_usd=500.0,
    advertising_roas=2.5,
    customer_satisfaction_score=85.0,
    recent_anomalies=[],
)

# Process
decisions = engine.process_signal(signal, context)

# Handle results
for decision in decisions:
    if decision.status == "approved":
        print(f"✓ {decision.title} - Execute now")
    else:
        print(f"✗ {decision.title} - Blocked by guardrails")
```

### Integration with Autonomous Loop

```python
from shopee_agent.decision_integration import DecisionIntegrator

integrator = DecisionIntegrator(engine, "my_store")

# During autonomous_loop cycle
signals = integrator.collect_signals_from_metrics()
context = integrator.build_economic_context()

# Process all signals
result = integrator.process_cycle()
print(f"Decisions approved: {result['decisions_approved']}")
print(f"Critical actions: {result['critical_decisions']}")

# Get pending decisions for autonomous_loop to execute
high_priority = integrator.get_pending_actions(
    min_priority=DecisionPriority.CRITICAL
)

# Execute them
for decision in high_priority:
    execute_decision(decision)  # Route to appropriate handler
    integrator.mark_decision_executed(decision.decision_id)
```

---

## 🔍 Monitoring & Observability

### Key Metrics

```bash
# Check decision quality
laura decision-metrics --days 7

# Output:
# Total Decisions: 42
# Avg Impact: 0.062
# Avg Confidence: 0.71
#
# By Type:
#   pricing           18 (42.9%)
#   ads               15 (35.7%)
#   inventory          9 (21.4%)
#
# By Status:
#   approved          35 (83.3%)
#   rejected           7 (16.7%)
#
# Quality Score: 78.5/100
```

### Health Checks

Decision Engine health in `laura doctor`:

```
Decision Engine
  ✓ Rules loaded: 3
  ✓ Log path accessible: reports/decision_log.jsonl
  ✓ Recent decisions: 42 (last 24h)
  ✓ Approval rate: 83.3%
  ✓ Avg confidence: 0.71
  Status: HEALTHY
```

---

## ⚠️ Limitations (v1.0)

1. **Rules are static**: No dynamic rule learning yet
2. **No memory layer**: Can't leverage past decision outcomes
3. **No multi-step planning**: Each decision is independent
4. **No agent negotiation**: Can't coordinate competing goals
5. **Limited to metrics signals**: Missing webhook/order events
6. **Execution is synchronous**: No async job queuing yet

These are addressed in Phase 35+.

---

## 📚 Related Documentation

- `docs/PHASE_34_DECISION_ENGINE.md` - Full technical spec
- `PROJECT_STRUCTURE.md` - How this fits in Laura
- `autonomous_loop.py` - Integration point
- `decision_cli.py` - Command-line interface
- `tests/test_decision_engine.py` - Implementation reference

---

## ✅ Test Coverage

All 17 unit tests passing:

```
✓ Engine initialization
✓ Rule management
✓ Signal processing (pricing, ads, inventory)
✓ Guardrail evaluation (normal + crisis)
✓ Decision scoring
✓ Audit logging
✓ Decision retrieval & filtering
✓ JSON serialization
```

Run tests:
```bash
pytest tests/test_decision_engine.py -v
```

---

## 👤 Author

Laura Decision Engine v1.0  
Implemented: 2026-05-14  
Status: Production Ready (MVP)

---

## 🎯 Key Takeaway

**Before Phase 34**: 40+ scripts running independently  
**After Phase 34**: Central nervous system coordinating all decisions  
**Result**: Auditable, prioritized, economically-aware autonomous operation

This is the bridge from AI COO to AI CEO. 🚀
