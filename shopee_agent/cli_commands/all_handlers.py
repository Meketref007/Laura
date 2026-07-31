"""Consolidated handler dispatch for all CLI commands not yet extracted.

This module collects all command handlers from cli.py's main() dispatch section
into a single place, keyed by command name. The handlers are organized into
groups by domain for maintainability.

Usage:
    from shopee_agent.cli_commands.all_handlers import HANDLER_DISPATCH
    handler_fn = HANDLER_DISPATCH.get(args.command)
    if handler_fn:
        return handler_fn(args, client=client, cfg=cfg)
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# ── Lazy module loading ────────────────────────────────────────────────────
# Handler modules (vision, pricing, chat, telegram, ...) drag in heavy
# dependencies (numpy, pandas, playwright, fastapi, ...). They are loaded on
# first use so `laura --help` starts in well under 0.5s.

_LAZY_MODULES: dict[str, str] = {
    # command-name -> module path (loaded on first use)
    "flash_sale": "shopee_agent.flash_sale_executor",
    "campaign": "shopee_agent.campaign_manager",
    "cross-sell": "shopee_agent.cross_selling",
    "vision": "shopee_agent.vision",
    "report": "shopee_agent.reporting",
    "pricing": "shopee_agent.pricing_automation",
    "workers": "shopee_agent.workers_management",
    "chat": "shopee_agent.chat_auto",
    "telegram": "shopee_agent.telegram_bot",
    "plugin": "shopee_agent.plugin_system",
    "plugin-sdk": "shopee_agent.plugin_sdk",
    # add more as needed
}

_loaded: dict[str, Any] = {}
_start = time.perf_counter()


def get_lazy_module(command: str) -> Any:
    """Import and return a module on first use, caching subsequent lookups."""
    mod_name = _LAZY_MODULES.get(command)
    if not mod_name:
        return None
    if mod_name not in _loaded:
        _loaded[mod_name] = importlib.import_module(mod_name)
    return _loaded[mod_name]


def lazy_import(module_path: str) -> Any:
    """Import any module lazily (one-shot, cached)."""
    if module_path not in _loaded:
        _loaded[module_path] = importlib.import_module(module_path)
    return _loaded[module_path]

# ── Skill handlers ──────────────────────────────────────────────────────────


def _handle_skill_list(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.registry import default_registry
    registry = default_registry
    names = registry.list()
    from tabulate import tabulate
    table = []
    for n in names:
        cls = registry.get(n)
        table.append([n, getattr(cls, "cost", "?"), getattr(cls, "priority", "?"),
                      str(getattr(cls, "preconditions", {})), str(getattr(cls, "effects", {}))])
    print(tabulate(table, headers=["Name", "Cost", "Priority", "Preconditions", "Effects"], tablefmt="grid"))
    return 0


def _handle_skill_register(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.loader import import_skill_class
    from shopee_agent.skills.registry import default_registry
    registry = default_registry
    if args.module:
        cls = import_skill_class(args.module, args.name)
    elif args.path:
        import importlib.util
        spec = importlib.util.spec_from_file_location(args.name, args.path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cls = getattr(mod, args.name)
    else:
        _print_json({"error": "provide --module or --path"})
        return 1
    if cls is None:
        _print_json({"error": f"class {args.name} not found"})
        return 1
    registry.register(cls)
    _print_json({"registered": args.name})
    return 0


def _handle_skill_history(args, client=None, cfg=None) -> int:
    import json as _j

    from shopee_agent.skills.learning import load_learning_history
    from shopee_agent.skills.registry import default_registry
    hist = load_learning_history(default_registry)
    from tabulate import tabulate
    if args.learning:
        costs = _j.loads(Path("reports/goap_learning.json").read_text()) if Path("reports/goap_learning.json").exists() else {}
        table = [[k, v.get("current_cost", "?"), v.get("base_cost", "?"), v.get("success_count", 0), v.get("failure_count", 0)] for k, v in costs.items()]
        print(tabulate(table, headers=["Skill", "Current Cost", "Base Cost", "Success", "Failure"], tablefmt="grid"))
    else:
        table = [[h.skill_name, h.timestamp, h.cost, h.success] for h in hist[:args.limit]]
        print(tabulate(table, headers=["Skill", "Time", "Cost", "Success"], tablefmt="grid"))
    return 0


# ── Goal handlers ────────────────────────────────────────────────────────────


def _handle_goal_summary(args, client=None, cfg=None) -> int:
    from click.testing import CliRunner

    from shopee_agent.decision_cli import goal_summary as gs_cmd
    runner = CliRunner()
    argv = ["--store-id", getattr(args, "store_id", "shop-1")]
    if getattr(args, "status", None):
        argv += ["--status", args.status]
    result = runner.invoke(gs_cmd, argv)
    print(result.output)
    return result.exit_code if result.exit_code else 0


def _handle_goal_list(args, client=None, cfg=None) -> int:
    from click.testing import CliRunner

    from shopee_agent.decision_cli import goal_list as gl_cmd
    runner = CliRunner()
    argv = ["--store-id", getattr(args, "store_id", "shop-1")]
    if getattr(args, "status", None):
        argv += ["--status", args.status]
    result = runner.invoke(gl_cmd, argv)
    print(result.output)
    return result.exit_code if result.exit_code else 0


def _handle_goal_add(args, client=None, cfg=None) -> int:
    import json as _j

    from shopee_agent.goal_management import GoalManager
    gm = GoalManager()
    goals = _j.loads(args.goals)
    result = gm.add_goals(goals)
    _print_json({"added": result})
    return 0


def _handle_goal_top(args, client=None, cfg=None) -> int:
    from shopee_agent.goal_management import GoalManager
    gm = GoalManager()
    _print_json({"top_goals": gm.top_goals(args.limit)})
    return 0


def _handle_goal_complete(args, client=None, cfg=None) -> int:
    from shopee_agent.goal_management import GoalManager
    gm = GoalManager()
    ok = gm.complete_goal(args.goal_id)
    _print_json({"completed": ok})
    return 0


# ── Strategic / Orchestration handlers ──────────────────────────────────────


def _handle_strategic_plan(args, client=None, cfg=None) -> int:
    import json as _j

    from shopee_agent.decision_engine import default_economic_context
    from shopee_agent.strategic_planner import GoalStack, StrategicPlanner
    ctx_kwargs = {}
    if getattr(args, "context_file", None):
        with open(args.context_file) as f:
            ctx_kwargs = _j.load(f)
    ctx = default_economic_context(**ctx_kwargs)
    planner = StrategicPlanner()
    goals = GoalStack()
    result = planner.create_and_assess(goals, ctx)
    plan = result.get("plan")
    if not plan:
        _print_json({"error": "no plan generated"})
        return 0
    from tabulate import tabulate
    print(f"\n=== Strategic Plan: {plan.name} ===")
    print(f"Objective: {plan.objective} | Status: {plan.status.value} | Budget: ${plan.budget:.0f}")
    phases_table = []
    for p in plan.phases:
        phases_table.append([p.phase_id, p.name, f"{p.duration_days}d", ", ".join(p.actions[:3])])
    print(tabulate(phases_table, headers=["ID", "Phase", "Duration", "Actions"], tablefmt="grid"))
    timeline = result.get("timeline")
    if timeline:
        print(f"\nTimeline: {timeline.total_duration_days} days total")
    assessment = result.get("assessment")
    if assessment:
        print(f"Assessment: {assessment.status.value} | Gates: {len(assessment.completed_gates)}/{len(assessment.failing_gates)}")
    return 0


# ── Trace / Insights ────────────────────────────────────────────────────────


def _handle_trace(args, client=None, cfg=None) -> int:
    from shopee_agent.event_bus import AsyncEventBus
    bus = AsyncEventBus()
    spans = []
    if args.follow:
        for _ in range(args.limit):
            try:
                event = bus._queue.get(timeout=2)
                spans.append({"type": event.event_type, "source": event.source, "time": str(getattr(event, "timestamp", ""))})
            except Exception:
                break
    _print_json({"spans": spans or "no_spans", "hint": "use --follow to tail events"})
    return 0


def _handle_insights_trend(args, client=None, cfg=None) -> int:
    from shopee_agent.insights_llm import analyze_trends
    result = analyze_trends()
    _print_json(result)
    return 0


def _handle_insights_anomaly(args, client=None, cfg=None) -> int:
    from shopee_agent.insights_llm import detect_anomalies
    result = detect_anomalies(args.metric)
    _print_json(result)
    return 0


def _handle_insights_recommendations(args, client=None, cfg=None) -> int:
    from shopee_agent.insights_llm import generate_recommendations
    result = generate_recommendations(args.focus)
    _print_json(result)
    return 0


def _handle_insights_summary(args, client=None, cfg=None) -> int:
    from shopee_agent.insights_llm import generate_executive_summary
    from shopee_agent.paths import PROFITABILITY_LATEST
    data = {}
    if PROFITABILITY_LATEST.exists():
        data = json.loads(PROFITABILITY_LATEST.read_text())
    summary = generate_executive_summary(data)
    print(summary)
    return 0


# ── Analytics / Charts ──────────────────────────────────────────────────────


def _handle_analytics_trends(args, client=None, cfg=None) -> int:
    from shopee_agent.analytics_trending import analyze_trends as at
    result = at()
    _print_json(result)
    return 0


def _handle_charts(args, client=None, cfg=None) -> int:
    from shopee_agent.charts import generate_chart
    result = generate_chart(args.chart_type, args.metric)
    _print_json({"status": "ok" if result else "error"})
    return 0


def _handle_chart_dashboard(args, client=None, cfg=None) -> int:
    from shopee_agent.charts import generate_dashboard
    result = generate_dashboard()
    _print_json({"status": "ok" if result else "error"})
    return 0


# ── Plan handlers ────────────────────────────────────────────────────────────


def _handle_plan_viz(args, client=None, cfg=None) -> int:
    import json as _j

    from shopee_agent.plan_viz import plan_to_gantt, plan_to_mermaid
    plan = _j.loads(args.plan)
    if args.format == "mermaid":
        print(plan_to_mermaid(plan))
    elif args.format == "gantt":
        print(plan_to_gantt(plan))
    if args.output:
        ext = "mmd" if args.format == "mermaid" else "gantt"
        Path(args.output).write_text(locals().get("output", ""), encoding="utf-8")
    return 0


def _handle_plan_diff(args, client=None, cfg=None) -> int:
    import json as _j

    from shopee_agent.plan_store import PlanStore, diff_plans
    store = PlanStore()
    plan_a = store.get(args.plan_a) or _j.loads(args.plan_a)
    plan_b = store.get(args.plan_b) or _j.loads(args.plan_b)
    result = diff_plans(plan_a, plan_b)
    _print_json(result)
    return 0


def _handle_plan_export(args, client=None, cfg=None) -> int:
    from shopee_agent.plan_store import PlanStore
    store = PlanStore()
    data = store.export_plan(args.plan_id)
    path = Path(args.output or f"reports/plan_{args.plan_id}.json")
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _print_json({"exported": args.plan_id, "path": str(path)})
    return 0


def _handle_plan_import(args, client=None, cfg=None) -> int:
    import json as _j

    from shopee_agent.plan_store import PlanStore
    store = PlanStore()
    data = _j.loads(Path(args.input).read_text())
    plan_id = store.import_plan(data)
    _print_json({"imported": plan_id})
    return 0


def _handle_plan_batch(args, client=None, cfg=None) -> int:
    import json as _j

    from shopee_agent.plan_store import PlanStore
    store = PlanStore()
    plans_input = _j.loads(args.plans)
    results = []
    for p in plans_input:
        results.append(store.save(p))
    _print_json({"saved": len(results)})
    return 0


def _handle_plan_store(args, client=None, cfg=None) -> int:

    from shopee_agent.plan_store import PlanStore
    store = PlanStore()
    if args.action == "list":
        plans = store.list_plans()
        from tabulate import tabulate
        table = [[p.plan_id[:8], p.goal, p.status, p.total_cost, p.created_at] for p in plans]
        print(tabulate(table, headers=["ID", "Goal", "Status", "Cost", "Created"], tablefmt="grid"))
    elif args.action == "get":
        plan = store.get(args.plan_id)
        _print_json(plan.to_dict() if hasattr(plan, "to_dict") else {"error": "not found"})
    elif args.action == "delete":
        ok = store.delete(args.plan_id)
        _print_json({"deleted": ok})
    return 0


def _handle_planner_alerts(args, client=None, cfg=None) -> int:
    import json as _j

    from shopee_agent.planner_alerts import evaluate_planner_alerts
    context = _j.loads(args.context) if args.context else {}
    result = evaluate_planner_alerts(context)
    _print_json(result)
    return 0


def _handle_plan_template(args, client=None, cfg=None) -> int:
    import json as _j

    from shopee_agent.plan_templates import resolve_template
    params = _j.loads(args.params) if args.params else {}
    result = resolve_template(args.template_name, params)
    _print_json(result)
    return 0


def _handle_goal_library(args, client=None, cfg=None) -> int:
    from shopee_agent.goal_library import get_template, list_templates
    if args.action == "list":
        templates = list_templates()
        _print_json({"templates": templates, "count": len(templates)})
    elif args.action == "get":
        tpl = get_template(args.template_name)
        _print_json(tpl if tpl else {"error": "not found"})
    return 0


# ── Skill lifecycle handlers ────────────────────────────────────────────────


def _handle_skill_create(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.scaffold import write_skill_file
    result = write_skill_file(
        skill_name=args.skill_name,
        preconditions=json.loads(args.preconditions) if args.preconditions else {},
        effects=json.loads(args.effects) if args.effects else {},
        cost=args.cost,
        priority=args.priority,
        output_dir=args.output_dir or "shopee_agent/skills",
    )
    _print_json(result)
    return 0


def _handle_skill_simulate(args, client=None, cfg=None) -> int:
    import json as _j

    from shopee_agent.skills.sandbox import simulate_skill
    params = _j.loads(args.params) if args.params else {}
    result = simulate_skill(args.skill_name, params, dry_run=args.dry_run)
    _print_json(result)
    return 0


def _handle_skill_reload(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.loader import discover_and_register
    from shopee_agent.skills.registry import default_registry
    discover_and_register()
    _print_json({"reloaded": True, "total": len(default_registry.list())})
    return 0


def _handle_skill_profile(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.registry import default_registry
    cls = default_registry.get(args.skill_name)
    if cls is None:
        _print_json({"error": "not found"})
        return 1
    _print_json({
        "name": getattr(cls, "name", ""),
        "cost": getattr(cls, "cost", 0),
        "priority": getattr(cls, "priority", 0),
        "preconditions": getattr(cls, "preconditions", {}),
        "effects": getattr(cls, "effects", {}),
        "dependencies": getattr(cls, "dependencies", []),
    })
    return 0


def _handle_skill_generate(args, client=None, cfg=None) -> int:
    import json as _j

    from shopee_agent.skills.generator import generate_skill
    result = generate_skill(
        description=args.description,
        preconditions=_j.loads(args.preconditions) if args.preconditions else {},
        effects=_j.loads(args.effects) if args.effects else {},
        risk=args.risk,
        cost=args.cost,
        priority=args.priority,
        schedule=args.schedule or None,
        event_types=args.event_types.split(",") if args.event_types else [],
    )
    _print_json(result)
    return 0


def _handle_skill_goap_explain(args, client=None, cfg=None) -> int:
    import json as _j

    from shopee_agent.goap_planner import GOAPPlanner
    from shopee_agent.skills.loader import discover_and_register
    from shopee_agent.skills.registry import default_registry
    discover_and_register()
    planner = GOAPPlanner()
    planner.load_skills(default_registry)
    current = _j.loads(args.current_state)
    goal = _j.loads(args.goal_state)
    plan = planner.plan(current, goal, max_depth=args.max_depth)
    _print_json(plan if plan else {"error": "no plan found"})
    return 0


def _handle_skill_rollback_learning(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.learning import rollback_learning
    result = rollback_learning(args.skill_name, steps=args.steps)
    _print_json({"rolled_back": result})
    return 0


def _handle_learning_stats(args, client=None, cfg=None) -> int:
    from shopee_agent.learning_db import LearningDB
    db = LearningDB()
    stats = db.get_stats(args.skill_name)
    _print_json(stats)
    return 0


# ── Scheduling ───────────────────────────────────────────────────────────────


def _handle_plan_schedule(args, client=None, cfg=None) -> int:
    import json as _j

    from shopee_agent.skills.scheduler import PlanScheduler
    scheduler = PlanScheduler()
    if args.action == "list":
        _print_json({"schedules": scheduler.list_schedules()})
    elif args.action == "add":
        time_str = args.schedule_time or "08:00"
        days = args.days.split(",") if args.days else ["mon", "wed", "fri"]
        scheduler.add_schedule(args.skill_name, time_str, days, _j.loads(args.params) if args.params else {})
        _print_json({"added": args.skill_name, "time": time_str, "days": days})
    elif args.action == "remove":
        scheduler.remove_schedule(args.skill_name)
        _print_json({"removed": args.skill_name})
    return 0


# ── Proxy / Fallback ─────────────────────────────────────────────────────────


def _handle_not_implemented(args, client=None, cfg=None) -> int:
    _print_json({"error": f"command '{args.command}' not yet extracted", "hint": "implement handler in all_handlers.py"})
    return 1


# ── Dispatch registry ────────────────────────────────────────────────────────


def _print_json(data):
    print(json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True))


def handle_competitors(args, client=None, cfg=None) -> int:
    from shopee_agent.shopee_search_scraper import (
        compare_product,
        generate_competitive_report,
        list_tracked,
        scrape_search,
        track_competitor,
    )
    if args.competitors_action == "search":
        results = scrape_search(args.keyword)
        _print_json({"keyword": args.keyword, "results": results, "total": len(results)})
    elif args.competitors_action == "track":
        result = track_competitor(args.item_id, name=args.name, price=args.price)
        _print_json(result)
    elif args.competitors_action == "list":
        tracked = list_tracked()
        _print_json({"tracked": tracked, "total": len(tracked)})
    elif args.competitors_action == "compare":
        comp_id = args.competitor_id
        if not comp_id:
            tracked = list_tracked()
            if tracked:
                comp_id = tracked[0]["item_id"]
            else:
                _print_json({"error": "No tracked competitors. Use 'track' first or specify --competitor-id"})
                return 1
        result = compare_product(args.item_id, comp_id)
        _print_json(result)
    elif args.competitors_action == "report":
        report = generate_competitive_report()
        _print_json(report)
    return 0


def handle_pricing(args, client=None, cfg=None) -> int:
    pricing = lazy_import("shopee_agent.pricing_automation")
    engine = pricing.DynamicPricingEngine(client=client)
    if args.pricing_action == "analyze":
        items = client.get_item_list(limit=200) if client else {"item_list": []}
        item_list = items.get("item_list", items.get("items", []))
        comp_cache = pricing._cached_competitor_prices()
        results = engine.analyze_all_items(item_list, comp_cache)
        _print_json({"results": results, "total": len(results)})
    elif args.pricing_action == "apply":
        items = client.get_item_list(limit=200) if client else {"item_list": []}
        item_list = items.get("item_list", items.get("items", []))
        comp_cache = pricing._cached_competitor_prices()
        summary = engine.apply_all_suggestions(items=item_list, competitor_data=comp_cache, dry_run=args.dry_run)
        _print_json(summary)
    return 0


def _handle_tenant(args, client=None, cfg=None) -> int:
    from shopee_agent.multi_tenant import TenantConfig, TenantManager
    manager = TenantManager()
    if args.tenant_action == "list":
        tenants = manager.list_tenants()
        _print_json({"tenants": tenants, "count": len(tenants)})
    elif args.tenant_action == "register":
        from datetime import datetime
        config = TenantConfig(
            store_id=args.store_id,
            shop_id=args.shop_id,
            access_token=args.access_token or "",
            reports_dir=manager.tenant_dir(args.store_id) / "reports",
            secrets_dir=manager.tenant_dir(args.store_id) / "secrets",
            db_dir=manager.tenant_dir(args.store_id) / "data",
            settings={},
            enabled=args.enabled,
            created_at=datetime.now(UTC).isoformat(),
        )
        ok = manager.register_tenant(config)
        _print_json({"registered": ok, "store_id": args.store_id})
    elif args.tenant_action == "remove":
        ok = manager.remove_tenant(args.store_id)
        _print_json({"removed": ok})
    elif args.tenant_action == "enable":
        ok = manager.enable_tenant(args.store_id)
        _print_json({"enabled": ok})
    elif args.tenant_action == "disable":
        ok = manager.disable_tenant(args.store_id)
        _print_json({"disabled": ok})
    return 0


# ── Refunds handler ─────────────────────────────────────────────────────────


def handle_refunds(args, client=None, cfg=None) -> int:
    from shopee_agent.refunds import RefundDecision, create_refund_manager

    manager = create_refund_manager()

    if args.refunds_action == "list":
        effective_access_token = args.access_token or (cfg and cfg.default_access_token)
        effective_shop_id = args.shop_id if args.shop_id is not None else (cfg and cfg.default_shop_id)

        if not effective_access_token:
            _print_json({"error": "Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)"})
            return 1
        if effective_shop_id is None:
            _print_json({"error": "Missing shop ID (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)"})
            return 1

        now = int(time.time())
        time_from = int((datetime.now(UTC) - timedelta(days=args.days)).timestamp())

        try:
            resp = client.get_return_list(
                access_token=effective_access_token,
                shop_id=effective_shop_id,
                time_from=time_from,
                time_to=now,
                return_status=args.status or "",
                page_size=50,
            )
            body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
            returns = body.get("return_list", [])

            print(f"Found {len(returns)} refunds:")
            for ret in returns:
                print(f"  {ret.get('return_sn')} | {ret.get('status')} | Order: {ret.get('order_sn')} | Amount: ${ret.get('refund_amount', 0):.2f}")

            return 0
        except Exception as exc:
            _print_json({"error": f"Failed to fetch refunds: {str(exc)}"})
            return 1

    elif args.refunds_action == "stats":
        stats = manager.get_refund_stats(days=args.days)
        _print_json({
            "total_refunds": stats.total_refunds,
            "pending_count": stats.pending_count,
            "approval_rate_pct": round(stats.approval_rate, 2),
            "avg_resolution_hours": round(stats.avg_resolution_time_hours, 2),
            "estimated_loss_usd": round(stats.estimated_loss, 2),
            "common_reasons": stats.common_reasons,
            "period_days": args.days,
        })
        return 0

    elif args.refunds_action == "approve":
        effective_access_token = args.access_token or (cfg and cfg.default_access_token)
        effective_shop_id = args.shop_id if args.shop_id is not None else (cfg and cfg.default_shop_id)

        if not effective_access_token:
            _print_json({"error": "Missing access token"})
            return 1
        if effective_shop_id is None:
            _print_json({"error": "Missing shop ID"})
            return 1

        if args.dry_run:
            print(f"DRY RUN: Would approve refund {args.return_sn}")
            return 0

        try:
            resp = client.confirm_return(
                access_token=effective_access_token,
                shop_id=effective_shop_id,
                return_sn=args.return_sn,
                status="MERCHANT_ACCEPTED",
            )
            print(f"Refund {args.return_sn} approved")
            _print_json(resp.data)
            return 0
        except Exception as exc:
            _print_json({"error": f"Failed to approve refund: {str(exc)}"})
            return 1

    elif args.refunds_action == "reject":
        effective_access_token = args.access_token or (cfg and cfg.default_access_token)
        effective_shop_id = args.shop_id if args.shop_id is not None else (cfg and cfg.default_shop_id)

        if not effective_access_token:
            _print_json({"error": "Missing access token"})
            return 1
        if effective_shop_id is None:
            _print_json({"error": "Missing shop ID"})
            return 1

        if args.dry_run:
            print(f"DRY RUN: Would reject refund {args.return_sn}")
            return 0

        try:
            resp = client.confirm_return(
                access_token=effective_access_token,
                shop_id=effective_shop_id,
                return_sn=args.return_sn,
                status="MERCHANT_REJECTED",
            )
            print(f"Refund {args.return_sn} rejected")
            _print_json(resp.data)
            return 0
        except Exception as exc:
            _print_json({"error": f"Failed to reject refund: {str(exc)}"})
            return 1

    elif args.refunds_action == "auto-evaluate":
        effective_access_token = args.access_token or (cfg and cfg.default_access_token)
        effective_shop_id = args.shop_id if args.shop_id is not None else (cfg and cfg.default_shop_id)

        if not effective_access_token:
            _print_json({"error": "Missing access token"})
            return 1
        if effective_shop_id is None:
            _print_json({"error": "Missing shop ID"})
            return 1

        print(f"Auto-evaluating refunds from last {args.days} days...")

        now = int(time.time())
        time_from = int((datetime.now(UTC) - timedelta(days=args.days)).timestamp())

        try:
            resp = client.get_return_list(
                access_token=effective_access_token,
                shop_id=effective_shop_id,
                time_from=time_from,
                time_to=now,
                return_status="PENDING",
                page_size=50,
            )
            body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
            pending_returns = body.get("return_list", [])

            recommendations = []
            for ret in pending_returns:
                decision = RefundDecision.MANUAL_REVIEW
                recommendations.append({
                    "return_sn": ret.get("return_sn"),
                    "order_sn": ret.get("order_sn"),
                    "amount": ret.get("refund_amount"),
                    "recommendation": decision.value,
                })

            if args.dry_run:
                print(f"DRY RUN: Would process {len(recommendations)} refunds:")
                _print_json(recommendations)
            else:
                print(f"Auto-evaluated {len(recommendations)} pending refunds:")
                _print_json(recommendations)

            return 0
        except Exception as exc:
            _print_json({"error": f"Failed to auto-evaluate refunds: {str(exc)}"})
            return 1

    else:
        print("Usage: laura refunds list|stats|approve|reject|auto-evaluate [options]")
        return 0


# ── Campaign handler ────────────────────────────────────────────────────────


def handle_campaign(args, client=None, cfg=None) -> int:
    campaign_manager = lazy_import("shopee_agent.campaign_manager")
    effective_access_token = args.access_token or (cfg and cfg.default_access_token)
    effective_shop_id = args.shop_id if args.shop_id is not None else (cfg and cfg.default_shop_id)
    mgr = campaign_manager.CampaignManager(client, effective_access_token, effective_shop_id)
    if args.campaign_action == "list":
        _print_json(mgr.list_active_campaigns())
    elif args.campaign_action == "bundle":
        result = mgr.create_bundle_deal(args.name, json.loads(args.items), args.discount,
            datetime.now(UTC), datetime.now(UTC) + timedelta(days=7))
        _print_json(result)
    elif args.campaign_action == "voucher":
        result = mgr.create_voucher(args.name, args.value, args.min_spend, args.quantity,
            datetime.now(UTC), datetime.now(UTC) + timedelta(days=7))
        _print_json(result)
    elif args.campaign_action == "auto":
        metrics = json.loads(args.metrics)
        _print_json(mgr.auto_campaign_from_metrics(metrics))
    return 0


# ── Workers handler ─────────────────────────────────────────────────────────


def handle_workers(args, client=None, cfg=None) -> int:
    workers_mgmt = lazy_import("shopee_agent.workers_management")
    mgr = workers_mgmt.WorkersManager()
    if args.workers_action == "list":
        _print_json(mgr.list_workers())
    elif args.workers_action == "status":
        _print_json(mgr.get_worker_status(args.worker_name))
    elif args.workers_action == "pause":
        _print_json({"paused": mgr.pause_worker(args.worker_name)})
    elif args.workers_action == "resume":
        _print_json({"resumed": mgr.resume_worker(args.worker_name)})
    elif args.workers_action == "stats":
        _print_json(mgr.get_queue_stats())
    return 0


# ── Cross-sell handler ──────────────────────────────────────────────────────


def handle_cross_sell(args, client=None, cfg=None) -> int:
    cross_selling = lazy_import("shopee_agent.cross_selling")
    engine = cross_selling.CrossSellingEngine(client=client)
    if args.xsell_action == "recommend":
        _print_json(engine.get_recommendations(args.product_id, args.top_n))
    elif args.xsell_action == "top-pairs":
        _print_json(engine.get_top_selling_pairs(args.top_n))
    elif args.xsell_action == "bundle":
        items = json.loads(args.items)
        _print_json(engine.get_bundle_recommendations(items))
    return 0


# ── Seller Center handler ───────────────────────────────────────────────────


def handle_sc(args, client=None, cfg=None) -> int:
    from shopee_agent.seller_center_full import SellerCenterAutomator
    automator = SellerCenterAutomator(client=client, headless=True)
    try:
        if args.sc_action == "products":
            _print_json(automator.list_products(page=args.page, page_size=args.page_size))
        elif args.sc_action == "product":
            _print_json(automator.get_product_detail(args.item_id))
        elif args.sc_action == "orders":
            _print_json(automator.list_orders(status=args.status, days=args.days))
        elif args.sc_action == "ship":
            _print_json(automator.ship_order(args.order_sn))
        elif args.sc_action == "pending":
            _print_json(automator.get_pending_shipments())
        elif args.sc_action == "balance":
            _print_json(automator.get_account_balance())
        elif args.sc_action == "campaigns":
            _print_json(automator.list_campaigns())
        elif args.sc_action == "perf":
            _print_json(automator.get_shop_performance())
        elif args.sc_action == "violations":
            _print_json(automator.get_listing_violations())
        elif args.sc_action == "bulk-price":
            _print_json(automator.bulk_update_prices(json.loads(args.items)))
        elif args.sc_action == "bulk-stock":
            _print_json(automator.bulk_update_stock(json.loads(args.items)))
        elif args.sc_action == "export":
            path = automator.export_products_to_csv(args.filepath)
            _print_json({"path": path, "status": "exported"})
    except Exception as exc:
        _print_json({"error": str(exc), "hint": "Verifique se o Chrome esta aberto com --remote-debugging-port=9222"})
    return 0


# ── Vision handler ──────────────────────────────────────────────────────────


def handle_vision(args, client=None, cfg=None) -> int:
    vision = lazy_import("shopee_agent.vision")
    if args.vision_action == "ocr":
        print(vision.ocr(args.image_path))
    elif args.vision_action == "describe" or args.vision_action == "descrever":
        print(vision.descrever(args.image_path))
    elif args.vision_action == "analyze" or args.vision_action == "analisar":
        product = getattr(args, 'product', '')
        print(vision.analisar_reclamacao(args.image_path, product))
    elif args.vision_action == "match":
        vision_engine = vision.LauraVision()
        result = vision_engine.match_product(args.image_path, args.product)
        _print_json(result)
    elif args.vision_action == "batch":
        vision_engine = vision.LauraVision()
        results = vision_engine.batch_process(args.directory, args.task)
        _print_json({"processed": len(results), "results": results[:10]})
    elif args.vision_action == "compare":
        vision_engine = vision.LauraVision()
        result = vision_engine.compare_images(args.img_a, args.img_b)
        _print_json(result)
    elif args.vision_action == "extract-table":
        vision_engine = vision.LauraVision()
        table = vision_engine.extract_table(args.image_path)
        _print_json({"rows": len(table), "data": table[:20]})
    return 0


# ── Chat handler ────────────────────────────────────────────────────────────


def handle_chat(args, client=None, cfg=None) -> int:
    chat_auto = lazy_import("shopee_agent.chat_auto")
    return chat_auto.main()


# ── Telegram handler ────────────────────────────────────────────────────────


def handle_telegram(args, client=None, cfg=None) -> int:
    telegram_bot = lazy_import("shopee_agent.telegram_bot")
    return telegram_bot.main()


# ── Report handler ──────────────────────────────────────────────────────────


def handle_report(args, client=None, cfg=None) -> int:
    reporting = lazy_import("shopee_agent.reporting")
    if args.report_action in ("daily", "weekly", "monthly"):
        engine = reporting.ReportingEngine(client=client)
        r = getattr(engine, f"generate_{args.report_action}_report")()
        _print_json(r)
    elif args.report_action == "export":
        fmt = getattr(args, 'format', 'excel')
        path = getattr(args, 'filepath', '')
        engine = reporting.ReportingEngine(client=client)
        history = engine.get_report_history(days=1)
        if history:
            r = engine.export_to_excel(history[-1], path) if fmt == 'excel' else engine.export_to_csv(history[-1], path)
            _print_json({"path": r})
        else:
            _print_json({"error": "Nenhum relatorio encontrado. Gere um primeiro."})
    elif args.report_action == "history":
        engine = reporting.ReportingEngine(client=client)
        _print_json(engine.get_report_history(days=30))
    elif args.report_action == "send":
        engine = reporting.ReportingEngine(client=client)
        rtype = getattr(args, 'type', 'daily')
        to = getattr(args, 'to', '')
        r = getattr(engine, f"generate_{rtype}_report")()
        sent = engine.send_email(r, [to])
        _print_json({"sent": sent, "type": rtype, "to": to})
    return 0


# ── Dashboard / Completion ────────────────────────────────────────────────


def _handle_completion(args, client=None, cfg=None) -> int:
    from shopee_agent.cli_completion import main as completion_main
    return completion_main()


def _handle_dashboard(args, client=None, cfg=None) -> int:
    from shopee_agent.dashboard import start as start_dashboard
    build_frontend = getattr(args, 'build_frontend', False)
    auto_build = not getattr(args, 'no_auto_build', False)
    start_dashboard(host=args.host, port=args.port, build_frontend=build_frontend, auto_build=auto_build)
    return 0


# ── Order commands ────────────────────────────────────────────────────────


def _handle_order_list(args, client=None, cfg=None) -> int:
    effective_access_token = args.access_token or cfg.default_access_token
    effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
    if not effective_access_token:
        _print_json({"error": "Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)"})
        return 1
    if effective_shop_id is None:
        _print_json({"error": "Missing shop id (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)"})
        return 1
    if args.page_size < 1 or args.page_size > 100:
        _print_json({"error": "--page-size deve estar entre 1 e 100"})
        return 1
    now_ts = int(datetime.now(UTC).timestamp())
    time_to = args.time_to if args.time_to is not None else now_ts
    time_from = args.time_from if args.time_from is not None else (time_to - 24 * 3600)
    if time_from < 0 or time_to < 0:
        _print_json({"error": "--time-from/--time-to devem ser epoch >= 0"})
        return 1
    if time_from > time_to:
        _print_json({"error": "--time-from nao pode ser maior que --time-to"})
        return 1
    resp = client.get_order_list(
        access_token=effective_access_token,
        shop_id=effective_shop_id,
        time_range_field=args.time_range_field,
        time_from=time_from,
        time_to=time_to,
        page_size=args.page_size,
        cursor=args.cursor,
        order_status=args.order_status,
    )
    _print_json(resp.data)
    return 0


def _handle_order_detail(args, client=None, cfg=None) -> int:
    effective_access_token = args.access_token or cfg.default_access_token
    effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
    if not effective_access_token:
        _print_json({"error": "Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)"})
        return 1
    if effective_shop_id is None:
        _print_json({"error": "Missing shop id (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)"})
        return 1
    resp = client.get_order_detail(
        access_token=effective_access_token,
        shop_id=effective_shop_id,
        order_sn=args.order_sn,
    )
    _print_json(resp.data)
    return 0


# ── Autonomous loop ───────────────────────────────────────────────────────


def _handle_autonomous_loop(args, client=None, cfg=None) -> int:
    effective_access_token = args.access_token or cfg.default_access_token
    effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
    from shopee_agent.autonomous_loop import AutonomousLoop
    al = AutonomousLoop(
        client=client,
        access_token=effective_access_token,
        shop_id=effective_shop_id,
        reports_dir=Path("reports"),
        telegram_token=args.telegram_token,
        telegram_chat_id=args.telegram_chat_id,
    )
    result = al.run_cycle()
    _print_json(result)
    return 0


# ── Logistics commands ────────────────────────────────────────────────────


def _handle_logistics_channel_list(args, client=None, cfg=None) -> int:
    effective_access_token = args.access_token or cfg.default_access_token
    effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
    if not effective_access_token:
        _print_json({"error": "Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)"})
        return 1
    if effective_shop_id is None:
        _print_json({"error": "Missing shop id (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)"})
        return 1
    resp = client.get_logistics_channel_list(
        access_token=effective_access_token,
        shop_id=effective_shop_id,
    )
    _print_json(resp.data)
    return 0


def _handle_logistics_tracking_number(args, client=None, cfg=None) -> int:
    effective_access_token = args.access_token or cfg.default_access_token
    effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
    if not effective_access_token:
        _print_json({"error": "Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)"})
        return 1
    if effective_shop_id is None:
        _print_json({"error": "Missing shop id (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)"})
        return 1
    resp = client.get_tracking_number(
        access_token=effective_access_token,
        shop_id=effective_shop_id,
        order_sn=args.order_sn,
        package_number=args.package_number,
    )
    _print_json(resp.data)
    return 0


def _handle_logistics_info(args, client=None, cfg=None) -> int:
    effective_access_token = args.access_token or cfg.default_access_token
    effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
    if not effective_access_token:
        _print_json({"error": "Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)"})
        return 1
    if effective_shop_id is None:
        _print_json({"error": "Missing shop id (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)"})
        return 1
    resp = client.get_logistics_info(
        access_token=effective_access_token,
        shop_id=effective_shop_id,
        order_sn=args.order_sn,
        package_number=args.package_number,
    )
    _print_json(resp.data)
    return 0


# ── Returns commands ──────────────────────────────────────────────────────


def _handle_returns_list(args, client=None, cfg=None) -> int:
    effective_access_token = args.access_token or cfg.default_access_token
    effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
    if not effective_access_token:
        _print_json({"error": "Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)"})
        return 1
    if effective_shop_id is None:
        _print_json({"error": "Missing shop id (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)"})
        return 1
    if args.page_no < 1:
        _print_json({"error": "--page-no deve ser >= 1"})
        return 1
    if args.page_size < 1 or args.page_size > 100:
        _print_json({"error": "--page-size deve estar entre 1 e 100"})
        return 1
    now_ts = int(datetime.now(UTC).timestamp())
    create_time_to = args.create_time_to if args.create_time_to is not None else now_ts
    create_time_from = args.create_time_from if args.create_time_from is not None else (create_time_to - 7 * 24 * 3600)
    if create_time_from < 0 or create_time_to < 0:
        _print_json({"error": "--create-time-from/--create-time-to devem ser epoch >= 0"})
        return 1
    if create_time_from > create_time_to:
        _print_json({"error": "--create-time-from nao pode ser maior que --create-time-to"})
        return 1
    if (create_time_to - create_time_from) > (15 * 24 * 3600):
        _print_json({"error": "janela de create_time deve ser no maximo 15 dias"})
        return 1
    resp = client.get_return_list(
        access_token=effective_access_token,
        shop_id=effective_shop_id,
        page_no=args.page_no,
        page_size=args.page_size,
        create_time_from=create_time_from,
        create_time_to=create_time_to,
    )
    _print_json(resp.data)
    return 0


def _handle_returns_detail(args, client=None, cfg=None) -> int:
    effective_access_token = args.access_token or cfg.default_access_token
    effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
    if not effective_access_token:
        _print_json({"error": "Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)"})
        return 1
    if effective_shop_id is None:
        _print_json({"error": "Missing shop id (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)"})
        return 1
    resp = client.get_return_detail(
        access_token=effective_access_token,
        shop_id=effective_shop_id,
        return_sn=args.return_sn,
    )
    _print_json(resp.data)
    return 0


# ── Payment / Discount / Voucher / Bundle / Add-on ────────────────────────


def _handle_payment_escrow_detail(args, client=None, cfg=None) -> int:
    effective_access_token = args.access_token or cfg.default_access_token
    effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
    if not effective_access_token:
        _print_json({"error": "Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)"})
        return 1
    if effective_shop_id is None:
        _print_json({"error": "Missing shop id (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)"})
        return 1
    resp = client.get_escrow_detail(
        access_token=effective_access_token,
        shop_id=effective_shop_id,
        order_sn=args.order_sn,
    )
    _print_json(resp.data)
    return 0


def _handle_discount_list(args, client=None, cfg=None) -> int:
    effective_access_token = args.access_token or cfg.default_access_token
    effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
    if not effective_access_token:
        _print_json({"error": "Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)"})
        return 1
    if effective_shop_id is None:
        _print_json({"error": "Missing shop id (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)"})
        return 1
    resp = client.get_discount_list(
        access_token=effective_access_token,
        shop_id=effective_shop_id,
        discount_status=args.discount_status,
    )
    _print_json(resp.data)
    return 0


def _handle_voucher_list(args, client=None, cfg=None) -> int:
    effective_access_token = args.access_token or cfg.default_access_token
    effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
    if not effective_access_token:
        _print_json({"error": "Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)"})
        return 1
    if effective_shop_id is None:
        _print_json({"error": "Missing shop id (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)"})
        return 1
    resp = client.get_voucher_list(
        access_token=effective_access_token,
        shop_id=effective_shop_id,
        status=args.status,
    )
    _print_json(resp.data)
    return 0


def _handle_bundle_deal_list(args, client=None, cfg=None) -> int:
    effective_access_token = args.access_token or cfg.default_access_token
    effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
    if not effective_access_token:
        _print_json({"error": "Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)"})
        return 1
    if effective_shop_id is None:
        _print_json({"error": "Missing shop id (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)"})
        return 1
    resp = client.get_bundle_deal_list(
        access_token=effective_access_token,
        shop_id=effective_shop_id,
    )
    _print_json(resp.data)
    return 0


def _handle_add_on_deal_list(args, client=None, cfg=None) -> int:
    effective_access_token = args.access_token or cfg.default_access_token
    effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
    if not effective_access_token:
        _print_json({"error": "Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)"})
        return 1
    if effective_shop_id is None:
        _print_json({"error": "Missing shop id (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)"})
        return 1
    resp = client.get_add_on_deal_list(
        access_token=effective_access_token,
        shop_id=effective_shop_id,
    )
    _print_json(resp.data)
    return 0


# ── Media / Video commands ────────────────────────────────────────────────


def _handle_media_video_init_upload(args, client=None, cfg=None) -> int:
    effective_access_token = args.access_token or cfg.default_access_token
    effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
    if not effective_access_token:
        _print_json({"error": "Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)"})
        return 1
    if effective_shop_id is None:
        _print_json({"error": "Missing shop id (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)"})
        return 1
    if args.file_size <= 0:
        _print_json({"error": "--file-size deve ser maior que 0"})
        return 1
    md5_hex = str(args.file_md5).strip().lower()
    if not re.fullmatch(r"[0-9a-fA-F]{32}", md5_hex):
        _print_json({"error": "--file-md5 deve ser hexadecimal com 32 caracteres"})
        return 1
    resp = client.init_video_upload(
        access_token=effective_access_token,
        shop_id=effective_shop_id,
        file_size=args.file_size,
        file_md5=md5_hex,
    )
    _print_json(resp.data)
    return 0


def _handle_media_video_upload_result(args, client=None, cfg=None) -> int:
    effective_access_token = args.access_token or cfg.default_access_token
    effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
    if not effective_access_token:
        _print_json({"error": "Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)"})
        return 1
    if effective_shop_id is None:
        _print_json({"error": "Missing shop id (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)"})
        return 1
    resp = client.get_video_upload_result(
        access_token=effective_access_token,
        shop_id=effective_shop_id,
        video_upload_id=args.video_upload_id,
    )
    _print_json(resp.data)
    return 0


def _handle_media_video_wait_completion(args, client=None, cfg=None) -> int:
    effective_access_token = args.access_token or cfg.default_access_token
    effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
    if not effective_access_token:
        _print_json({"error": "Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)"})
        return 1
    if effective_shop_id is None:
        _print_json({"error": "Missing shop id (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)"})
        return 1
    if args.max_wait_seconds <= 0:
        _print_json({"error": "--max-wait-seconds deve ser maior que 0"})
        return 1
    if args.poll_interval_seconds <= 0:
        _print_json({"error": "--poll-interval-seconds deve ser maior que 0"})
        return 1
    start_time = time.time()
    poll_count = 0
    last_status = None
    last_response = None
    while True:
        elapsed = time.time() - start_time
        if elapsed > args.max_wait_seconds:
            _print_json({"timeout": True, "elapsed_seconds": int(elapsed), "poll_count": poll_count, "last_status": last_status, "last_response": last_response})
            return 1
        poll_count += 1
        resp = client.get_video_upload_result(
            access_token=effective_access_token,
            shop_id=effective_shop_id,
            video_upload_id=args.video_upload_id,
        )
        if resp.data.get("error"):
            _print_json({"error": f"API error: {resp.data.get('error')}"})
            return 1
        response_obj = resp.data.get("response", {})
        status = response_obj.get("status", "UNKNOWN")
        last_status = status
        last_response = response_obj
        if status != "TRANSCODING":
            _print_json({"completed": True, "status": status, "elapsed_seconds": int(elapsed), "poll_count": poll_count, "video_info": response_obj.get("video_info")})
            return 0
        if poll_count > 1:
            print(f"Poll #{poll_count}: status={status}, elapsed={int(elapsed)}s", file=sys.stderr)
        if elapsed + args.poll_interval_seconds <= args.max_wait_seconds:
            time.sleep(args.poll_interval_seconds)


def _handle_media_video_upload_part(args, client=None, cfg=None) -> int:
    effective_access_token = args.access_token or cfg.default_access_token
    effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
    if not effective_access_token:
        _print_json({"error": "Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)"})
        return 1
    if effective_shop_id is None:
        _print_json({"error": "Missing shop id (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)"})
        return 1
    if args.part_seq < 0:
        _print_json({"error": "--part-seq deve ser maior ou igual a 0"})
        return 1
    part_path = Path(args.part_file)
    if not part_path.exists() or not part_path.is_file():
        _print_json({"error": "--part-file deve apontar para um arquivo existente"})
        return 1
    part_content = part_path.read_bytes()
    if len(part_content) == 0:
        _print_json({"error": "--part-file nao pode ser vazio"})
        return 1
    if args.content_md5:
        content_md5 = str(args.content_md5).strip().lower()
        if not re.fullmatch(r"[0-9a-fA-F]{32}", content_md5):
            _print_json({"error": "--content-md5 deve ser hexadecimal com 32 caracteres"})
            return 1
    else:
        content_md5 = hashlib.md5(part_content).hexdigest()
    resp = client.upload_video_part(
        access_token=effective_access_token,
        shop_id=effective_shop_id,
        video_upload_id=args.video_upload_id,
        part_seq=args.part_seq,
        content_md5=content_md5,
        file_name=part_path.name,
        part_content=part_content,
    )
    _print_json(resp.data)
    return 0


def _handle_media_video_complete_upload(args, client=None, cfg=None) -> int:
    effective_access_token = args.access_token or cfg.default_access_token
    effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
    if not effective_access_token:
        _print_json({"error": "Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)"})
        return 1
    if effective_shop_id is None:
        _print_json({"error": "Missing shop id (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)"})
        return 1
    raw_parts = [part.strip() for part in str(args.part_seq_list).split(",") if part.strip()]
    if not raw_parts:
        _print_json({"error": "--part-seq-list deve conter ao menos um numero"})
        return 1
    try:
        part_seq_list = [int(part) for part in raw_parts]
    except ValueError as exc:
        _print_json({"error": f"--part-seq-list invalido: {exc}"})
        return 1
    if any(part < 0 for part in part_seq_list):
        _print_json({"error": "--part-seq-list deve conter apenas inteiros maiores ou iguais a zero"})
        return 1
    resp = client.complete_video_upload(
        access_token=effective_access_token,
        shop_id=effective_shop_id,
        video_upload_id=args.video_upload_id,
        part_seq_list=part_seq_list,
    )
    _print_json(resp.data)
    return 0


# ── API commands ──────────────────────────────────────────────────────────


def _handle_api_call(args, client=None, cfg=None) -> int:
    effective_access_token = args.access_token or cfg.default_access_token
    effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
    payload = _load_json_file(args.payload_file, "payload")
    query_params = _load_json_file(args.query_file, "query params")
    if args.timeout_seconds is not None:
        if args.timeout_seconds <= 0:
            _print_json({"error": "--timeout-seconds deve ser maior que 0"})
            return 1
        client.timeout_seconds = args.timeout_seconds
    resp = client.call_endpoint(
        path=args.path,
        method=args.method,
        payload=payload,
        query_params=query_params,
        access_token=effective_access_token,
        shop_id=effective_shop_id,
    )
    if args.output_file:
        output_path = Path(args.output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(resp.data, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_json(resp.data)
    return 0


def _load_json_file(path_value, label):
    if path_value is None:
        return None
    p = Path(path_value)
    if not p.exists():
        _print_json({"error": f"{label} file not found: {path_value}"})
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        _print_json({"error": f"invalid JSON in {label} file"})
        return None


def _handle_api_endpoints(args, client=None, cfg=None) -> int:
    from shopee_agent.endpoints import list_endpoint_catalog
    catalog = list_endpoint_catalog()
    if args.json:
        _print_json({"count": len(catalog), "endpoints": catalog})
    else:
        print("Shopee API endpoints cataloged by Laura:")
        print("=" * 60)
        for item in catalog:
            print(f"{item['category']}: {item['name']} [{item['method']}] {item['path']}")
            print(f"  auth={item['auth']}")
            print(f"  {item['description']}")
    return 0


def _handle_api_families(args, client=None, cfg=None) -> int:
    from shopee_agent.endpoints import list_endpoint_families
    families = list_endpoint_families()
    if args.json:
        _print_json({"count": len(families), "families": families})
    else:
        print("Shopee API families recognized by Laura:")
        print("=" * 60)
        for family in families:
            features = ", ".join(family["features"])
            print(f"{family['name']}")
            print(f"  {family['description']}")
            print(f"  features={features}")
    return 0


def _handle_api_serve(args, client=None, cfg=None) -> int:
    if args.port < 1 or args.port > 65535:
        _print_json({"error": "--port deve estar entre 1 e 65535"})
        return 1
    from shopee_agent.cli import _serve_api as _sa
    _sa(host=args.host, port=args.port, reload=args.reload, log_level=args.log_level)
    return 0


# ── Health check ──────────────────────────────────────────────────────────


def _handle_health_check(args, client=None, cfg=None) -> int:
    from datetime import datetime
    if getattr(args, "local", False):
        try:
            import urllib.request
        except ImportError:
            import urllib.request as urllib_request
            urllib.request = urllib_request
        checks = {"status": "ok", "mode": "local", "timestamp": datetime.now(UTC).isoformat()}
        try:
            resp = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5)
            checks["ollama"] = "ok" if resp.getcode() == 200 else "error"
        except Exception as e:
            checks["ollama"] = f"unreachable ({e})"
            checks["status"] = "degraded"
        guard = Path("reports/laura_webhook_ready_guard.state")
        checks["webhook_guard"] = "present" if guard.exists() else "absent"
        _print_json(checks)
        return 0
    _cfg = cfg
    _client = client
    if _cfg is None or _client is None:
        from shopee_agent.client import ShopeeClient as _SC
        from shopee_agent.config import load_config as _lc
        _cfg = _lc()
        _client = _SC(_cfg)
    if not _cfg.default_refresh_token:
        _print_json({"error": "Missing SHOPEE_DEFAULT_REFRESH_TOKEN in environment"})
        return 1
    if _cfg.default_shop_id is None:
        _print_json({"error": "Missing SHOPEE_DEFAULT_SHOP_ID in environment"})
        return 1
    try:
        refresh_resp = _client.refresh_token(refresh_token=_cfg.default_refresh_token, shop_id=_cfg.default_shop_id)
        new_access_token = str(refresh_resp.data.get("access_token", "")).strip()
        new_refresh_token = str(refresh_resp.data.get("refresh_token", "")).strip()
        if not new_access_token or not new_refresh_token:
            new_access_token = _cfg.default_access_token
            new_refresh_token = _cfg.default_refresh_token
        else:
            _upsert_env_values(Path(args.env_file), {"SHOPEE_DEFAULT_ACCESS_TOKEN": new_access_token, "SHOPEE_DEFAULT_REFRESH_TOKEN": new_refresh_token})
        shop_info_resp = _client.get_shop_info(access_token=new_access_token, shop_id=_cfg.default_shop_id)
        _print_json({"refresh": refresh_resp.data, "shop_info": shop_info_resp.data, "saved_env": str(Path(args.env_file))})
        return 0
    except Exception as exc:
        _print_json({"error": str(exc)})
        return 1


def _upsert_env_values(env_path, updates):
    if not env_path.exists():
        _print_json({"error": f"Arquivo de ambiente nao encontrado: {env_path}"})
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    seen = set()
    new_lines = []
    for line in lines:
        replaced = False
        for key, value in updates.items():
            prefix = f"{key}="
            if line.startswith(prefix):
                new_lines.append(f"{key}={value}")
                seen.add(key)
                replaced = True
                break
        if not replaced:
            new_lines.append(line)
    for key, value in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={value}")
    final_text = "\n".join(new_lines) + "\n"
    backup_path = env_path.with_suffix(env_path.suffix + ".bak")
    temp_path = env_path.with_suffix(env_path.suffix + ".tmp")
    backup_path.write_text(env_path.read_text(encoding="utf-8"), encoding="utf-8")
    temp_path.write_text(final_text, encoding="utf-8")
    temp_path.replace(env_path)


# ── Webhook commands ──────────────────────────────────────────────────────


def _handle_webhook_start(args, client=None, cfg=None) -> int:
    if args.port < 1 or args.port > 65535:
        _print_json({"error": "--port deve estar entre 1 e 65535"})
        return 1
    callback_path = str(args.callback_path).strip() or "/webhook/shopee"
    if not callback_path.startswith("/"):
        callback_path = f"/{callback_path}"
    public_base_url = str(args.public_base_url).strip().rstrip("/")
    secret_key = str(args.secret_key).strip() or None
    from shopee_agent.logger import info as _webhook_info
    from shopee_agent.webhook_handlers import get_registry, initialize_handlers
    from shopee_agent.webhook_server import initialize_webhook_server
    server = initialize_webhook_server(host=args.host, port=args.port, secret_key=secret_key, allow_unverified_ack=args.allow_unverified_ack)
    initialize_handlers(server)
    server.start()
    recommended_callback_url = None
    if public_base_url:
        recommended_callback_url = f"{public_base_url}{callback_path}"
    _print_json({"status": "running", "bind": f"{args.host}:{args.port}", "callback_path": callback_path, "recommended_callback_url": recommended_callback_url, "signature_required": bool(secret_key), "allow_unverified_ack": bool(args.allow_unverified_ack), "handlers_registered": len(get_registry().handlers), "health_check_url": f"http://{args.host}:{args.port}/health"})
    if not secret_key:
        print("Webhook iniciado sem assinatura HMAC. Configure LAURA_WEBHOOK_SECRET para producao.", file=sys.stderr)
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        _webhook_info("Recebido SIGINT, encerrando webhook server")
        server.stop()
        return 0


def _handle_webhook_drain(args, client=None, cfg=None) -> int:
    if args.port < 1 or args.port > 65535:
        _print_json({"error": "--port deve estar entre 1 e 65535"})
        return 1
    import requests
    url = f"http://{args.host}:{args.port}/drain"
    try:
        resp = requests.post(url, timeout=10)
        data = {}
        try:
            data = resp.json()
        except Exception:
            data = {"status": "invalid_json", "raw": resp.text[:500]}
        _print_json({"status_code": resp.status_code, "url": url, "response": data})
        return 0 if resp.status_code == 200 else 1
    except Exception as exc:
        _print_json({"error": f"falha ao drenar fila de webhook em {url}: {exc}"})
        return 1


# ── Ollama commands ───────────────────────────────────────────────────────


def _handle_ollama_status(args, client=None, cfg=None) -> int:
    from shopee_agent.llm_local import get_ollama_status as _get_ollama_status
    report = _get_ollama_status(args.model)
    if args.json:
        _print_json(report)
    else:
        print("Laura Ollama status")
        print("=" * 60)
        print(f"Service running: {'OK' if report['service_running'] else 'FAIL'}")
        print(f"Requested model: {report['requested_model']}")
        print(f"Default model: {report['default_model']}")
        print(f"Model installed: {'OK' if report['model_installed'] else 'FAIL'}")
        print(f"Model loaded: {'OK' if report['model_loaded'] else 'FAIL'}")
        print(f"Installed models: {', '.join(report['installed_models']) or 'none'}")
        print(f"Loaded models: {', '.join(report['loaded_models']) or 'none'}")
        print()
        print("RAM usage:")
        print(report.get("ram_usage") or "n/a")
        print()
        print("Ollama process snapshot:")
        print(report.get("process_usage") or "n/a")
    return 0


def _handle_ollama_fix(args, client=None, cfg=None) -> int:
    import subprocess

    from shopee_agent.llm_local import check_ollama_running, start_ollama_if_needed
    from shopee_agent.llm_local import get_ollama_status as _gstatus
    model_name = args.model
    print("Ollama Maintenance - Starting diagnosis and repair")
    print("=" * 60)
    print("\nService check...")
    if not check_ollama_running():
        print("   Ollama not running. Starting...")
        if start_ollama_if_needed(model_name):
            print("   Ollama service started")
        else:
            print("   Failed to start Ollama service")
            print("   Install: https://ollama.ai/install.sh")
            return 1
    else:
        print("   Ollama service running")
    time.sleep(2)
    print(f"\nModel availability ({model_name})...")
    status = _gstatus(model_name)
    if status.get("model_installed") and not args.force_pull:
        print(f"   Model {model_name} already installed")
    else:
        print(f"   Pulling model {model_name}... (this may take a moment)")
        rc = 0
        stderr = ""
        try:
            proc = subprocess.run(["ollama", "pull", model_name], capture_output=True, text=True, timeout=300, check=False)
            rc = proc.returncode
            stderr = proc.stderr
        except Exception as exc:
            stderr = str(exc)
        if rc == 0:
            print(f"   Model {model_name} pulled successfully")
        else:
            print(f"   Failed to pull model: {stderr}")
            return 1
    time.sleep(1)
    print("\nLoading model into RAM...")
    try:
        proc = subprocess.run(["ollama", "run", model_name, "exit"], capture_output=True, text=True, timeout=120, check=False)
        if proc.returncode == 0:
            print(f"   Model {model_name} loaded into RAM")
        else:
            print(f"   Model load may be in progress: {proc.stderr[:100]}")
    except Exception as exc:
        print(f"   Load attempt: {str(exc)[:100]}")
    time.sleep(1)
    print("\nFinal status...")
    status = _gstatus(model_name)
    print("   Service: {}".format('Running' if status['service_running'] else 'Not running'))
    print("   Model installed: {}".format('Yes' if status['model_installed'] else 'No'))
    print("   Model loaded: {}".format('Yes' if status['model_loaded'] else 'Loading...'))
    print("   Installed models: {}".format(', '.join(status['installed_models']) or 'none'))
    print("\n" + "=" * 60)
    if status['service_running'] and status['model_installed']:
        if status['model_loaded']:
            print("Ollama is fully ready!")
            return 0
        else:
            print("Model is installing/loading. Try again in a moment.")
            return 0
    else:
        print("Ollama repair failed. Check logs and try manual: ollama serve")
        return 1


# ── LLM commands ──────────────────────────────────────────────────────────


def _handle_llm_prompts(args, client=None, cfg=None) -> int:
    from shopee_agent.prompts import list_available_prompts
    prompts = list_available_prompts()
    print("System Prompts Disponiveis:")
    print("=" * 60)
    for name, description in prompts.items():
        print(f"  {name:30s} - {description}")
    return 0


def _handle_llm_analyze(args, client=None, cfg=None) -> int:
    metrics_file = Path(args.metrics_file)
    if not metrics_file.exists():
        _print_json({"error": f"Arquivo de metricas nao encontrado: {metrics_file}"})
        return 1
    try:
        with open(metrics_file) as f:
            metrics = json.load(f)
    except json.JSONDecodeError:
        _print_json({"error": f"JSON invalido em {metrics_file}"})
        return 1
    try:
        from shopee_agent.llm_local import create_analyzer
        analyzer = create_analyzer(model=args.model)
        if args.timeout_seconds is not None:
            if args.timeout_seconds <= 0:
                _print_json({"error": "--timeout-seconds deve ser maior que 0"})
                return 1
            analyzer.request_timeout_seconds = args.timeout_seconds
        if args.prompt_type == "profitability_analyzer":
            result = analyzer.analyze_profitability(metrics=metrics, prompt_type=args.prompt_type, max_tokens=256)
        else:
            result = analyzer.analyze(metrics=metrics, prompt_type=args.prompt_type, max_tokens=256)
    except ValueError as e:
        _print_json({"error": f"Erro na analise: {e}"})
        return 1
    except Exception as e:
        _print_json({"error": f"Erro inesperado: {e}"})
        return 1
    result_dict = analyzer.to_dict(result)
    output_file = Path(args.output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(output_file, 'w') as f:
            json.dump(result_dict, f, indent=2, ensure_ascii=False)
        history_file = output_file.parent / "laura_profitability_llm_history.jsonl"
        with open(history_file, 'a') as f:
            f.write(json.dumps(result_dict, ensure_ascii=False) + '\n')
    except Exception as e:
        _print_json({"error": f"Erro ao salvar resultado: {e}"})
        return 1
    print("\n" + "=" * 70)
    print("RESULTADO DA ANALISE LLM (LOCAL)")
    print("=" * 70)
    print(f"Modelo: {result_dict.get('model', analyzer.model)}")
    print(f"Tempo de inferencia: {result_dict.get('inference_time_ms', 0)}ms")
    print(f"Decisao: {result_dict.get('decision', result_dict.get('action', ''))}")
    print(f"Acao: {result_dict.get('action', '')}")
    print(f"Prioridade: {result_dict.get('priority', '')}")
    print(f"Modo: {result_dict.get('mode', '')}")
    print(f"Confianca: {float(result_dict.get('confidence', 0.0) or 0.0):.1%}")
    print()
    print(f"Reasoning:\n{result_dict.get('reasoning', '')}")
    print()
    print(f"Proximos Passos:\n{result_dict.get('next_steps', result_dict.get('top_action', ''))}")
    print()
    print(f"Resultado salvo em: {output_file}")
    print("=" * 70)
    return 0


# ── Analytics / Charting (not yet extracted) ──────────────────────────────


def _handle_analytics_trends_inline(args, client=None, cfg=None) -> int:
    from shopee_agent.analytics_trending import AdvancedAnalytics
    analytics = AdvancedAnalytics()
    period = int(args.period)
    report = analytics.get_historical_metrics(period)
    if args.format == "json" or args.output:
        output_file = args.output or f"analytics_{period}d.json"
        Path(output_file).write_text(json.dumps(report, indent=2))
        print(f"Relatorio de tendencias salvo em: {output_file}")
    else:
        print(f"\n{'='*70}")
        print(f"ANALISE DE TENDENCIAS - {period} DIAS")
        print('=' * 70)
        print("ATUALIZACAO EM TEMPO REAL")
        print('=' * 70)
        print(f"Graficos: {', '.join(args.chart_types)}")
        print(f"Intervalo: {args.interval}s")
        print("Status: Ativo")
        print('=' * 70)
    return 0


def _handle_anomaly_detect(args, client=None, cfg=None) -> int:
    from shopee_agent.analytics_trending import AdvancedAnalytics
    analytics = AdvancedAnalytics()
    anomalies = analytics.detect_anomalies(args.threshold)
    if args.output:
        Path(args.output).write_text(json.dumps(anomalies, indent=2))
        print(f"Anomalias salvas em: {args.output}")
    else:
        print(f"\n{'='*70}")
        print(f"DETECCAO DE ANOMALIAS (threshold={args.threshold}s)")
        print('=' * 70)
        if anomalies:
            for anom in anomalies:
                print(f"\n{anom['type'].upper()}")
                print(f"   Timestamp: {anom['timestamp']}")
                print(f"   Valor: {anom['value']} | Limiar: {anom['threshold']:.1f}")
                print(f"   Severidade: {anom['severity']}")
        else:
            print("Nenhuma anomalia detectada no periodo")
        print(f"\n{'='*70}\n")
    return 0


def _handle_predict_refunds(args, client=None, cfg=None) -> int:
    from shopee_agent.analytics_trending import AdvancedAnalytics
    analytics = AdvancedAnalytics()
    prediction = analytics.predict_refund_rate(args.days)
    if args.output:
        Path(args.output).write_text(json.dumps(prediction, indent=2))
        print(f"Previsao salva em: {args.output}")
    else:
        print(f"\n{'='*70}")
        print(f"PREVISAO DE TAXA DE DEVOLUCOES ({args.days} DIAS)")
        print('=' * 70)
        if prediction.get('status') == 'no_data':
            print("Nenhum dado de devolucoes disponivel")
        elif prediction.get('status') == 'insufficient_history':
            print(f"Historico insuficiente ({prediction['days_available']} dias)")
        else:
            print(f"Media Historica: {prediction['historical_avg']:.2f}")
            print(f"Valor Previsto: {prediction['predicted_value']:.2f}")
            print(f"Confianca: {prediction['confidence']*100:.0f}%")
            print(f"{prediction['recommendation']}")
        print(f"\n{'='*70}\n")
    return 0


def _handle_charts_inline(args, client=None, cfg=None) -> int:
    from shopee_agent.charting_visualization import ChartingVisualization
    charts = ChartingVisualization()
    chart_html = None
    if args.type == "alerts":
        chart_html = charts.generate_alerts_chart(args.days)
        title = f"Grafico de Alertas ({args.days} dias)"
    elif args.type == "refunds":
        chart_html = charts.generate_refunds_chart(args.days)
        title = f"Grafico de Devolucoes ({args.days} dias)"
    elif args.type == "health":
        chart_html = charts.generate_health_gauge()
        title = "Medidor de Saude da Loja"
    elif args.type == "distribution":
        chart_html = charts.generate_distribution_chart("pie")
        title = "Distribuicao de Alertas"
    elif args.type == "comparison":
        chart_html = charts.generate_comparison_chart("alerts", "refunds")
        title = "Comparacao: Alertas vs Devolucoes"
    if chart_html:
        output_file = args.output or f"chart_{args.type}.html"
        Path(output_file).write_text(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js"></script>
</head>
<body>
    <h1>{title}</h1>
    {chart_html}
</body>
</html>""")
        print(f"Grafico {args.type} gerado: {output_file}")
    return 0


