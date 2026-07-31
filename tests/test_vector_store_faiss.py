import pytest

faiss = pytest.importorskip("faiss", reason="faiss not installed; skipping Faiss adapter tests")

from shopee_agent.vector_store_faiss import FaissVectorStore  # noqa: E402


def test_faiss_vector_store_basic():
    store = FaissVectorStore(dim=3)
    v1 = [1.0, 0.0, 0.0]
    v2 = [0.0, 1.0, 0.0]

    store.index("d1", v1, metadata={"note": "first"})
    store.index("d2", v2, metadata={"note": "second"})

    res = store.query([0.9, 0.1, 0.0], top_k=2)
    assert len(res) > 0
