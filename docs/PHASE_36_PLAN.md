# Phase 36 — Semantic Memory & Vector Store (Plan)

Objective
- Add a semantic/vector memory layer to support Phase 35 learning features.

Goals
- Provide a pluggable `VectorStore` abstraction with a lightweight in-memory reference implementation.
- Allow indexing of decision outcomes and retrieval by similarity.
- Keep an adapter interface so a future Faiss/Annoy/Weaviate backend can be added.

Milestones
1. Define `VectorStore` interface and a simple in-memory implementation.
2. Add unit tests for basic indexing and querying semantics.
3. Integrate `VectorStore` with `DecisionMemory` to optionally persist vectors alongside JSONL.
4. Add CLI commands to rebuild/index and query memory semantically.
5. Evaluate performance and add optional Faiss backend.

Deliverables (MVP)
- `shopee_agent/vector_store.py` — `VectorStore` + `InMemoryVectorStore`.
- Unit tests in `tests/test_vector_store.py`.
- Documentation notes in this file.

Risks & Notes
- MVP will use a pure Python approach (no external deps) for portability.
- Switching to a production vector index should be done behind an adapter layer.