def _handle_chart_dashboard_inline(args, client=None, cfg=None) -> int:
    from shopee_agent.charting_visualization import ChartingVisualization
    charts = ChartingVisualization()
    html = charts.generate_dashboard_html()
    output_file = args.output
    Path(output_file).write_text(html)
    print(f"Dashboard visual criado: {output_file}")
    print(f"Abrir no navegador: file://{Path(output_file).absolute()}")
    print("Auto-refresh a cada 60 segundos")
    return 0


def _handle_performance_report(args, client=None, cfg=None) -> int:
    from shopee_agent.charting_visualization import ChartingVisualization
    charts = ChartingVisualization()
    report = charts.generate_performance_report(args.days)
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2))
        print(f"Relatorio de performance salvo: {args.output}")
    else:
        _print_json(report)
    return 0


# ── Reporting commands ────────────────────────────────────────────────────


def _handle_export_report(args, client=None, cfg=None) -> int:
    from shopee_agent.realtime_export import ScheduledReportManager
    manager = ScheduledReportManager()
    results = manager.generate_report(args.type, args.formats, args.output_dir)
    print(f"\n{'='*70}")
    print(f"EXPORTACAO DE RELATORIO - {args.type.upper()}")
    print('=' * 70)
    if results:
        for format_type, file_path in results.items():
            print(f"{format_type.upper()}: {file_path}")
    else:
        print("Erro ao exportar relatorio")
    print(f"{'='*70}\n")
    return 0 if results else 1


