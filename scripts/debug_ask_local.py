"""Debug ask_local issue."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["LAURA_LLM_MODEL"] = "llama3.2:3b"
os.environ["LAURA_OLLAMA_HOST"] = "http://127.0.0.1:11434"
from shopee_agent.llm_local import ask_local
result = ask_local("say hello", max_tokens=50)
print(f"Result: {result}")
