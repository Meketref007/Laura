"""Debug - test with and without options."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests

# Without options
r1 = requests.post("http://127.0.0.1:11434/api/generate",
    json={"model": "tinyllama", "prompt": "say hi", "stream": False},
    timeout=30)
print(f'Without options: HTTP {r1.status_code}')
if r1.status_code == 200:
    print(f'  {r1.json().get("response","")[:80]}')
else:
    print(f'  {r1.text[:200]}')

# With options
r2 = requests.post("http://127.0.0.1:11434/api/generate",
    json={"model": "tinyllama", "prompt": "say hi", "stream": False, "options": {"num_predict": 50}},
    timeout=30)
print(f'With options: HTTP {r2.status_code}')
if r2.status_code == 200:
    print(f'  {r2.json().get("response","")[:80]}')
else:
    print(f'  {r2.text[:200]}')

# Try with different model name
r3 = requests.post("http://127.0.0.1:11434/api/generate",
    json={"model": "tinyllama:latest", "prompt": "say hi", "stream": False},
    timeout=30)
print(f'Tinyllama:latest: HTTP {r3.status_code}')
if r3.status_code == 200:
    print(f'  {r3.json().get("response","")[:80]}')
else:
    print(f'  {r3.text[:200]}')