def _handle_schedule_report(args, client=None, cfg=None) -> int:
    from shopee_agent.realtime_export import ScheduledReportManager
    manager = ScheduledReportManager()
    report_id = args.report_id or f"report_{args.type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    config = {"type": args.type, "frequency": args.frequency, "formats": args.formats, "recipients": args.recipients or [], "created_at": datetime.now().isoformat()}
    success = manager.register_scheduled_report(report_id, config)
    print('=' * 70)
    print("AGENDAMENTO DE RELATORIO")
    print('=' * 70)
    if success:
        print("Relatorio agendado com sucesso!")
        print(f"ID: {report_id}")
        print(f"Tipo: {args.type}")
        print(f"Frequencia: {args.frequency}")
        print(f"Formatos: {', '.join(args.formats)}")
        if args.recipients:
            print(f"Destinatarios: {', '.join(args.recipients)}")
    else:
        print("Erro ao agendar relatorio")
    print('=' * 70)
    return 0 if success else 1


def _handle_realtime_config(args, client=None, cfg=None) -> int:
    from shopee_agent.realtime_export import RealtimeUpdateEngine
    RealtimeUpdateEngine()
    config = {"chart_types": args.chart_types, "update_interval_seconds": args.interval, "enabled": True, "created_at": datetime.now().isoformat()}
    if args.output:
        Path(args.output).write_text(json.dumps(config, indent=2))
        print(f"Configuracao salva em: {args.output}")
    else:
        _print_json(config)
    print("\n" + '=' * 70)
    print("ATUALIZACAO EM TEMPO REAL")
    print('=' * 70)
    print(f"Graficos: {', '.join(args.chart_types)}")
    print(f"Intervalo: {args.interval}s")
    print("Status: Ativo")
    print('=' * 70)
    return 0


