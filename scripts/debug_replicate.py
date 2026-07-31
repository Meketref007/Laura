"""Debug - exactly replicate ask_local behavior."""
import os, sys
os.environ["LAURA_LLM_MODEL"] = "llama3.2:3b"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Exact same code as ask_local
import requests as _req
_host = os.getenv("LAURA_OLLAMA_HOST", "http://127.0.0.1:11434")
_model = os.getenv("LAURA_LLM_MODEL", "qwen2.5:7b")
prompt = "say hello"
max_tokens = 50
print(f"Host: {_host}, Model: {_model}")
_resp = _req.post(
    f"{_host}/api/generate",
    json={"model": _model, "prompt": prompt, "stream": False, "options": {"num_predict": max_tokens}},
    timeout=60,
)
print(f"HTTP {_resp.status_code}")
if _resp.status_code == 200:
    _text = _resp.json().get("response", "")
    print(f"OK: {_text.strip()}")
else:
    print(f"Error: {_resp.text[:200]}")
