"""Test with qwen2.5:7b which is available."""
import os, requests

host = "http://127.0.0.1:11434"
model = "qwen2.5:7b"

r = requests.post(f"{host}/api/generate",
    json={"model": model, "prompt": "Say hello in 3 words", "stream": False},
    timeout=120)
print(f"qwen2.5:7b: HTTP {r.status_code}")
if r.status_code == 200:
    print(f"OK: {r.json().get('response', '')[:100]}")
else:
    print(f"Error: {r.text[:200]}")

# Test with options
r2 = requests.post(f"{host}/api/generate",
    json={"model": model, "prompt": "Say hello in 3 words", "stream": False, "options": {"num_predict": 30}},
    timeout=120)
print(f"qwen2.5:7b with options: HTTP {r2.status_code}")
if r2.status_code == 200:
    print(f"OK: {r2.json().get('response', '')[:100]}")
else:
    print(f"Error: {r2.text[:200]}")