# ── Activity / Dashboard-CLI / Doctor ─────────────────────────────────────


def _handle_activity(args, client=None, cfg=None) -> int:
    from shopee_agent.cli import _activity_report as _ar
    from shopee_agent.cli import _print_activity_report as _par
    report = _ar(limit=args.limit)
    if args.json:
        _print_json(report)
    else:
        _par(report)
    return 0


def _handle_dashboard_cli(args, client=None, cfg=None) -> int:
    from shopee_agent.monitoring_dashboard import MonitoringDashboard
    dashboard = MonitoringDashboard()
    if args.format == "html":
        html_content = dashboard.get_dashboard_html()
        output_file = args.output or "dashboard.html"
        Path(output_file).write_text(html_content)
        print(f"Dashboard HTML criado: {output_file}")
        print(f"Abrir no navegador: file://{Path(output_file).absolute()}")
    else:
        metrics = dashboard.get_store_metrics()
        if args.output:
            dashboard.export_metrics_json(args.output)
            print(f"Metricas JSON exportadas: {args.output}")
        else:
            _print_json(metrics)
    return 0


def _handle_doctor(args, client=None, cfg=None) -> int:
    from shopee_agent import _CLI_START
    from shopee_agent.cli import _doctor_report as _dr
    from shopee_agent.cli import _print_doctor_text as _pdt
    if getattr(args, "startup_time", False):
        _print_json({"startup_time_s": round(time.perf_counter() - _CLI_START, 3)})
        return 0
    report = _dr(env_file=args.env_file)
    if args.json:
        _print_json(report)
    else:
        _pdt(report)
    return 0 if report["overall_ok"] else 1


