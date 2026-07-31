"""Cache, Memory & Learning commands: cache, memory-semantic-search, memory-reindex-vectors, learning-summary, strategy-summary, self-healing-summary."""
import json
import sys
from pathlib import Path

from ._utils import print_json


def register_subparsers(sub):
    cache_cmd = sub.add_parser("cache", help="Gerenciar cache local de dados da API")
    cache_sub = cache_cmd.add_subparsers(dest="cache_action", required=False)
    cache_sub.add_parser("list", help="Listar entradas em cache")
    cache_clear = cache_sub.add_parser("clear", help="Limpar todo o cache")
    cache_clear.add_argument("--name", default=None, help="Limpar apenas esta entrada especifica")
    cache_inspect = cache_sub.add_parser("inspect", help="Ver detalhes de uma entrada")
    cache_inspect.add_argument("name", help="Nome da entrada em cache")
    mem_search = sub.add_parser("memory-semantic-search", help="Query the decision memory semantically (vector or text)")
    mem_search.add_argument("--vector", default=None, help="Comma-separated vector values (e.g. '0.1,0.2,0.3')")
    mem_search.add_argument("--text", default=None, help="Text query to embed with a simple fallback embedder")
    mem_search.add_argument("--top-k", type=int, default=5, help="Number of results to return")
    mem_search.add_argument("--out", default=None, help="Optional JSON output file for results")
    mem_search.add_argument("--outcomes-path", default="reports/decision_outcomes.jsonl", help="Decision outcomes JSONL file")
    mem_search.add_argument("--vectors-path", default="reports/decision_vectors.jsonl", help="Sidecar vectors JSONL file")
    mem_search.add_argument("--use-ollama", action="store_true", help="Use local Ollama to embed --text queries (best-effort)")
    mem_search.add_argument("--vector-backend", choices=["memory", "annoy", "faiss"], default="memory", help="Which vector backend to use for search")
    mem_search.add_argument("--annoy-index-path", default="reports/annoy_index.ann", help="Annoy index file path")
    mem_search.add_argument("--annoy-meta-path", default="reports/annoy_meta.json", help="Annoy meta sidecar path")
    mem_search.add_argument("--faiss-index-path", default="reports/faiss_index.faiss", help="Faiss index file path")
    mem_search.add_argument("--faiss-meta-path", default="reports/faiss_meta.json", help="Faiss meta sidecar path")
    mem_reindex = sub.add_parser("memory-reindex-vectors", help="Rebuild decision vector sidecar from outcomes using fallback embedder")
    mem_reindex.add_argument("--outcomes-path", default="reports/decision_outcomes.jsonl", help="Decision outcomes JSONL file")
    mem_reindex.add_argument("--vectors-path", default="reports/decision_vectors.jsonl", help="Sidecar vectors JSONL file to write")
    mem_reindex.add_argument("--dry-run", action="store_true", help="Do not write files; just show summary")
    mem_reindex.add_argument("--limit", type=int, default=0, help="Limit number of outcomes to reindex (0 = all)")
    mem_reindex.add_argument("--vector-backend", choices=["memory", "annoy", "faiss"], default="memory", help="Where to write reindexed vectors")
    mem_reindex.add_argument("--annoy-index-path", default="reports/annoy_index.ann", help="Annoy index file path")
    mem_reindex.add_argument("--annoy-meta-path", default="reports/annoy_meta.json", help="Annoy meta sidecar path")
    mem_reindex.add_argument("--faiss-index-path", default="reports/faiss_index.faiss", help="Faiss index file path")
    mem_reindex.add_argument("--faiss-meta-path", default="reports/faiss_meta.json", help="Faiss meta sidecar path")
    learning_summary = sub.add_parser("learning-summary", help="Evaluate the learning loop, outcome trends, and failure hotspots")
    learning_summary.add_argument("--outcomes-path", default="reports/decision_outcomes.jsonl", help="Decision outcomes JSONL file")
    learning_summary.add_argument("--notes-path", default="reports/long_term_memory_notes.jsonl", help="Long-term memory notes JSONL file")
    learning_summary.add_argument("--window-days", type=int, default=30, help="Learning window size in days")
    learning_summary.add_argument("--output", default=None, help="Optional JSON output file")
    learning_summary.add_argument("--no-persist-note", action="store_true", help="Do not persist a learning note")
    strategy_summary = sub.add_parser("strategy-summary", help="Evaluate long-term growth strategy, seasonal risk, and expansion opportunities")
    strategy_summary.add_argument("--horizon-days", type=int, default=30, help="Forecast horizon in days")
    strategy_summary.add_argument("--output", default=None, help="Optional JSON output file")
    self_healing_summary = sub.add_parser("self-healing-summary", help="Inspect monitoring and circuit breaker state for recovery and failover actions")
    self_healing_summary.add_argument("--output", default=None, help="Optional JSON output file")
    self_healing_summary.add_argument("--auto-reset", action="store_true", help="Attempt breaker resets for open circuits")


