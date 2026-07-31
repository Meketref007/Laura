import json
import pytest


def test_cli_reindex_annoy(tmp_path):
    # Skip if annoy package not available
    import importlib
    if importlib.util.find_spec("annoy") is None:
        pytest.skip("annoy not available")
    # Prepare a tiny outcomes JSONL
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    outcomes_path = reports_dir / "decision_outcomes.jsonl"
    outcomes = [
        {"decision_id": "a1", "rule_id": "r1", "feedback": "promo", "metadata": {}},
        {"decision_id": "a2", "rule_id": "r2", "feedback": "discount", "metadata": {}},
    ]
    with outcomes_path.open("w", encoding="utf-8") as fh:
        for o in outcomes:
            fh.write(json.dumps(o, ensure_ascii=False) + "\n")

    # Build an Annoy index via the project's InMemory->Annoy flow
    from shopee_agent.cli import _text_to_simple_vector
    from shopee_agent.vector_store_annoy import AnnoyVectorStore

    # Create store in tmp dir
    idx_path = tmp_path / "annoy_index.ann"
    meta_path = tmp_path / "annoy_meta.jsonl"
    store = AnnoyVectorStore(dim=128, index_path=str(idx_path), meta_path=str(meta_path))

    # Index records
    with outcomes_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            obj = json.loads(line)
            text = f"{obj.get('rule_id','')} {obj.get('feedback','')}"
            vec = _text_to_simple_vector(text, dim=128)
            store.index(str(obj.get("decision_id")), vec, metadata={"rule_id": obj.get("rule_id")})

    # Build and save
    store._ensure_index()
    store._save_meta()

    # Query the built store (in-memory vectors present)
    q = _text_to_simple_vector("promo", dim=128)
    res = store.query(q, top_k=1)
    assert len(res) == 1
    assert res[0][0] in {"a1", "a2"}