# ── Decision Engine commands ──────────────────────────────────────────────


def _handle_decision_status(args, client=None, cfg=None) -> int:
    from click.testing import CliRunner

    from shopee_agent.decision_cli import status as decision_status_cmd
    runner = CliRunner()
    result = runner.invoke(decision_status_cmd, ["--store-id", args.store_id, "--priority", args.priority])
    print(result.output)
    return result.exit_code


def _handle_decision_history(args, client=None, cfg=None) -> int:
    from click.testing import CliRunner

    from shopee_agent.decision_cli import history as decision_history_cmd
    runner = CliRunner()
    result = runner.invoke(decision_history_cmd, ["--store-id", args.store_id, "--limit", str(args.limit), "--type", args.type])
    print(result.output)
    return result.exit_code


def _handle_decision_detail(args, client=None, cfg=None) -> int:
    from click.testing import CliRunner

    from shopee_agent.decision_cli import detail as decision_detail_cmd
    runner = CliRunner()
    result = runner.invoke(decision_detail_cmd, [args.decision_id, "--store-id", args.store_id])
    print(result.output)
    return result.exit_code


def _handle_decision_cycle(args, client=None, cfg=None) -> int:
    from click.testing import CliRunner

    from shopee_agent.decision_cli import cycle as decision_cycle_cmd
    runner = CliRunner()
    result = runner.invoke(decision_cycle_cmd, ["--store-id", args.store_id])
    print(result.output)
    return result.exit_code


