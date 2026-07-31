"""
CLI for Decision Engine Management

Provides commands to:
- View pending decisions
- Check decision history
- Monitor decision quality
- Manually approve/reject decisions
- Generate decision reports

Usage:
    laura decision-status              # Show pending decisions
    laura decision-history             # View decision audit log
    laura decision-approve <id>        # Approve specific decision
    laura decision-reject <id>         # Reject specific decision
    laura decision-metrics             # Show decision quality metrics
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click
from tabulate import tabulate

from shopee_agent.cognitive_memory import LongTermMemory, ReflectionSystem, SemanticMemory
from shopee_agent.decision_engine import (
    DecisionEngine,
    DecisionPriority,
    DecisionRule,
    create_default_rules,
)
from shopee_agent.decision_integration import DecisionIntegrator
from shopee_agent.decision_memory import MemoryLayer
from shopee_agent.vector_store import InMemoryVectorStore

# goal_management not required in CLI commands


def load_engine(store_id: str = "default", rules_enabled: bool = True) -> DecisionEngine:
    """Load or create decision engine. If `reports/rules_state.json` exists, load persisted rules."""
    rules_file = Path("reports/rules_state.json")
    rules = []
    if rules_enabled and rules_file.exists():
        try:
            with open(rules_file) as f:
                data = json.load(f)
                for r in data.get("rules", []):
                    try:
                        rules.append(DecisionRule.from_dict(r))
                    except Exception:
                        continue
        except Exception:
            rules = create_default_rules() if rules_enabled else []
    else:
        rules = create_default_rules() if rules_enabled else []

    return DecisionEngine(
        store_id,
        rules=rules,
        log_path="reports/decision_log.jsonl",
        memory=MemoryLayer(path="reports/decision_outcomes.jsonl", vector_store=InMemoryVectorStore()),
    )


def load_integrator(store_id: str = "default") -> DecisionIntegrator:
    """Load decision integrator."""
    return DecisionIntegrator(store_id, metrics_dir="reports/")


# ============================================================================
# COMMANDS
# ============================================================================

@click.group()
def decision_cli():
    """Decision Engine management commands."""
    pass


@decision_cli.command()
@click.option("--store-id", default="default", help="Store ID")
@click.option("--priority", type=click.Choice(["critical", "high", "all"]), default="all")
def status(store_id: str, priority: str):
    """Show pending decisions."""
    engine = load_engine(store_id)
    integrator = load_integrator(store_id)

    # Get current state
    cycle_info = integrator.last_decision_cycle or {}

    click.secho("\n═══════════════════════════════════════════════════", fg="cyan", bold=True)
    click.secho("  LAURA DECISION ENGINE - STATUS", fg="cyan", bold=True)
    click.secho("═══════════════════════════════════════════════════\n", fg="cyan", bold=True)

    # Engine summary
    summary = engine.summary()
    click.echo(f"Store: {summary['store_id']}")
    click.echo(f"Rules: {summary['total_rules']}")
    click.echo(f"Pending Decisions: {summary['pending_decisions']}")
    click.echo(f"Critical: {summary['critical_decisions']}")

    if cycle_info:
        click.echo(f"\nLast Cycle: {cycle_info.get('timestamp', 'N/A')}")
        click.echo(f"  Signals Received: {cycle_info.get('signals_received', 0)}")
        click.echo(f"  Decisions Approved: {cycle_info.get('decisions_approved', 0)}")
        click.echo(f"  Decisions Rejected: {cycle_info.get('decisions_rejected', 0)}")

    # Get pending decisions
    min_priority = None
    if priority == "critical":
        min_priority = DecisionPriority.CRITICAL
    elif priority == "high":
        min_priority = DecisionPriority.HIGH

    pending = engine.get_pending_decisions(min_priority=min_priority)

    if pending:
        click.echo(f"\n{len(pending)} Pending Decisions:\n")

        table_data = []
        for decision in pending[:10]:  # Show top 10
            table_data.append([
                decision.decision_id[:12],
                decision.decision_type.value,
                decision.priority.name,
                f"{decision.impact_score:.2f}",
                f"{decision.confidence_score:.2f}",
                decision.status.value,
            ])

        headers = ["ID", "Type", "Priority", "Impact", "Confidence", "Status"]
        click.echo(tabulate(table_data, headers=headers, tablefmt="grid"))
    else:
        click.secho("\n✓ No pending decisions", fg="green")

    click.echo()


@decision_cli.command()
@click.option("--store-id", default="default")
@click.option("--limit", default=20, help="Number of recent decisions to show")
@click.option("--type", "decision_type", type=click.Choice(["pricing", "ads", "inventory", "all"]), default="all")
def history(store_id: str, limit: int, decision_type: str):
    """Show decision history from audit log."""
    log_path = Path("reports/decision_log.jsonl")

    if not log_path.exists():
        click.secho("✗ No decision log found", fg="red")
        return

    click.secho("\n═══════════════════════════════════════════════════", fg="cyan", bold=True)
    click.secho("  DECISION HISTORY", fg="cyan", bold=True)
    click.secho("═══════════════════════════════════════════════════\n", fg="cyan", bold=True)

    # Read log
    decisions = []
    with open(log_path) as f:
        for line in f:
            try:
                decision = json.loads(line)
                if decision_type != "all" and decision.get("decision_type") != decision_type:
                    continue
                decisions.append(decision)
            except json.JSONDecodeError:
                pass

    # Show recent decisions
    recent = decisions[-limit:]

    if not recent:
        click.secho("✓ No decisions in history", fg="green")
        return

    table_data = []
    for d in recent:
        table_data.append([
            d.get("decision_id", "?")[:12],
            d.get("decision_type", "?"),
            d.get("priority", "?"),
            f"{d.get('impact_score', 0):.2f}",
            d.get("status", "?"),
            d.get("created_at", "?")[:16],
        ])

    headers = ["ID", "Type", "Priority", "Impact", "Status", "Created"]
    click.echo(tabulate(table_data, headers=headers, tablefmt="grid"))
    click.echo(f"\nTotal decisions logged: {len(decisions)}")
    click.echo()


@decision_cli.command()
@click.argument("decision_id")
@click.option("--store-id", default="default")
def detail(decision_id: str, store_id: str):
    """Show detailed decision information."""
    log_path = Path("reports/decision_log.jsonl")

    if not log_path.exists():
        click.secho("✗ No decision log found", fg="red")
        return

    # Find decision in log
    decision = None
    with open(log_path) as f:
        for line in f:
            try:
                d = json.loads(line)
                if d.get("decision_id", "").startswith(decision_id):
                    decision = d
                    break
            except json.JSONDecodeError:
                pass

    if not decision:
        click.secho(f"✗ Decision not found: {decision_id}", fg="red")
        return

    click.secho("\n═══════════════════════════════════════════════════", fg="cyan", bold=True)
    click.secho("  DECISION DETAILS", fg="cyan", bold=True)
    click.secho("═══════════════════════════════════════════════════\n", fg="cyan", bold=True)

    # Format decision details
    click.echo(f"ID:           {decision['decision_id']}")
    click.echo(f"Title:        {decision['title']}")
    click.echo(f"Type:         {decision['decision_type']}")
    click.echo(f"Priority:     {decision['priority']}")
    click.echo(f"Status:       {decision['status']}")
    click.echo("Created:      {}".format(decision['created_at']))

    click.echo("\nScoring:")
    click.echo("  Impact:      {:.3f} ({:+.1f}%)".format(decision['impact_score'], decision['impact_score']*100))
    click.echo("  Risk:        {:.3f} (0-1)".format(decision['risk_score']))
    click.echo(f"  Confidence:  {decision['confidence_score']:.3f}")

    click.echo("\nAction:")
    click.echo("  {}".format(decision['recommended_action']))

    click.echo("\nReasoning:")
    click.echo("  {}".format(decision['reasoning']))

    if decision.get('guardrails_passed'):
        click.echo("\nGuardrails:")
        for guard, passed in decision['guardrails_passed'].items():
            status = "✓ PASS" if passed else "✗ FAIL"
            click.secho(f"  {guard}: {status}", fg="green" if passed else "red")

    if decision.get('assumptions'):
        click.echo("\nAssumptions:")
        for assumption in decision['assumptions']:
            click.echo(f"  • {assumption}")

    click.echo()


@decision_cli.command()
@click.option("--store-id", default="default")
def cycle(store_id: str):
    """Run a decision evaluation cycle."""
    integrator = load_integrator(store_id)

    click.secho("\n═══════════════════════════════════════════════════", fg="cyan", bold=True)
    click.secho("  RUNNING DECISION CYCLE", fg="cyan", bold=True)
    click.secho("═══════════════════════════════════════════════════\n", fg="cyan", bold=True)

    click.echo("Collecting signals...")
    signals = integrator.collect_signals_from_metrics()
    click.echo(f"  ✓ {len(signals)} signals collected")

    click.echo("Building economic context...")
    context = integrator.build_economic_context()
    click.echo(f"  ✓ Context built (margin={context.current_margin_pct:.1f}%)")

    click.echo("Processing decisions...")
    result = integrator.process_cycle()

    click.echo("\nCycle Results:")
    click.echo("  Signals:       {}".format(result['signals_received']))
    click.echo("  Approved:      {}".format(result['decisions_approved']))
    click.echo(f"  Rejected:      {result['decisions_rejected']}")
    click.echo(f"  Critical:      {result['critical_decisions']}")

    click.secho("\n✓ Cycle complete", fg="green")
    click.echo()


@decision_cli.command()
@click.option("--store-id", default="default")
@click.option("--days", default=7, help="Number of days to analyze")
def metrics(store_id: str, days: int):
    """Show decision quality metrics."""
    log_path = Path("reports/decision_log.jsonl")

    if not log_path.exists():
        click.secho("✗ No decision log found", fg="red")
        return

    click.secho("\n═══════════════════════════════════════════════════", fg="cyan", bold=True)
    click.secho(f"  DECISION METRICS (Last {days} days)", fg="cyan", bold=True)
    click.secho("═══════════════════════════════════════════════════\n", fg="cyan", bold=True)

    # Analyze decisions
    cutoff_time = datetime.now(UTC) - timedelta(days=days)
    decisions = []

    with open(log_path) as f:
        for line in f:
            try:
                d = json.loads(line)
                created = datetime.fromisoformat(d.get("created_at", "").replace("Z", "+00:00"))
                if created >= cutoff_time:
                    decisions.append(d)
            except (json.JSONDecodeError, ValueError):
                pass

    if not decisions:
        click.secho("✗ No decisions in this period", fg="red")
        return

    # Calculate metrics
    by_type = {}
    by_status = {}
    total_impact = 0
    avg_confidence = 0

    for d in decisions:
        dtype = d.get("decision_type", "unknown")
        status = d.get("status", "unknown")

        by_type[dtype] = by_type.get(dtype, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1

        total_impact += d.get("impact_score", 0)
        avg_confidence += d.get("confidence_score", 0)

    avg_confidence = avg_confidence / len(decisions) if decisions else 0
    avg_impact = total_impact / len(decisions) if decisions else 0

    # Display
    click.echo(f"Total Decisions: {len(decisions)}")
    click.echo(f"Avg Impact:      {avg_impact:.3f}")
    click.echo(f"Avg Confidence:  {avg_confidence:.3f}")

    click.echo("\nBy Type:")
    for dtype, count in sorted(by_type.items()):
        pct = (count / len(decisions)) * 100
        click.echo(f"  {dtype:15} {count:3} ({pct:5.1f}%)")

    click.echo("\nBy Status:")
    for status, count in sorted(by_status.items()):
        pct = (count / len(decisions)) * 100
        click.echo(f"  {status:15} {count:3} ({pct:5.1f}%)")

    # Quality score
    approved_pct = (by_status.get("approved", 0) / len(decisions)) * 100 if decisions else 0
    quality_score = (approved_pct * 0.5) + (avg_confidence * 50)

    color = "green" if quality_score > 70 else "yellow" if quality_score > 50 else "red"
    click.secho(f"\nQuality Score: {quality_score:.1f}/100", fg=color, bold=True)
    click.echo()


@decision_cli.command()
@click.option("--store-id", default="default")
@click.option("--backend", default="memory", type=click.Choice(["memory", "annoy", "faiss"]))
@click.option("--dim", default=128, type=int, help="Vector dimensionality for backend")
@click.option("--index-path", default=None, help="Index file path (for annoy/faiss)")
@click.option("--meta-path", default=None, help="Meta sidecar path (for annoy/faiss)")
@click.option("--annoy-n-trees", default=10, type=int, help="Annoy n_trees (if using annoy)")
@click.option("--apply/--no-apply", default=False, help="Write backend config to reports/vector_backend_config.json")
def reindex_backend(store_id: str, backend: str, dim: int, index_path: str, meta_path: str, annoy_n_trees: int, apply: bool):
    """Rebuild vector backend from the vectors sidecar (reports/decision_vectors.jsonl).

    This command will instantiate the chosen backend and populate it from the
    configured sidecar file. It is useful for operational recovery and testing.
    """
    click.secho(f"Reindexing vectors to backend={backend} (dim={dim})", fg="cyan")

    vectors_path = Path("reports/decision_vectors.jsonl")
    mem = MemoryLayer(path="reports/decision_outcomes.jsonl", vector_store=None, vectors_path=str(vectors_path))

    annoy_opts = {"n_trees": annoy_n_trees}
    try:
        store = mem.reindex_to_backend(backend=backend, dim=dim, index_path=index_path, meta_path=meta_path, annoy_options=annoy_opts)
        click.secho(f"Reindex complete. Backend instantiated: {type(store).__name__}", fg="green")
        if apply:
            # Persist a small config so services can pick up preferred backend
            try:
                cfg = {
                    "backend": backend,
                    "dim": dim,
                    "index_path": index_path,
                    "meta_path": meta_path,
                    "annoy_n_trees": annoy_n_trees,
                }
                Path("reports").mkdir(parents=True, exist_ok=True)
                with open(Path("reports") / "vector_backend_config.json", "w", encoding="utf-8") as fh:
                    import json as _json

                    fh.write(_json.dumps(cfg, ensure_ascii=False, indent=2))
                click.secho("Applied configuration to reports/vector_backend_config.json", fg="green")
            except Exception as e:  # pragma: no cover - best-effort write
                click.secho(f"Failed to write config file: {e}", fg="yellow")
    except Exception as e:
        click.secho(f"Reindex failed: {e}", fg="red")


@decision_cli.command(name="outcomes")
@click.option("--store-id", default="default")
@click.option("--limit", default=20, help="Number of recent outcomes to show")
@click.option("--days", default=None, type=int, help="Filter to last N days")
def outcomes(store_id: str, limit: int, days: int | None = None):
    """Show recent decision outcomes from the memory store."""
    from datetime import timedelta
    mem = MemoryLayer(path="reports/decision_outcomes.jsonl")
    outs = mem.list_outcomes(limit=limit * 2)  # fetch extra for filtering

    if days:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        outs = [o for o in outs if o.executed_at and o.executed_at >= cutoff]

    if not outs:
        click.secho("✓ No decision outcomes recorded", fg="green")
        return

    table = []
    for o in outs[-limit:]:
        table.append([
            o.decision_id[:12],
            o.rule_id,
            o.outcome_type,
            f"{o.impact_realized if o.impact_realized is not None else 'N/A'}",
            o.executed_at.isoformat()[:19] if o.executed_at else "N/A",
        ])

    headers = ["ID", "Rule", "Outcome", "Impact", "Executed"]
    click.echo(tabulate(table, headers=headers, tablefmt="grid"))
    click.echo()


@decision_cli.command()
@click.option("--store-id", default="default")
@click.option("--apply-updates", is_flag=True, help="Apply learned updates to in-memory rules")
def learn(store_id: str, apply_updates: bool):
    """Run learning pass: compute rule effectiveness and optionally update rules."""
    engine = load_engine(store_id)
    mem = MemoryLayer(path="reports/decision_outcomes.jsonl")

    click.secho("\nRunning learning pass...", fg="cyan")
    report = []
    for rule_id, rule in engine.rules.items():
        eff = mem.get_rule_effectiveness(rule_id)
        orig_impact = rule.estimated_impact.get("margin", 0.0)

        change = 0.0
        if eff > 0.6:
            # boost impact estimate by 10%
            change = orig_impact * 0.10 if orig_impact else 0.01
            if apply_updates:
                rule.estimated_impact["margin"] = orig_impact + change
        elif eff < 0.4:
            # reduce impact estimate by 10% and reduce priority_boost
            change = -(orig_impact * 0.10) if orig_impact else -0.01
            if apply_updates:
                rule.estimated_impact["margin"] = max(0.0, orig_impact + change)
                rule.priority_boost = max(0, rule.priority_boost - 1)

        report.append((rule_id, eff, orig_impact, change))

    # Display report
    table = []
    for r in report:
        table.append([r[0], f"{r[1]:.2f}", f"{r[2]:.3f}", f"{r[3]:+.3f}"])

    click.echo(tabulate(table, headers=["Rule", "Effectiveness", "OrigImpact", "Delta"]))

    if apply_updates:
        # persist rules to reports/rules_state.json
        rules_file = Path("reports/rules_state.json")
        try:
            rules_file.parent.mkdir(parents=True, exist_ok=True)
            out = {"updated_at": datetime.now(UTC).isoformat(), "rules": []}
            for rule in engine.rules.values():
                try:
                    out["rules"].append(rule.to_dict())
                except Exception:
                    continue
            with open(rules_file, "w") as f:
                json.dump(out, f, indent=2)
            click.secho("\n✓ Updates applied and persisted to reports/rules_state.json", fg="green")
        except Exception as e:
            click.secho(f"\n⚠️ Failed to persist rules: {e}", fg="red")
    else:
        click.secho("\nRun again with --apply-updates to modify in-memory rules", fg="yellow")
    click.echo()


@decision_cli.command(name="effectiveness")
@click.option("--rule", default=None, help="Filter by rule ID")
@click.option("--store-id", default="default")
def effectiveness(rule: str | None, store_id: str):
    """Show rule effectiveness scores from outcome memory."""
    mem = MemoryLayer(path="reports/decision_outcomes.jsonl")
    engine = load_engine(store_id)

    if rule:
        rule_ids = [rule] if rule in engine.rules else []
    else:
        rule_ids = list(engine.rules.keys())

    if not rule_ids:
        click.secho("✓ No rules found", fg="green")
        return

    table = []
    for rid in rule_ids:
        eff = mem.get_rule_effectiveness(rid)
        pred = mem.predict_outcome_for_rule(rid)
        rule_obj = engine.rules.get(rid)
        table.append([
            rid,
            f"{eff:.2f}",
            f"{pred:.3f}",
            rule_obj.priority_boost if rule_obj else 0,
            rule_obj.effectiveness_score if rule_obj else eff,
        ])

    click.echo(tabulate(table, headers=["Rule", "Effectiveness", "PredImpact", "PriorityBoost", "AdaptiveScore"], tablefmt="grid"))


@decision_cli.command(name="similar")
@click.argument("decision_id")
@click.option("--top-k", default=5, type=int, help="Number of similar decisions to show")
@click.option("--store-id", default="default")
def similar(decision_id: str, top_k: int, store_id: str):
    """Find similar past decisions by outcome metadata."""
    mem = MemoryLayer(path="reports/decision_outcomes.jsonl")

    target = None
    for o in mem._cache:
        if o.decision_id == decision_id:
            target = o
            break

    if target is None:
        click.secho(f"Decision not found: {decision_id}", fg="red")
        return

    signal = {"rule_id": target.rule_id, "type": target.outcome_type, "metric": target.metadata.get("decision_type", "")}
    similar_outs = mem.rank_similar_decisions(signal, limit=top_k + 1)

    table = []
    for o in similar_outs:
        if o.decision_id == decision_id:
            continue
        table.append([
            o.decision_id[:12],
            o.rule_id,
            o.outcome_type,
            f"{o.impact_realized if o.impact_realized is not None else 'N/A'}",
        ])

    if not table:
        click.secho("No similar decisions found", fg="yellow")
    else:
        click.echo(tabulate(table, headers=["ID", "Rule", "Outcome", "Impact"], tablefmt="grid"))


@decision_cli.command(name="dashboard")
@click.option("--live", is_flag=True, help="Watch metrics every 5s (Ctrl+C to stop)")
def cmd_dashboard(live: bool) -> None:
    """Show live dashboard of system metrics from the event bus."""
    from shopee_agent.event_bus import AsyncEventBus, MetricUpdateEvent
    from shopee_agent.workers import MetricWorker
    bus = AsyncEventBus(worker_count=1)
    bus.start()
    worker = MetricWorker(bus)
    worker.subscribe()

    def _render(recent):
        import rich.console

        console = rich.console.Console()
        console.clear()
        console.rule("[bold cyan]Laura Dashboard")
        if not recent:
            console.print("[yellow]No metrics received yet.")
        else:
            m = recent[-1]
            console.print(f"  Events processed:  [green]{bus.stats().processed}")
            metrics = m.metrics if hasattr(m, "metrics") else {}
            for k, v in metrics.items():
                console.print(f"  {k}: [green]{v}")
        console.rule()

    recent = []
    bus.register_handler("metric_update", lambda e: recent.append(e))

    if live:
        import time
        try:
            while True:
                _render(recent)
                time.sleep(5)
        except KeyboardInterrupt:
            pass
    else:
        from shopee_agent.metrics import collect_laura_metrics
        m = collect_laura_metrics()
        bus.submit(MetricUpdateEvent(metrics=m))
        bus.wait_until_idle(timeout=3)
        _render(recent)

    bus.stop()


@decision_cli.command(name="memory-summary")
@click.option("--limit", default=10, help="Number of recent notes to include")
def memory_summary(limit: int):
    """Show long-term memory summary."""
    memory = LongTermMemory()
    summary = memory.overview(limit=limit)
    click.echo(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


@decision_cli.command(name="memory-search")
@click.argument("query")
@click.option("--limit", default=10, help="Max results")
def memory_search(query: str, limit: int):
    """Search long-term memory with lightweight semantic matching."""
    memory = SemanticMemory()
    results = memory.search(query, limit=limit)
    click.echo(json.dumps({"query": query, "count": len(results), "results": results}, ensure_ascii=False, indent=2, sort_keys=True))


@decision_cli.command(name="memory-reflect")
@click.option("--limit", default=100, help="Recent outcomes to analyze")
def memory_reflect(limit: int):
    """Generate a reflection report from stored outcomes."""
    reflection = ReflectionSystem()
    report = reflection.reflect(limit=limit)
    click.echo(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


@decision_cli.command(name="goal-summary")
@click.option("--store-id", default="default")
def goal_summary(store_id: str):
    """Show the current goal snapshot and ranking."""
    integrator = load_integrator(store_id)
    snapshot = integrator.goal_manager.snapshot(context=integrator.build_economic_context(), priority_engine=integrator.priority_engine)
    click.echo(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))


@decision_cli.command(name="goal-list")
@click.option("--store-id", default="default")
@click.option("--status", default="active", type=click.Choice(["active", "completed", "all"]))
def goal_list(store_id: str, status: str):
    """List registered goals."""
    integrator = load_integrator(store_id)
    manager = integrator.goal_manager
    goals = manager.list_goals(None if status == "all" else status)

    if not goals:
        click.secho("✓ No goals registered", fg="green")
        return

    ranked = manager.rank_goals(context=integrator.build_economic_context(), priority_engine=integrator.priority_engine, status=None if status == "all" else status)
    score_map = {item["goal"]["goal_id"]: item["score"] for item in ranked}

    table_data = []
    for goal in goals:
        table_data.append([
            goal.goal_id[:12],
            goal.name,
            goal.status,
            goal.priority,
            f"{score_map.get(goal.goal_id, 0.0):.1f}",
            goal.duration_days,
        ])

    click.echo(tabulate(table_data, headers=["ID", "Name", "Status", "Priority", "Score", "Days"], tablefmt="grid"))


@decision_cli.command(name="goal-add")
@click.argument("name")
@click.argument("objective")
@click.option("--metric", "metrics", multiple=True, help="Target metric in key=value format")
@click.option("--budget", default=0.0, type=float)
@click.option("--days", default=30, type=int)
@click.option("--priority", default=3, type=int)
@click.option("--tag", "tags", multiple=True)
@click.option("--store-id", default="default")
def goal_add(name: str, objective: str, metrics: tuple[str, ...], budget: float, days: int, priority: int, tags: tuple[str, ...], store_id: str):
    """Register a new goal."""
    integrator = load_integrator(store_id)
    target_metrics: dict[str, float] = {}
    for metric in metrics:
        if "=" not in metric:
            raise click.BadParameter("Metrics must use key=value format")
        key, value = metric.split("=", 1)
        target_metrics[key.strip()] = float(value)

    goal = integrator.goal_manager.register_goal(
        name=name,
        objective=objective,
        target_metrics=target_metrics,
        budget=budget,
        duration_days=days,
        priority=priority,
        tags=list(tags),
    )
    click.echo(json.dumps(goal.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))


@decision_cli.command(name="goal-top")
@click.option("--store-id", default="default")
def goal_top(store_id: str):
    """Show the highest priority goal."""
    integrator = load_integrator(store_id)
    top_goal = integrator.goal_manager.top_goal(context=integrator.build_economic_context(), priority_engine=integrator.priority_engine)
    if not top_goal:
        click.secho("✓ No goals registered", fg="green")
        return
    click.echo(json.dumps(top_goal.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))


@decision_cli.command(name="goal-complete")
@click.argument("goal_id")
@click.option("--note", default=None)
@click.option("--store-id", default="default")
def goal_complete(goal_id: str, note: str | None, store_id: str):
    """Mark a goal as completed."""
    integrator = load_integrator(store_id)
    goal = integrator.goal_manager.complete_goal(goal_id, note=note)
    if goal is None:
        raise click.ClickException(f"Goal not found: {goal_id}")
    click.echo(json.dumps(goal.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))


# ============================================================================
# CLI INTEGRATION
# ============================================================================

def register_decision_commands(cli_group):
    """Register decision commands with main CLI group."""
    cli_group.add_command(status, name="decision-status")
    cli_group.add_command(history, name="decision-history")
    cli_group.add_command(detail, name="decision-detail")
    cli_group.add_command(cycle, name="decision-cycle")
    cli_group.add_command(metrics, name="decision-metrics")
    cli_group.add_command(memory_summary, name="memory-summary")
    cli_group.add_command(memory_search, name="memory-search")
    cli_group.add_command(memory_reflect, name="memory-reflect")
    cli_group.add_command(goal_summary, name="goal-summary")
    cli_group.add_command(goal_list, name="goal-list")
    cli_group.add_command(goal_add, name="goal-add")
    cli_group.add_command(goal_top, name="goal-top")
    cli_group.add_command(goal_complete, name="goal-complete")
    # Phase 35: Memory & Learning Layer commands
    cli_group.add_command(outcomes, name="decision-outcomes")
    cli_group.add_command(learn, name="decision-learn")
    cli_group.add_command(reindex_backend, name="decision-reindex-backend")
    cli_group.add_command(effectiveness, name="decision-effectiveness")
    cli_group.add_command(similar, name="decision-similar")
    cli_group.add_command(cmd_dashboard, name="dashboard")


if __name__ == "__main__":
    decision_cli()
