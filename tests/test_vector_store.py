from shopee_agent.vector_store import InMemoryVectorStore


def test_inmemory_vector_store_basic():
    store = InMemoryVectorStore()
    store.index("a", [1.0, 0.0], {"text": "alpha"})
    store.index("b", [0.0, 1.0], {"text": "beta"})

    # Query closer to 'a'
    res = store.query([0.9, 0.1], top_k=2)
    assert res[0][0] == "a"
    assert res[0][1] > res[1][1]

    # Query exact 'b'
    res2 = store.query([0.0, 1.0], top_k=1)
    assert res2[0][0] == "b"
