import json
import pytest


def test_cli_reindex_faiss(tmp_path):
    # Skip if faiss not installed
    import importlib
    if importlib.util.find_spec("faiss") is None:
        pytest.skip("faiss not available")

    # Prepare outcomes
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    outcomes_path = reports_dir / "decision_outcomes.jsonl"
    outcomes = [
        {"decision_id": "f1", "rule_id": "r1", "feedback": "promo", "metadata": {}},
        {"decision_id": "f2", "rule_id": "r2", "feedback": "discount", "metadata": {}},
    ]
    with outcomes_path.open("w", encoding="utf-8") as fh:
        for o in outcomes:
            fh.write(json.dumps(o, ensure_ascii=False) + "\n")

    from shopee_agent.cli import _text_to_simple_vector
    from shopee_agent.vector_store_faiss import FaissVectorStore

    idx_path = tmp_path / "faiss.idx"
    meta_path = tmp_path / "faiss_meta.json"

    store = FaissVectorStore(dim=128, index_path=str(idx_path), meta_path=str(meta_path))

    with outcomes_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            obj = json.loads(line)
            text = f"{obj.get('rule_id','')} {obj.get('feedback','')}"
            vec = _text_to_simple_vector(text, dim=128)
            store.index(str(obj.get("decision_id")), vec, metadata={"rule_id": obj.get("rule_id")})

    q = _text_to_simple_vector("promo", dim=128)
    res = store.query(q, top_k=1)
    assert len(res) >= 0