def run(args, client=None, cfg=None):
    if args.command == "cache":
        import shopee_agent.api_cache as api_cache
        if args.cache_action == "list" or not args.cache_action:
            entries = api_cache.list_cached()
            if not entries:
                print("Cache vazio.")
                return 0
            print(f"{'Nome':<30} {'Idade (dias)':<15} {'TTL':<8} {'Status':<10} {'Tamanho':<10}")
            print("-" * 80)
            for e in entries:
                status = "FRESCO" if e["fresh"] else "EXPIRADO"
                print(f"{e['name']:<30} {e['age_days']:<15.1f} {e['ttl_days']:<8} {status:<10} {e['size_bytes']:<10}")
            return 0
        if args.cache_action == "clear":
            if args.name:
                api_cache.invalidate(args.name)
                print(f"Cache '{args.name}' limpo.")
            else:
                import shutil

                from shopee_agent.api_cache import CACHE_DIR
                if CACHE_DIR.exists():
                    shutil.rmtree(str(CACHE_DIR))
                    print("Cache completamente limpo.")
            return 0
        if args.cache_action == "inspect":
            data = api_cache.load(args.name)
            if data is None:
                print(f"Cache '{args.name}' nao encontrado ou expirado.")
                return 1
            print_json({"name": args.name, "data": data})
            return 0
        return 0

    if args.command == "memory-semantic-search":
        import shopee_agent.api_cache as api_cache
        from shopee_agent.config import load_config as _load_config
        try:
            cfg_search = _load_config()
            if args.vector_backend == "memory" and getattr(cfg_search, "vector_backend", "memory") == "annoy":
                args.vector_backend = "annoy"
                if not args.annoy_index_path and getattr(cfg_search, "annoy_index_path", None):
                    args.annoy_index_path = cfg_search.annoy_index_path
                if not args.annoy_meta_path and getattr(cfg_search, "annoy_meta_path", None):
                    args.annoy_meta_path = cfg_search.annoy_meta_path
        except Exception:
            pass
        if not args.vector and not args.text:
            print("Provide either --vector or --text for semantic search", file=sys.stderr); return 1
        vec: list[float]
        if args.vector:
            try:
                parts = [p.strip() for p in str(args.vector).split(",") if p.strip()]
                vec = [float(p) for p in parts]
            except Exception:
                print("Invalid --vector format; use comma-separated floats", file=sys.stderr); return 1
        else:
            if args.use_ollama:
                try:
                    import os

                    from shopee_agent.llm_local import LauraOllamaAnalyzer
                    analyzer = LauraOllamaAnalyzer(model=os.getenv("LAURA_LLM_MODEL", "tinyllama"), pull_model=False)
                    emb = analyzer.embed_text(args.text or "", dim=128)
                    if emb and isinstance(emb, list) and len(emb) > 0:
                        vec = emb
                    else:
                        vec = _text_to_simple_vector(args.text or "", dim=128)
                except Exception:
                    vec = _text_to_simple_vector(args.text or "", dim=128)
            else:
                vec = _text_to_simple_vector(args.text or "", dim=128)
        from pathlib import Path as _P

        from shopee_agent.decision_memory import MemoryLayer
        store = None
        vectors_file = _P(args.vectors_path)
        if args.vector_backend == "annoy":
            try:
                from shopee_agent.vector_store_annoy import AnnoyVectorStore
                try:
                    cfg_search = _load_config()
                except Exception:
                    cfg_search = None
                dim = getattr(cfg_search, "vector_dim", 128) if cfg_search is not None else 128
                bg = getattr(cfg_search, "annoy_background_build", False) if cfg_search is not None else False
                interval = getattr(cfg_search, "annoy_build_interval", 60) if cfg_search is not None else 60
                store = AnnoyVectorStore(dim=dim, index_path=args.annoy_index_path, meta_path=args.annoy_meta_path, background_build=bg, build_interval=interval)
                if vectors_file.exists():
                    try:
                        with vectors_file.open("r", encoding="utf-8") as fh:
                            for line in fh:
                                try:
                                    obj = json.loads(line)
                                    doc_id = str(obj.get("decision_id"))
                                    vector = obj.get("vector") or []
                                    meta = obj.get("metadata") or {}
                                    if doc_id and isinstance(vector, list):
                                        try:
                                            store.index(doc_id, [float(x) for x in vector], metadata=meta)
                                        except Exception:
                                            continue
                                except Exception:
                                    continue
                    except Exception:
                        pass
            except Exception:
                store = None
        elif args.vector_backend == "faiss":
            try:
                from shopee_agent.vector_store_faiss import FaissVectorStore
                try:
                    cfg_search = _load_config()
                except Exception:
                    cfg_search = None
                dim = getattr(cfg_search, "vector_dim", 128) if cfg_search is not None else 128
                faiss_index = args.faiss_index_path or (getattr(cfg_search, "faiss_index_path", None) if cfg_search is not None else None)
                faiss_meta = args.faiss_meta_path or (getattr(cfg_search, "faiss_meta_path", None) if cfg_search is not None else None)
                store = FaissVectorStore(dim=dim, index_path=faiss_index, meta_path=faiss_meta)
                if vectors_file.exists():
                    try:
                        with vectors_file.open("r", encoding="utf-8") as fh:
                            for line in fh:
                                try:
                                    obj = json.loads(line)
                                    doc_id = str(obj.get("decision_id"))
                                    vector = obj.get("vector") or []
                                    meta = obj.get("metadata") or {}
                                    if doc_id and isinstance(vector, list):
                                        try:
                                            store.index(doc_id, [float(x) for x in vector], metadata=meta)
                                        except Exception:
                                            continue
                                except Exception:
                                    continue
                    except Exception:
                        pass
            except Exception:
                store = None
        else:
            from shopee_agent.vector_store import InMemoryVectorStore
            store = InMemoryVectorStore()
            if vectors_file.exists():
                try:
                    with vectors_file.open("r", encoding="utf-8") as fh:
                        for line in fh:
                            try:
                                obj = json.loads(line)
                                doc_id = str(obj.get("decision_id"))
                                vector = obj.get("vector") or []
                                meta = obj.get("metadata") or {}
                                if doc_id and isinstance(vector, list):
                                    try:
                                        store.index(doc_id, [float(x) for x in vector], metadata=meta)
                                    except Exception:
                                        continue
                            except Exception:
                                continue
                except Exception:
                    pass
        mem = MemoryLayer(path=args.outcomes_path, vector_store=store, vectors_path=args.vectors_path)
        results = mem.semantic_query(vec, top_k=max(1, int(args.top_k or 5)))
        out_obj = {"query_vector_length": len(vec), "results": []}
        for r in results:
            out_obj["results"].append({"decision_id": r.get("decision_id"), "score": r.get("score"), "meta": r.get("meta")})
        if args.out:
            Path(args.out).write_text(json.dumps(out_obj, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Results saved to: {args.out}")
        else:
            print_json(out_obj)
        return 0

    if args.command == "memory-reindex-vectors":
        from shopee_agent.config import load_config as _load_config
        try:
            cfg_search = _load_config()
            if args.vector_backend == "memory" and getattr(cfg_search, "vector_backend", "memory") == "annoy":
                args.vector_backend = "annoy"
                if not args.annoy_index_path and getattr(cfg_search, "annoy_index_path", None):
                    args.annoy_index_path = cfg_search.annoy_index_path
                if not args.annoy_meta_path and getattr(cfg_search, "annoy_meta_path", None):
                    args.annoy_meta_path = cfg_search.annoy_meta_path
        except Exception:
            pass
        from pathlib import Path as _P
        outcomes_file = _P(args.outcomes_path)
        vectors_file = _P(args.vectors_path)
        if not outcomes_file.exists():
            print(f"Outcomes file not found: {outcomes_file}", file=sys.stderr); return 1
        count = 0
        limit = int(args.limit or 0)
        if not args.dry_run:
            try:
                vectors_file.parent.mkdir(parents=True, exist_ok=True)
                out_fh = vectors_file.open("w", encoding="utf-8")
            except Exception as exc:
                print(f"Failed to open vectors file for write: {exc}", file=sys.stderr); return 1
        else:
            out_fh = None
        try:
            if args.vector_backend == "annoy":
                try:
                    from shopee_agent.vector_store_annoy import AnnoyVectorStore
                    store = AnnoyVectorStore(dim=128, index_path=args.annoy_index_path, meta_path=args.annoy_meta_path)
                except Exception:
                    store = None
            elif args.vector_backend == "faiss":
                try:
                    from shopee_agent.vector_store_faiss import FaissVectorStore
                    store = FaissVectorStore(dim=128, index_path=args.faiss_index_path, meta_path=args.faiss_meta_path)
                except Exception:
                    store = None
            else:
                from shopee_agent.vector_store import InMemoryVectorStore
                store = InMemoryVectorStore()
            with outcomes_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if limit and count >= limit:
                        break
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    pieces = [str(obj.get("rule_id", "")), str(obj.get("feedback", ""))]
                    meta = obj.get("metadata") or {}
                    try:
                        meta_text = json.dumps(meta, ensure_ascii=False)
                    except Exception:
                        meta_text = str(meta)
                    pieces.append(meta_text)
                    text = " ".join([p for p in pieces if p])
                    vec = _text_to_simple_vector(text or obj.get("decision_id", ""), dim=128)
                    if args.vector_backend == "annoy" and store is not None:
                        try:
                            store.index(str(obj.get("decision_id")), vec, metadata={"rule_id": obj.get("rule_id")})
                        except Exception:
                            pass
                    else:
                        rec = {"decision_id": str(obj.get("decision_id")), "vector": vec, "metadata": {"rule_id": obj.get("rule_id")}}
                        if out_fh is not None:
                            out_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    count += 1
        finally:
            if out_fh is not None:
                out_fh.close()
        if args.vector_backend == "annoy" and not args.dry_run and store is not None:
            try:
                store._ensure_index()
                store._save_meta()
            except Exception:
                pass
        print(f"Reindexed {count} outcomes -> {vectors_file} (dry_run={bool(args.dry_run)})")
        return 0

    if args.command == "learning-summary":
        from shopee_agent.learning_system import LearningSystem, dump_learning_report
        system = LearningSystem(outcomes_path=args.outcomes_path, notes_path=args.notes_path)
        report = system.evaluate(window_days=args.window_days, persist_note=not args.no_persist_note)
        if args.output:
            output_path = dump_learning_report(report, args.output)
            print(f"Wrote learning report to {output_path}")
        print_json(report.to_dict())
        return 0

    if args.command == "strategy-summary":
        from shopee_agent.autonomous_strategy import AutonomousStrategyLayer, dump_strategy_snapshot
        strategy = AutonomousStrategyLayer()
        snapshot = strategy.evaluate_goal(horizon_days=args.horizon_days)
        if args.output:
            output_path = dump_strategy_snapshot(snapshot, args.output)
            print(f"Wrote strategy snapshot to {output_path}")
        print_json(snapshot.to_dict())
        return 0

    if args.command == "self-healing-summary":
        from shopee_agent.self_healing import SelfHealingCoordinator, dump_self_healing_snapshot
        coordinator = SelfHealingCoordinator()
        result = coordinator.run_recovery_plan(auto_reset=args.auto_reset)
        snapshot = result["snapshot"]
        if args.output:
            output_path = dump_self_healing_snapshot(coordinator.evaluate(), args.output)
            print(f"Wrote self-healing snapshot to {output_path}")
        print_json({"snapshot": snapshot, "reset_results": result["reset_results"]})
        return 0

    return 2


def _text_to_simple_vector(text: str, dim: int = 128) -> list[float]:
    import hashlib
    h = hashlib.sha256(text.encode("utf-8")).digest()
    bys = (h * ((dim // len(h)) + 1))[:dim]
    vec = [((b / 255.0) * 2.0 - 1.0) for b in bys]
    return vec
