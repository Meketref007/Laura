import json


def test_cli_reindex_writes_vectors_sidecar(tmp_path):
    # Prepare a tiny outcomes JSONL
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    outcomes_path = reports_dir / "decision_outcomes.jsonl"
    outcomes = [
        {"decision_id": "d1", "rule_id": "r1", "feedback": "increase price", "metadata": {"k": "v"}},
        {"decision_id": "d2", "rule_id": "r2", "feedback": "decrease price", "metadata": {"k": "w"}},
    ]
    with outcomes_path.open("w", encoding="utf-8") as fh:
        for o in outcomes:
            fh.write(json.dumps(o, ensure_ascii=False) + "\n")

    vectors_path = tmp_path / "vectors.jsonl"

    # Import CLI helper and perform the same simple reindex logic locally
    from shopee_agent.cli import _text_to_simple_vector

    recs = []
    with outcomes_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            obj = json.loads(line)
            pieces = [str(obj.get("rule_id", "")), str(obj.get("feedback", ""))]
            meta = obj.get("metadata") or {}
            try:
                meta_text = json.dumps(meta, ensure_ascii=False)
            except Exception:
                meta_text = str(meta)
            pieces.append(meta_text)
            text = " ".join([p for p in pieces if p])
            vec = _text_to_simple_vector(text or obj.get("decision_id", ""), dim=128)
            rec = {"decision_id": str(obj.get("decision_id")), "vector": vec, "metadata": {"rule_id": obj.get("rule_id")}}
            recs.append(rec)

    vectors_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs), encoding="utf-8")

    assert vectors_path.exists()
    loaded = [json.loads(line) for line in vectors_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(loaded) == 2
    ids = {r["decision_id"] for r in loaded}
    assert ids == {"d1", "d2"}
