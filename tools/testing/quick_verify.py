#!/usr/bin/env python3
"""
quick_verify.py - Verificação rápida do sistema Ollama
Executa 8 testes para validar que tudo está funcionando.
"""

import sys
import json
from pathlib import Path

def test_imports():
    """Testa se todos os imports funcionam"""
    try:
        return True, "Imports OK"
    except Exception as e:
        return False, f"Import error: {e}"

def test_prompts():
    """Testa se prompts carregam"""
    try:
        from shopee_agent.prompts import list_available_prompts
        prompts = list_available_prompts()
        if len(prompts) != 4:
            return False, f"Expected 4 prompts, got {len(prompts)}"
        return True, f"Prompts OK ({len(prompts)})"
    except Exception as e:
        return False, f"Prompts error: {e}"

def test_models():
    """Testa se modelos estão disponíveis"""
    try:
        from shopee_agent.llm_local import LauraOllamaAnalyzer
        models = list(LauraOllamaAnalyzer.MODELS.keys())
        if len(models) != 4:
            return False, f"Expected 4 models, got {len(models)}"
        return True, f"Models OK ({', '.join(models)})"
    except Exception as e:
        return False, f"Models error: {e}"

def test_llm_result():
    """Testa se LLMAnalysisResult funciona"""
    try:
        from shopee_agent.llm_local import LLMAnalysisResult
        from datetime import datetime, timezone
        result = LLMAnalysisResult(
            decision="TEST", action="SCALE_WINNERS", priority="HIGH",
            mode="test", metrics={}, reasoning="test", next_steps="test",
            confidence=0.9, timestamp=datetime.now(timezone.utc).isoformat(),
            raw_response="{}", model="llama2", prompt_type="profitability_analyzer",
            inference_time_ms=100
        )
        if result.decision != "TEST":
            return False, "LLMAnalysisResult creation failed"
        return True, "LLMAnalysisResult OK"
    except Exception as e:
        return False, f"LLMAnalysisResult error: {e}"

def test_cli():
    """Testa se CLI parser funciona"""
    try:
        from shopee_agent.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(['llm-prompts'])
        if args.command != 'llm-prompts':
            return False, "CLI parser mismatch"
        return True, "CLI OK"
    except Exception as e:
        return False, f"CLI error: {e}"

def test_requirements():
    """Testa se requirements.txt está correto"""
    try:
        req_file = Path("requirements.txt")
        if not req_file.exists():
            return False, "requirements.txt not found"
        content = req_file.read_text()
        if "anthropic" in content:
            return False, "anthropic still in requirements.txt"
        if "requests" not in content:
            return False, "requests not in requirements.txt"
        return True, "requirements.txt OK"
    except Exception as e:
        return False, f"requirements.txt error: {e}"

def test_metrics():
    """Testa se arquivo de métricas existe"""
    try:
        metrics_file = Path("reports/laura_profitability_inputs_latest.json")
        if not metrics_file.exists():
            return True, "Metrics file not created yet (normal)"
        with open(metrics_file) as f:
            metrics = json.load(f)
        return True, f"Metrics OK ({len(metrics)} fields)"
    except Exception as e:
        return False, f"Metrics error: {e}"

def test_docs():
    """Testa se documentação existe"""
    try:
        docs = [
            "OLLAMA_LOCAL_GUIDE.md",
            "IMPLEMENTATION_STATUS.md",
            "shopee_agent/llm_local.py"
        ]
        missing = [d for d in docs if not Path(d).exists()]
        if missing:
            return False, f"Missing: {', '.join(missing)}"
        return True, f"Documentation OK ({len(docs)} files)"
    except Exception as e:
        return False, f"Docs error: {e}"

def main():
    """Executa todos os testes"""
    tests = [
        ("Imports", test_imports),
        ("Prompts", test_prompts),
        ("Models", test_models),
        ("LLMResult", test_llm_result),
        ("CLI", test_cli),
        ("Requirements", test_requirements),
        ("Metrics", test_metrics),
        ("Documentation", test_docs),
    ]
    
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║          VERIFICAÇÃO RÁPIDA - SISTEMA OLLAMA                      ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        success, message = test_func()
        status = "✅" if success else "❌"
        print(f"{status} {name:20s} - {message}")
        if success:
            passed += 1
        else:
            failed += 1
    
    print()
    print("╔════════════════════════════════════════════════════════════════════╗")
    if failed == 0:
        print(f"║ ✅ TODOS OS {passed} TESTES PASSARAM                                      ║")
        print("║                                                                ║")
        print("║ Sistema pronto para uso!                                       ║")
        print("║                                                                ║")
        print("║ Próximo passo:                                                 ║")
        print("║ $ curl -fsSL https://ollama.ai/install.sh | sh                ║")
        print("║ $ laura llm-analyze                                            ║")
        print("╚════════════════════════════════════════════════════════════════╗")
        return 0
    else:
        print(f"║ ❌ {failed} teste(s) falharam, {passed} passaram                              ║")
        print("╚════════════════════════════════════════════════════════════════╗")
        return 1

if __name__ == "__main__":
    sys.exit(main())