def _handle_decision_metrics(args, client=None, cfg=None) -> int:
    from click.testing import CliRunner

    from shopee_agent.decision_cli import metrics as decision_metrics_cmd
    runner = CliRunner()
    result = runner.invoke(decision_metrics_cmd, ["--store-id", args.store_id, "--days", str(args.days)])
    print(result.output)
    return result.exit_code


def _handle_decision_outcomes(args, client=None, cfg=None) -> int:
    from click.testing import CliRunner

    from shopee_agent.decision_cli import outcomes as decision_outcomes_cmd
    runner = CliRunner()
    result = runner.invoke(decision_outcomes_cmd, ["--store-id", args.store_id, "--days", str(getattr(args, "days", 7))])
    print(result.output)
    return result.exit_code


def _handle_decision_learn(args, client=None, cfg=None) -> int:
    from click.testing import CliRunner

    from shopee_agent.decision_cli import learn as decision_learn_cmd
    runner = CliRunner()
    result = runner.invoke(decision_learn_cmd, ["--store-id", args.store_id])
    print(result.output)
    return result.exit_code


def _handle_decision_effectiveness(args, client=None, cfg=None) -> int:
    from click.testing import CliRunner

    from shopee_agent.decision_cli import effectiveness as decision_effectiveness_cmd
    runner = CliRunner()
    argv = ["--store-id", args.store_id]
    if getattr(args, "rule", None):
        argv.extend(["--rule", args.rule])
    result = runner.invoke(decision_effectiveness_cmd, argv)
    print(result.output)
    return result.exit_code


def _handle_decision_similar(args, client=None, cfg=None) -> int:
    from click.testing import CliRunner

    from shopee_agent.decision_cli import similar as decision_similar_cmd
    runner = CliRunner()
    result = runner.invoke(decision_similar_cmd, [args.decision_id, "--store-id", args.store_id, "--top-k", str(getattr(args, "top_k", 5))])
    print(result.output)
    return result.exit_code


def _handle_decision_reindex_backend(args, client=None, cfg=None) -> int:
    from click.testing import CliRunner

    from shopee_agent.decision_cli import reindex_backend as decision_reindex_backend_cmd
    runner = CliRunner()
    result = runner.invoke(decision_reindex_backend_cmd, ["--store-id", args.store_id])
    print(result.output)
    return result.exit_code


def _handle_metrics_dashboard(args, client=None, cfg=None) -> int:
    from click.testing import CliRunner

    from shopee_agent.decision_cli import cmd_dashboard
    runner = CliRunner()
    argv = ["--live"] if getattr(args, "live", False) else []
    result = runner.invoke(cmd_dashboard, argv)
    print(result.output)
    return result.exit_code


# ── Agent orchestration ───────────────────────────────────────────────────


def _handle_agent_orchestration(args, client=None, cfg=None) -> int:
    import json as _json

    from shopee_agent.agent_orchestrator import AgentOrchestrator
    from shopee_agent.decision_engine import default_economic_context
    orchestrator = AgentOrchestrator()
    if args.agent_action == "list":
        agents = [{"name": name, "weight": getattr(a, "weight", 1.0), "objectives": getattr(a, "objectives", [])} for name, a in orchestrator.agents.items()]
        _print_json({"agents": agents, "count": len(agents)})
    elif args.agent_action == "status":
        ctx = default_economic_context()
        plan = orchestrator.coordinate_cycle_sync(ctx)
        _print_json({"plan_id": plan.plan_id, "approved": len(plan.approved_actions), "rejected": len(plan.rejected_actions), "conflicts": len(plan.conflicts), "score": plan.consensus_score})
    elif args.agent_action == "negotiate":
        ctx_kwargs = _json.loads(getattr(args, "context", "{}")) if hasattr(args, "context") and args.context else {}
        ctx = default_economic_context(**ctx_kwargs)
        plan = orchestrator.coordinate_cycle_sync(ctx)
        _print_json(plan.to_dict())
    return 0


# ── Flash sale recommend ──────────────────────────────────────────────────


def _handle_flash_sale_recommend(args, client=None, cfg=None) -> int:
    effective_access_token = args.access_token or cfg.default_access_token
    effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
    if not effective_access_token:
        _print_json({"error": "Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)"})
        return 1
    if effective_shop_id is None:
        _print_json({"error": "Missing shop id (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)"})
        return 1
    from shopee_agent.flash_sale_recommender import FlashSaleRecommender
    recommender = FlashSaleRecommender(client=client, access_token=effective_access_token, shop_id=effective_shop_id, reports_dir=Path("reports"), min_stock=args.min_stock, discount_pct=args.discount_pct)
    recommendation = recommender.generate_recommendations()
    summary = recommender.summarize(recommendation)
    payload = {"summary": summary, "recommendation": {"shop_id": recommendation.shop_id, "generated_at": recommendation.generated_at, "scheduled_start": recommendation.scheduled_start, "scheduled_end": recommendation.scheduled_end, "status": recommendation.status, "candidates": [{"item_id": candidate.item_id, "item_name": candidate.item_name, "stock": candidate.stock, "sales_7d": candidate.sales_7d, "discount_pct": candidate.discount_pct, "reason": candidate.reason} for candidate in recommendation.candidates]}}
    if args.output:
        Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Recomendacao de flash sale salva: {args.output}")
    else:
        _print_json(payload)
    if args.create:
        result = recommender.create_flash_sale(recommendation)
        print("\n" + "=" * 70)
        print("FLASH SALE AUTO-CREATE")
        print("=" * 70)
        print(f"Status: {result['status']}")
        print(f"Candidates: {len(result['candidates'])}")
        if result.get("payload"):
            print(f"Name: {result['payload']['flash_sale_name']}")
        if args.output:
            print("Saved flash sale result to: reports/laura_flash_sale_result_latest.json")
        print("=" * 70)
    return 0


# ── Competitive intel / Branding / Economic brain ─────────────────────────


