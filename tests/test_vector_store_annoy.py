import os
import tempfile

import importlib.util
import pytest

if importlib.util.find_spec("annoy") is None:
    pytest.skip("annoy not installed; skipping Annoy tests", allow_module_level=True)

from shopee_agent.vector_store_annoy import AnnoyVectorStore


def test_annoy_vector_store_basic_index_query():
    tmpdir = tempfile.mkdtemp()
    index_path = os.path.join(tmpdir, "test.ann")
    meta_path = os.path.join(tmpdir, "test_meta.json")

    store = AnnoyVectorStore(dim=3, index_path=index_path, meta_path=meta_path, n_trees=10)

    v1 = [1.0, 0.0, 0.0]
    v2 = [0.0, 1.0, 0.0]

    store.index("doc1", v1, metadata={"note": "first"})
    store.index("doc2", v2, metadata={"note": "second"})

    # Query near v1
    res = store.query([0.9, 0.1, 0.0], top_k=2)
    assert len(res) == 2
    # top result should be doc1
    assert res[0][0] == "doc1"
