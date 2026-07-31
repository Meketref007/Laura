**Phase 20 — AI-Powered Insights & LLM Analysis**

- **Goal:** provide AI explanations, recommendations and anomaly reasoning using a local Ollama LLM.
- **Implemented:** `shopee_agent/insights_llm.py` with: trend analysis, anomaly explanation, recommendations, executive summary, predictions, and batch alert analysis.
- **LLM integration:** uses `shopee_agent/llm_local.py` (`LauraOllamaAnalyzer`). Integration is now lazy-initialized and non-blocking; CLI falls back to heuristic responses when Ollama or models are unavailable.
- **CLI:** new commands: `insights-trend`, `insights-anomaly`, `insights-recommendations`, `insights-summary` (see `shopee_agent/cli.py`).
- **Testing:** Added `tests/test_insights_llm.py` with mocked analyzer to allow fast CI without Ollama.
- **Next steps:**
  - Add more unit tests for parsing and edge cases.
  - Harden async handling and provide an optional background model pull mechanism.
  - Add CI job that runs tests and optionally spins up a lightweight Ollama mock for integration tests.

**Notes:**
- If Ollama is not running or model isn't pulled, commands now return a deterministic heuristic fallback rather than blocking.
- Files: `shopee_agent/insights_llm.py`, `shopee_agent/llm_local.py`, `tests/test_insights_llm.py`.