def _handle_competitive_intel_summary(args, client=None, cfg=None) -> int:
    from shopee_agent.competitive_intelligence import CompetitiveIntelligence
    intelligence = CompetitiveIntelligence(path=args.offers_file)
    our_prices = {}
    our_prices_path = Path(args.our_prices_file)
    if our_prices_path.exists():
        try:
            payload = json.loads(our_prices_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                for item_id, value in payload.items():
                    try:
                        our_prices[str(item_id)] = float(value)
                    except Exception:
                        continue
        except Exception:
            our_prices = {}
    snapshot = intelligence.snapshot(our_prices=our_prices)
    _print_json(snapshot.to_dict())
    return 0


def _handle_branding_growth_summary(args, client=None, cfg=None) -> int:
    from shopee_agent.branding_growth import BrandingGrowthAnalyzer
    analyzer = BrandingGrowthAnalyzer(catalog_path=args.catalog_file)
    snapshot = analyzer.snapshot()
    _print_json(snapshot.to_dict())
    return 0


def _handle_economic_brain_summary(args, client=None, cfg=None) -> int:
    from shopee_agent.economic_brain import EconomicBrain
    brain = EconomicBrain(latest_path=args.latest_file, history_path=args.history_file)
    snapshot = brain.snapshot()
    _print_json(snapshot)
    return 0


# ── Start / Daemon / Shell ────────────────────────────────────────────────


def _handle_start(args, client=None, cfg=None) -> int:
    from shopee_agent.decision_integration import DecisionExecutor
    from shopee_agent.goap_planner import GOAPPlanner
    from shopee_agent.laura_daemon import LauraDaemon
    from shopee_agent.skills.loader import discover_and_register
    discover_and_register()
    GOAPPlanner()
    daemon = LauraDaemon()
    DecisionExecutor(store_id=cfg.default_shop_id or "", client=client, engine=None)
    logger = __import__("shopee_agent.logger", fromlist=["info"]).info
    logger("Laura iniciada com skills e GOAP planner")
    daemon.run_forever()
    return 0


def _handle_daemon(args, client=None, cfg=None) -> int:
    from shopee_agent.laura_daemon import LauraDaemon
    daemon = LauraDaemon()
    daemon.run_forever()
    return 0


def _handle_shell(args, client=None, cfg=None) -> int:
    if args.command:
        from tools.laura_shell import _execute
        _execute(args.command)
    else:
        from tools.laura_shell import main as shell_main
        shell_main()
    return 0


# ── Skill commands (not yet extracted) ────────────────────────────────────


def _handle_skill_run(args, client=None, cfg=None) -> int:
    import asyncio as _asyncio
    import json as _json

    from shopee_agent.skills.registry import default_registry, invoke
    skill_cls = default_registry.get(args.name)
    if skill_cls is None:
        print(f"Skill '{args.name}' nao encontrada. Skills disponiveis: {list(default_registry._skills.keys())}")
        return 1
    params = _json.loads(args.params) if isinstance(args.params, str) else {}
    skill_instance = skill_cls()
    result = _asyncio.run(invoke(skill_instance, **params))
    _print_json({"skill": args.name, "params": params, "result": result})
    return 0


def _handle_skill_goap_plan(args, client=None, cfg=None) -> int:
    import json as _json

    from shopee_agent.skills.loader import discover_and_register
    from shopee_agent.skills.orchestrator import SkillOrchestrator
    discover_and_register()
    current = _json.loads(args.current_state)
    goal = _json.loads(args.goal_state)
    orch = SkillOrchestrator()
    skills = orch.determine_skills(current, goal, max_depth=args.max_depth)
    if skills:
        results = orch.execute_plan(skills, context=current)
        _print_json({"plan": skills, "results": results, "status": "executed"})
    else:
        _print_json({"plan": [], "status": "no_plan_found"})
    return 0


def _handle_skill_test(args, client=None, cfg=None) -> int:
    import json as _json

    from shopee_agent.skills.loader import discover_and_register
    from shopee_agent.skills.registry import default_registry
    from shopee_agent.skills.sandbox import run_skill_sandbox
    discover_and_register()
    params = _json.loads(args.params)
    expected_effects = _json.loads(args.assert_effects)
    skill = default_registry.get_or_create(args.name)
    if skill is None:
        print(f"Skill '{args.name}' nao encontrada")
        return 1
    import asyncio as _asyncio
    result = _asyncio.run(run_skill_sandbox(skill_name=args.name, run_fn=skill.run, dry_run=args.dry_run, **(params)))
    output = {"skill": args.name, "result": result}
    if expected_effects and result.get("ok"):
        actual = skill.effects if hasattr(skill, "effects") else {}
        mismatches = {k: {"expected": v, "actual": actual.get(k)} for k, v in expected_effects.items() if actual.get(k) != v}
        output["effects_match"] = len(mismatches) == 0
        output["effect_mismatches"] = mismatches
    _print_json(output)
    return 0


def _handle_goal_synthesize(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.goal_synthesizer import describe_goal, synthesize_goal
    goal = synthesize_goal(margin_pct=args.margin_pct, low_margin_count=args.low_margin, low_stock_count=args.low_stock, refund_rate_pct=args.refund_pct)
    _print_json({"goal": goal, "description": describe_goal(goal)})
    return 0


def _handle_goal_nl(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.goal_nl import synthesize_from_text, synthesize_with_llm
    if args.llm:
        from shopee_agent.llm_local import create_analyzer
        llm = create_analyzer()
        goal = synthesize_with_llm(args.text, llm_func=lambda p: llm.client.chat(p))
    else:
        goal = synthesize_from_text(args.text)
    _print_json({"input": args.text, "goal": goal})
    return 0


def _handle_skill_approve(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.approval import approve
    ok = approve(args.request_id)
    print(f"Approved: {ok}")
    return 0 if ok else 1


def _handle_skill_reject(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.approval import reject
    ok = reject(args.request_id)
    print(f"Rejected: {ok}")
    return 0 if ok else 1


def _handle_skill_approval_list(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.approval import list_all, list_pending
    entries = list_all() if getattr(args, "all", False) else list_pending()
    _print_json({"requests": entries, "count": len(entries)})
    return 0


def _handle_store_list(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.store_registry import get_store_registry
    reg = get_store_registry()
    _print_json({"stores": reg.list_store_ids(), "summaries": reg.summaries()})
    return 0


def _handle_store_init(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.loader import discover_and_register
    from shopee_agent.skills.store_registry import get_store_registry
    reg = get_store_registry()
    ctx = reg.get_or_create(args.store_id)
    discover_and_register(registry=ctx.registry)
    ctx.planner.load_skills(ctx.registry)
    _print_json({"store_id": args.store_id, "status": "initialized", "skills": ctx.registry.list()})
    return 0


def _handle_store_summary(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.store_registry import get_store_registry
    reg = get_store_registry()
    ctx = reg.get(args.store_id)
    if ctx is None:
        print(f"Store '{args.store_id}' nao encontrada. Use store-init primeiro.")
        return 1
    _print_json(ctx.summary())
    return 0


def _handle_benchmark(args, client=None, cfg=None) -> int:
    import time as _btime

    from shopee_agent.goap_planner import GOAPAction, GOAPPlanner
    from shopee_agent.skills.loader import discover_and_register
    from shopee_agent.skills.orchestrator import SkillOrchestrator
    discover_and_register()
    iterations = max(1, args.iterations)
    target_skills = [s.strip() for s in args.skills.split(",") if s.strip()] if args.skills else []
    planner = GOAPPlanner()
    planner.register_action(GOAPAction("a", cost=1.0, effects={"x": True}))
    planner.register_action(GOAPAction("b", cost=2.0, preconditions={"x": True}, effects={"y": True}))
    planner.register_action(GOAPAction("c", cost=1.5, preconditions={"y": True}, effects={"z": True}))
    plan_times = []
    for _ in range(iterations):
        t0 = _btime.perf_counter()
        planner.plan({"x": False, "y": False, "z": False}, {"z": True}, use_cache=False)
        plan_times.append((_btime.perf_counter() - t0) * 1000)
    orch = SkillOrchestrator()
    exec_times = []
    skills_to_run = target_skills if target_skills else orch.registry.list()[:3]
    import asyncio as _basyncio
    for _ in range(min(iterations, 5)):
        for sname in skills_to_run:
            skill = orch.registry.get_or_create(sname)
            if skill is None:
                continue
            t0 = _btime.perf_counter()
            _basyncio.run(orch._execute_single(sname, {}, dry_run=True, timeout_seconds=5, max_retries=0, retry_base_delay=0))
            exec_times.append((_btime.perf_counter() - t0) * 1000)
    _print_json({"iterations": iterations, "goap_planning": {"mean_ms": round(sum(plan_times) / len(plan_times), 2) if plan_times else 0, "min_ms": round(min(plan_times), 2) if plan_times else 0, "max_ms": round(max(plan_times), 2) if plan_times else 0, "total_calls": len(plan_times)}, "skill_execution": {"mean_ms": round(sum(exec_times) / len(exec_times), 2) if exec_times else 0, "min_ms": round(min(exec_times), 2) if exec_times else 0, "max_ms": round(max(exec_times), 2) if exec_times else 0, "skills_tested": skills_to_run, "total_calls": len(exec_times)}})
    return 0


# ── A/B testing & Canary commands ─────────────────────────────────────────


def _handle_ab_test_start(args, client=None, cfg=None) -> int:
    import importlib as _ab_il

    from shopee_agent.skills.ab_testing import get_ab_registry
    mod_control = _ab_il.import_module(args.control_module)
    mod_variant = _ab_il.import_module(args.variant_module)
    cls_control = getattr(mod_control, args.control_class)
    cls_variant = getattr(mod_variant, args.variant_class)
    reg = get_ab_registry()
    reg.register_test(args.skill_name, cls_control, cls_variant, traffic_split=args.split)
    _print_json({"skill": args.skill_name, "control": args.control_class, "variant": args.variant_class, "status": "started"})
    return 0


def _handle_ab_test_status(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.ab_testing import get_ab_registry
    reg = get_ab_registry()
    _print_json(reg.summary())
    return 0


def _handle_canary_start(args, client=None, cfg=None) -> int:
    import importlib as _ca_il

    from shopee_agent.skills.canary import get_canary
    mod_new = _ca_il.import_module(args.new_module)
    cls_new = getattr(mod_new, args.new_class)
    canary = get_canary()
    cid = canary.start_canary(args.skill_name, cls_new, initial_pct=args.initial_pct, max_error_rate=args.max_error)
    _print_json({"canary_id": cid, "skill": args.skill_name, "initial_pct": args.initial_pct})
    return 0


def _handle_canary_status(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.canary import get_canary
    canary = get_canary()
    _print_json({"canaries": canary.list_canaries()})
    return 0


def _handle_canary_promote(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.canary import get_canary
    canary = get_canary()
    ok = canary.promote(args.canary_id)
    _print_json({"canary_id": args.canary_id, "promoted": ok})
    return 0


def _handle_canary_rollback(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.canary import get_canary
    canary = get_canary()
    ok = canary.rollback(args.canary_id)
    _print_json({"canary_id": args.canary_id, "rolled_back": ok})
    return 0


def _handle_sandbox_test(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.shopee_sandbox import ShopeeSandboxClient
    _client = ShopeeSandboxClient()
    result = _client.test_connectivity()
    _print_json(result)
    return 0


# ── Plan commands (not yet extracted) ─────────────────────────────────────


def _handle_plan_optimize(args, client=None, cfg=None) -> int:
    from shopee_agent.goap_planner import GOAPPlanner
    from shopee_agent.plan_optimizer import compare_plan_costs, suggest_optimizations
    from shopee_agent.skills.loader import discover_and_register
    from shopee_agent.skills.registry import default_registry as _po_reg
    discover_and_register()
    planner = GOAPPlanner()
    planner.load_skills(_po_reg)
    if args.compare:
        current = json.loads(args.current_state)
        goal = json.loads(args.goal_state)
        _print_json(compare_plan_costs(planner, current, goal))
    else:
        _print_json({"suggestions": suggest_optimizations(planner)})
    return 0


def _handle_skill_anomaly(args, client=None, cfg=None) -> int:
    from shopee_agent.anomaly_detector import AnomalyDetector
    detector = AnomalyDetector()
    if args.action == "summary":
        _print_json(detector.get_anomaly_summary())
    elif args.action == "check":
        from shopee_agent.skills.sandbox import get_profile_summary
        profiles = get_profile_summary()
        anomalies = []
        for name, data in profiles.items():
            anomalies.extend(detector.check_execution(name, data.get("avg_elapsed", 0), True))
        _print_json({"anomalies": anomalies, "checked": len(profiles)})
    return 0


def _handle_skill_version(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.version_history import get_skill_history
    history = get_skill_history()
    if args.action == "list":
        _print_json(history.get_all_summary())
    elif args.action == "history":
        if not args.skill_name:
            _print_json({"error": "skill_name required"})
        else:
            _print_json({"versions": history.get_history(args.skill_name)})
    elif args.action == "rollback":
        if not args.skill_name or not args.target_version:
            _print_json({"error": "skill_name and target_version required"})
        else:
            v = history.rollback(args.skill_name, args.target_version)
            _print_json(v or {"error": "version not found"})
    return 0


_multi_approval_workflows: dict[str, Any] = {}


def _handle_multi_approve(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.approval import MultiStepApproval
    if args.action == "create":
        if not args.skill_name or not args.steps:
            _print_json({"error": "skill_name and steps required"})
            return 1
        steps = [s.strip() for s in args.steps.split(",") if s.strip()]
        m = MultiStepApproval(args.skill_name, steps)
        _multi_approval_workflows[args.skill_name] = m
        _print_json({"created": args.skill_name, "steps": steps, "status": m.get_status()})
    elif args.action in ("approve", "reject"):
        if not args.skill_name or not args.approver:
            _print_json({"error": "skill_name and approver required"})
            return 1
        m = _multi_approval_workflows.get(args.skill_name)
        if m is None:
            _print_json({"error": "workflow not found"})
            return 1
        ok = m.approve(args.approver) if args.action == "approve" else m.reject(args.approver)
        _print_json({"action": args.action, "approver": args.approver, "ok": ok, "status": m.get_status()})
    elif args.action == "status":
        if not args.skill_name:
            _print_json({"error": "skill_name required"})
            return 1
        m = _multi_approval_workflows.get(args.skill_name)
        _print_json(m.get_status() if m else {"error": "not_found"})
    return 0


def _handle_plan_heal(args, client=None, cfg=None) -> int:
    import json as _phj

    from shopee_agent.plan_healer import execute_with_healing
    from shopee_agent.skills.loader import discover_and_register
    from shopee_agent.skills.orchestrator import SkillOrchestrator
    discover_and_register()
    orch = SkillOrchestrator()
    current = _phj.loads(args.current_state)
    goal = _phj.loads(args.goal_state)
    result = execute_with_healing(orch, current, goal, max_repairs=args.max_repairs, dry_run=args.dry_run)
    _print_json(result)
    return 0


def _handle_plan_explain(args, client=None, cfg=None) -> int:
    import json as _pej

    from shopee_agent.goap_planner import GOAPPlanner
    from shopee_agent.plan_explainer import explain_plan_nl, explain_with_llm
    from shopee_agent.skills.loader import discover_and_register
    from shopee_agent.skills.registry import default_registry as _per
    discover_and_register()
    planner = GOAPPlanner()
    planner.load_skills(_per)
    current = _pej.loads(args.current_state)
    goal = _pej.loads(args.goal_state)
    if args.llm:
        text = explain_with_llm(planner, current, goal)
    else:
        text = explain_plan_nl(planner, current, goal)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        _print_json({"saved": args.output})
    else:
        print(text)
    return 0


def _handle_proactive_goals(args, client=None, cfg=None) -> int:
    import json as _pgj

    from shopee_agent.proactive_goals import suggest_goals
    metrics = _pgj.loads(args.metrics)
    suggestions = suggest_goals(metrics)
    _print_json({"suggestions": suggestions, "count": len(suggestions)})
    return 0


def _handle_cost_predict(args, client=None, cfg=None) -> int:
    from shopee_agent.cost_predictor import predict_cost
    from shopee_agent.goap_planner import GOAPPlanner
    from shopee_agent.skills.loader import discover_and_register
    from shopee_agent.skills.registry import default_registry as _cpr
    discover_and_register()
    planner = GOAPPlanner()
    planner.load_skills(_cpr)
    result = predict_cost(planner, args.actions)
    _print_json(result)
    return 0


def _handle_skill_market(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.marketplace import export_skill_package, import_skill_package, load_package, save_package
    from shopee_agent.skills.registry import default_registry as _smr
    if args.action == "export":
        cls = _smr.get(args.skill_name)
        if cls is None:
            _print_json({"error": f"skill '{args.skill_name}' not found"})
            return 1
        pkg = export_skill_package(cls)
        if args.output:
            path = save_package(pkg, args.output)
            _print_json({"exported": args.skill_name, "saved": str(path)})
        else:
            _print_json(pkg)
    elif args.action == "import":
        if not args.input:
            _print_json({"error": "input file required"})
            return 1
        pkg = load_package(args.input)
        if pkg is None:
            _print_json({"error": "invalid package"})
            return 1
        ok = import_skill_package(pkg, _smr)
        _print_json({"imported": ok, "skill": pkg.get("skill", {}).get("name", "unknown")})
    elif args.action == "list":
        _print_json({"skills": _smr.list()})
    return 0


def _handle_federated(args, client=None, cfg=None) -> int:
    import json as _flj

    from shopee_agent.federated_learning import FederatedLearningCoordinator
    fed = FederatedLearningCoordinator()
    if args.action == "stores":
        _print_json({"stores": fed.list_stores(), "count": fed.get_store_count()})
    elif args.action == "aggregate":
        _print_json(fed.aggregate())
    elif args.action == "report":
        if not args.store_id:
            _print_json({"error": "store_id required"})
            return 1
        data = _flj.loads(args.data)
        fed.report(args.store_id, data)
        _print_json({"reported": args.store_id})
    return 0


def _handle_plan_conform(args, client=None, cfg=None) -> int:
    import json as _pcj

    from shopee_agent.plan_conformance import check_conformance
    from shopee_agent.skills.registry import default_registry as _pcr
    expected_actions = _pcj.loads(args.expected_actions)
    expected_effects = _pcj.loads(args.expected_effects)
    actual_state = _pcj.loads(args.actual_state)
    result = check_conformance(expected_actions, expected_effects, [], actual_state, _pcr)
    _print_json(result)
    return 0


# ── Export / Cleanup / Health (plugable) ──────────────────────────────────


def _handle_export(args, client=None, cfg=None) -> int:
    from shopee_agent.cli_commands.export_cmd import handle_export
    handle_export(args)
    return 0


def _handle_cleanup(args, client=None, cfg=None) -> int:
    from shopee_agent.cli_commands.cleanup_cmd import handle_cleanup
    handle_cleanup(args)
    return 0


def _handle_health(args, client=None, cfg=None) -> int:
    from shopee_agent.cli_commands.health_cmd import handle_health
    handle_health(args)
    return 0


# ── Queue / Metrics / Flash sale exec / AB auto / Browser / Supply / Fed v2 ──


def _handle_queue(args, client=None, cfg=None) -> int:
    from shopee_agent.event_bus import AsyncEventBus
    _bus = AsyncEventBus()
    if args.queue_action == "status":
        _print_json(_bus.stats().__dict__ if hasattr(_bus.stats(), "__dict__") else _bus.stats())
    elif args.queue_action == "dlq":
        dlq_events = _bus.dlq()[:args.max]
        _print_json({"dlq_count": len(dlq_events), "events": [str(e) for e in dlq_events]})
    elif args.queue_action == "retry":
        replayed = _bus.replay_dlq(max_events=args.max)
        _print_json({"replayed": replayed})
    return 0


def _handle_metrics_export(args, client=None, cfg=None) -> int:
    from shopee_agent.metrics_exporter import MetricsExporter
    exporter = MetricsExporter()
    exporter.inc("laura_agent_cycles_total", value=1)
    text = exporter.render()
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        _print_json({"saved": args.output})
    else:
        print(text)
    return 0


def _handle_flash_sale_exec(args, client=None, cfg=None) -> int:
    from shopee_agent.flash_sale_executor import FlashSaleExecutor
    from shopee_agent.flash_sale_recommender import FlashSaleRecommender
    _client = client
    _cfg = cfg
    if _client is None or _cfg is None:
        from shopee_agent.client import ShopeeClient
        from shopee_agent.config import load_config
        _cfg = load_config()
        _client = ShopeeClient(_cfg)
    effective_access_token = args.access_token or _cfg.default_access_token
    effective_shop_id = args.shop_id or _cfg.default_shop_id
    executor = FlashSaleExecutor(_client, access_token=effective_access_token, shop_id=effective_shop_id)
    if args.action == "list":
        _print_json({"active": executor.get_active_flash_sales()})
    elif args.action == "cancel":
        ok = executor.cancel_flash_sale(args.item_id)
        _print_json({"cancelled": ok, "item_id": args.item_id})
    elif args.action == "create":
        recommender = FlashSaleRecommender(_client, access_token=effective_access_token, shop_id=effective_shop_id)
        rec = recommender.generate_recommendations()
        result = executor.execute_recommendations(rec, auto_approve=args.auto_approve)
        _print_json(result)
    return 0


def _handle_ab_auto_promote(args, client=None, cfg=None) -> int:
    from shopee_agent.ab_test_automator import ABTestAutomator
    from shopee_agent.skills.ab_testing import ABTestRegistry
    registry = getattr(ABTestRegistry, "_instance", ABTestRegistry())
    automator = ABTestAutomator(registry)
    if args.test_id:
        result = automator.evaluate_and_promote(args.test_id, min_confidence=args.min_confidence, min_samples=args.min_samples)
    else:
        results = automator.evaluate_all(min_confidence=args.min_confidence, min_samples=args.min_samples)
        result = {"evaluated": len(results), "results": results}
    _print_json(result)
    return 0


def _handle_browser_run(args, client=None, cfg=None) -> int:
    from shopee_agent.skills.browser_skill import BrowserSkill
    skill = BrowserSkill()
    params = {"action": args.action, "url": args.url, "selector": args.selector, "value": args.value, "js": args.js, "screenshot": args.screenshot}
    result = skill.run(params)
    _print_json(result)
    return 0


def _handle_supply_chain(args, client=None, cfg=None) -> int:
    from shopee_agent.supply_chain_planner_v2 import (
        AutoPurchaseOrderGenerator,
        MultiWarehouseBalancer,
        SupplierScorer,
        SupplyChainPlannerV2,
    )
    SupplyChainPlannerV2()
    if args.sc_action == "score-supplier":
        scorer = SupplierScorer()
        result = scorer.score_supplier({"supplier_id": args.supplier_id, "delivery_time_days": 5, "defect_rate_pct": 2, "price_competitiveness": 0.85, "communication_score": 0.9, "order_accuracy_pct": 98})
        _print_json(result)
    elif args.sc_action == "generate-po":
        import json as _scj
        po_gen = AutoPurchaseOrderGenerator()
        items = _scj.loads(args.items)
        result = po_gen.generate_po(args.supplier_id, items, {})
        _print_json(result)
    elif args.sc_action == "balance":
        balancer = MultiWarehouseBalancer()
        result = balancer.suggest_rebalance("wh_001")
        _print_json(result)
    return 0


def _handle_federated_v2(args, client=None, cfg=None) -> int:
    import json as _fv2j

    from shopee_agent.federated_learning_v2 import FederatedLearningOrchestratorV2
    orch = FederatedLearningOrchestratorV2()
    if args.fed_v2_action == "secure-round":
        reports = _fv2j.loads(args.reports)
        result = orch.secure_round(reports)
        _print_json(result)
    elif args.fed_v2_action == "cross-train":
        result = orch.cross_train(args.store_id, rounds=args.rounds)
        _print_json(result)
    elif args.fed_v2_action == "privacy":
        _print_json(orch.get_privacy_report())
    return 0


HANDLER_DISPATCH = {
    # Extracted inline handlers
    "completion": _handle_completion,
    "dashboard": _handle_dashboard,
    "order-list": _handle_order_list,
    "order-detail": _handle_order_detail,
    "autonomous-loop": _handle_autonomous_loop,
    "logistics-channel-list": _handle_logistics_channel_list,
    "logistics-tracking-number": _handle_logistics_tracking_number,
    "logistics-info": _handle_logistics_info,
    "returns-list": _handle_returns_list,
    "returns-detail": _handle_returns_detail,
    "payment-escrow-detail": _handle_payment_escrow_detail,
    "discount-list": _handle_discount_list,
    "voucher-list": _handle_voucher_list,
    "bundle-deal-list": _handle_bundle_deal_list,
    "add-on-deal-list": _handle_add_on_deal_list,
    "media-video-init-upload": _handle_media_video_init_upload,
    "media-video-upload-result": _handle_media_video_upload_result,
    "media-video-wait-completion": _handle_media_video_wait_completion,
    "media-video-upload-part": _handle_media_video_upload_part,
    "media-video-complete-upload": _handle_media_video_complete_upload,
    "api-call": _handle_api_call,
    "api-endpoints": _handle_api_endpoints,
    "api-families": _handle_api_families,
    "api-serve": _handle_api_serve,
    "health-check": _handle_health_check,
    "webhook-start": _handle_webhook_start,
    "webhook-drain": _handle_webhook_drain,
    "ollama-status": _handle_ollama_status,
    "ollama-fix": _handle_ollama_fix,
    "llm-prompts": _handle_llm_prompts,
    "llm-analyze": _handle_llm_analyze,
    "anomaly-detect": _handle_anomaly_detect,
    "predict-refunds": _handle_predict_refunds,
    "performance-report": _handle_performance_report,
    "export-report": _handle_export_report,
    "schedule-report": _handle_schedule_report,
    "realtime-config": _handle_realtime_config,
    "activity": _handle_activity,
    "dashboard-cli": _handle_dashboard_cli,
    "doctor": _handle_doctor,
    "decision-status": _handle_decision_status,
    "decision-history": _handle_decision_history,
    "decision-detail": _handle_decision_detail,
    "decision-cycle": _handle_decision_cycle,
    "decision-metrics": _handle_decision_metrics,
    "decision-outcomes": _handle_decision_outcomes,
    "decision-learn": _handle_decision_learn,
    "decision-effectiveness": _handle_decision_effectiveness,
    "decision-similar": _handle_decision_similar,
    "decision-reindex-backend": _handle_decision_reindex_backend,
    "metrics-dashboard": _handle_metrics_dashboard,
    "agent-orchestration": _handle_agent_orchestration,
    "flash-sale-recommend": _handle_flash_sale_recommend,
    "competitive-intel-summary": _handle_competitive_intel_summary,
    "branding-growth-summary": _handle_branding_growth_summary,
    "economic-brain-summary": _handle_economic_brain_summary,
    "start": _handle_start,
    "daemon": _handle_daemon,
    "shell": _handle_shell,
    "skill-run": _handle_skill_run,
    "skill-goap-plan": _handle_skill_goap_plan,
    "skill-test": _handle_skill_test,
    "goal-synthesize": _handle_goal_synthesize,
    "goal-nl": _handle_goal_nl,
    "skill-approve": _handle_skill_approve,
    "skill-reject": _handle_skill_reject,
    "skill-approval-list": _handle_skill_approval_list,
    "store-list": _handle_store_list,
    "store-init": _handle_store_init,
    "store-summary": _handle_store_summary,
    "benchmark": _handle_benchmark,
    "ab-test-start": _handle_ab_test_start,
    "ab-test-status": _handle_ab_test_status,
    "canary-start": _handle_canary_start,
    "canary-status": _handle_canary_status,
    "canary-promote": _handle_canary_promote,
    "canary-rollback": _handle_canary_rollback,
    "sandbox-test": _handle_sandbox_test,
    "plan-optimize": _handle_plan_optimize,
    "skill-anomaly": _handle_skill_anomaly,
    "skill-version": _handle_skill_version,
    "multi-approve": _handle_multi_approve,
    "plan-heal": _handle_plan_heal,
    "plan-explain": _handle_plan_explain,
    "proactive-goals": _handle_proactive_goals,
    "cost-predict": _handle_cost_predict,
    "skill-market": _handle_skill_market,
    "federated": _handle_federated,
    "plan-conform": _handle_plan_conform,
    "export": _handle_export,
    "cleanup": _handle_cleanup,
    "health": _handle_health,
    "queue": _handle_queue,
    "metrics-export": _handle_metrics_export,
    "flash-sale-exec": _handle_flash_sale_exec,
    "ab-auto-promote": _handle_ab_auto_promote,
    "browser-run": _handle_browser_run,
    "supply-chain": _handle_supply_chain,
    "federated-v2": _handle_federated_v2,
    # Extracted inline handlers
    "competitors": handle_competitors,
    "pricing": handle_pricing,
    "refunds": handle_refunds,
    "campaign": handle_campaign,
    "workers": handle_workers,
    "cross-sell": handle_cross_sell,
    "sc": handle_sc,
    "vision": handle_vision,
    "chat": handle_chat,
    "telegram": handle_telegram,
    "report": handle_report,
    # Skills
    "skill-list": _handle_skill_list,
    "skill-register": _handle_skill_register,
    "skill-history": _handle_skill_history,
    "skill-create": _handle_skill_create,
    "skill-simulate": _handle_skill_simulate,
    "skill-reload": _handle_skill_reload,
    "skill-profile": _handle_skill_profile,
    "skill-generate": _handle_skill_generate,
    "skill-goap-explain": _handle_skill_goap_explain,
    "skill-rollback-learning": _handle_skill_rollback_learning,
    "learning-stats": _handle_learning_stats,
    # Goals
    "goal-summary": _handle_goal_summary,
    "goal-list": _handle_goal_list,
    "goal-add": _handle_goal_add,
    "goal-top": _handle_goal_top,
    "goal-complete": _handle_goal_complete,
    "goal-library": _handle_goal_library,
    # Strategic
    "strategic-plan": _handle_strategic_plan,
    # Trace / Insights
    "trace": _handle_trace,
    "insights-trend": _handle_insights_trend,
    "insights-anomaly": _handle_insights_anomaly,
    "insights-recommendations": _handle_insights_recommendations,
    "insights-summary": _handle_insights_summary,
    # Analytics / Charts
    "analytics-trends": _handle_analytics_trends,
    "charts": _handle_charts,
    "chart-dashboard": _handle_chart_dashboard,
    # Plans
    "plan-viz": _handle_plan_viz,
    "plan-diff": _handle_plan_diff,
    "plan-export": _handle_plan_export,
    "plan-import": _handle_plan_import,
    "plan-batch": _handle_plan_batch,
    "plan-store": _handle_plan_store,
    "planner-alerts": _handle_planner_alerts,
    "plan-template": _handle_plan_template,
    "plan-schedule": _handle_plan_schedule,
    # Multi-tenant
    "tenant": _handle_tenant,
}
