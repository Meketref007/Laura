"""
Integração com LLM local via Ollama.

Este módulo fornece integração com modelos LLM rodando localmente (Llama 2, Mistral)
sem depender de APIs externas. Totalmente local, grátis e privado.
"""

import json
import os
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from .llm_providers import LLMConfig, LLMEngine
from .logger import debug, info, warning
from .logger import error as log_error
from .prompts import get_system_prompt
from .telegram_narrator import narrador

_llm_engine = LLMEngine()


def _extract_json_object(raw_response: str) -> str | None:
    text = raw_response.strip()
    if not text:
        return None

    if "```json" in text:
        start = text.find("```json") + len("```json")
        end = text.find("```", start)
        if end > start:
            candidate = text[start:end].strip()
            if candidate:
                return candidate

    if "```" in text:
        start = text.find("```") + len("```")
        end = text.find("```", start)
        if end > start:
            candidate = text[start:end].strip()
            if candidate:
                return candidate

    decoder = json.JSONDecoder()
    for start_char in ("{", "["):
        start = text.find(start_char)
        if start < 0:
            continue
        try:
            obj, _ = decoder.raw_decode(text[start:])
            return json.dumps(obj, ensure_ascii=False)
        except Exception:
            continue

    # Try to find and clean up loose JSON within braces
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if 0 <= brace_start < brace_end:
        candidate = text[brace_start:brace_end + 1]
        # Remove trailing commas before closing braces
        import re as _re
        candidate = _re.sub(r",\s*}", "}", candidate)
        candidate = _re.sub(r",\s*\]", "]", candidate)
        # Try parsing
        try:
            obj = json.loads(candidate)
            return json.dumps(obj, ensure_ascii=False)
        except json.JSONDecodeError:
            pass

    return None


def _get_ollama_hostport(default_host: str = "127.0.0.1", default_port: int = 11434) -> tuple[str, int]:
    raw = os.getenv("LAURA_OLLAMA_HOST", f"http://{default_host}:{default_port}")
    raw = raw.replace("http://", "").replace("https://", "").strip()
    if ":" in raw:
        parts = raw.split(":")
        return parts[0], int(parts[1])
    return raw, default_port


def check_ollama_running(host: str | None = None, port: int | None = None) -> bool:
    """Verifica se Ollama está rodando."""
    if host is None or port is None:
        h, p = _get_ollama_hostport()
        host = host or h
        port = port or p
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex((host, port))
    sock.close()
    return result == 0


def start_ollama_if_needed(model: str = "llama2") -> bool:
    """
    Inicia Ollama se não estiver rodando.
    
    Args:
        model: Modelo a executar (llama2, mistral, neural-chat)
    
    Returns:
        True se Ollama está pronto
    """
    if check_ollama_running():
        debug("Ollama already running")
        return True

    info("Starting Ollama in background")
    try:
        # Iniciar Ollama em background
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # Aguardar inicialização
        for i in range(30):
            if check_ollama_running():
                debug("Ollama initialized successfully", attempts=i+1)
                time.sleep(2)  # Extra para ter certeza
                return True
            time.sleep(1)

        log_error("Ollama startup timeout", attempts=30, timeout_seconds=30)
        return False
    except FileNotFoundError:
        log_error("Ollama executable not found", install_url="https://ollama.ai/install.sh")
        return False


def _run_ollama_command(args: list[str], timeout_seconds: int = 10) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["ollama", *args],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as exc:
        return 1, "", str(exc)


def _parse_ollama_table(stdout: str) -> list[str]:
    items: list[str] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line or line.upper().startswith("NAME"):
            continue
        name = line.split()[0]
        if name and name not in items:
            items.append(name)
    return items


def get_ollama_status(model: str = "tinyllama") -> dict[str, Any]:
    """Collect a concise Ollama runtime status report."""
    service_running = check_ollama_running()
    installed_models: list[str] = []
    loaded_models: list[str] = []
    ps_output = ""
    list_output = ""
    ram_usage = ""
    process_usage = ""

    list_rc, list_stdout, list_stderr = _run_ollama_command(["list"], timeout_seconds=10)
    if list_rc == 0:
        list_output = list_stdout
        installed_models = _parse_ollama_table(list_stdout)
    else:
        list_stderr = list_stderr.strip()

    ps_rc, ps_stdout, ps_stderr = _run_ollama_command(["ps"], timeout_seconds=10)
    if ps_rc == 0:
        ps_output = ps_stdout
        loaded_models = _parse_ollama_table(ps_stdout)
    else:
        ps_stderr = ps_stderr.strip()

    try:
        free_proc = subprocess.run(["free", "-h"], capture_output=True, text=True, timeout=5, check=False)
        ram_usage = free_proc.stdout.strip()
    except Exception as exc:
        ram_usage = str(exc)

    try:
        proc = subprocess.run(
            ["ps", "-o", "pid,rss,vsz,cmd", "-C", "ollama"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        process_usage = proc.stdout.strip()
    except Exception as exc:
        process_usage = str(exc)

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "service_running": service_running,
        "requested_model": model,
        "default_model": os.getenv("LAURA_LLM_MODEL", "tinyllama"),
        "installed_models": installed_models,
        "loaded_models": loaded_models,
        "model_installed": model.split(":")[0] in {m.split(":")[0] for m in installed_models},
        "model_loaded": model.split(":")[0] in {m.split(":")[0] for m in loaded_models},
        "ram_usage": ram_usage,
        "process_usage": process_usage,
        "ollama_list_output": list_output,
        "ollama_ps_output": ps_output,
        "list_error": list_stderr if list_rc != 0 else "",
        "ps_error": ps_stderr if ps_rc != 0 else "",
    }


@dataclass
class LLMAnalysisResult:
    """Resultado de uma análise via LLM local."""

    decision: str
    action: str
    priority: str
    mode: str
    metrics: dict[str, float]
    reasoning: str
    next_steps: str
    confidence: float
    timestamp: str
    raw_response: str
    model: str
    prompt_type: str
    inference_time_ms: int = 0


class LauraOllamaAnalyzer:
    """
    Analisador de profitabilidade usando Ollama (LLM local).
    
    Roda 100% localmente - sem APIs externas, sem custos.
    
    Features:
    - Suporta Llama 2, Mistral, Neural-Chat
    - Totalmente privado (dados nunca saem da máquina)
    - Grátis (open source)
    - Offline (funciona sem internet)
    """

    MODELS = {
        "tinyllama": "TinyLlama (1.1B) - Ultra leve para pouca RAM",
        "llama3.2:3b": "Llama 3.2 (3B) - Rapido e confiavel para JSON",
        "phi3:mini": "Phi-3 Mini (3.8B) - Instrucoes complexas",
        "llama2": "Llama 2 (7B) - Balanceado",
        "mistral": "Mistral (7B) - Rápido e eficiente",
        "neural-chat": "Neural Chat (7B) - Especializado em chat",
        "llama2:13b": "Llama 2 (13B) - Mais poderoso (requer 16GB RAM)",
    }

    def __init__(self, model: str = "", base_url: str | None = None, pull_model: bool = True, llm_engine: LLMEngine | None = None):
        if not model:
            model = os.getenv("LAURA_LLM_MODEL", "tinyllama")
        """
        Inicializa o analisador Ollama.
        
        Args:
            model: Modelo a usar (default: tinyllama)
            base_url: URL do Ollama (default: lê LAURA_OLLAMA_HOST ou http://127.0.0.1:11434)
        
        Raises:
            RuntimeError: Se Ollama não estiver disponível
        """
        if base_url is None:
            base_url = os.getenv("LAURA_OLLAMA_HOST", "http://127.0.0.1:11434")
        # Ensure base_url includes a port; default to 11434 for Ollama
        if "://" in base_url:
            scheme, rest = base_url.split("://", 1)
            if ":" not in rest:
                base_url = f"{scheme}://{rest}:11434"
        elif ":" not in base_url:
            base_url = f"http://{base_url}:11434"
        info("Initializing LLM analyzer", model=model, base_url=base_url)
        self.model = model
        self.base_url = base_url
        self.request_timeout_seconds = int(os.getenv("LAURA_LLM_REQUEST_TIMEOUT_SECONDS", "60"))  # Increased from 15 to 60
        self._llm_engine = llm_engine or _llm_engine

        if not check_ollama_running():
            debug("Ollama not running, attempting to start")
            if not start_ollama_if_needed(model):
                log_error("Ollama initialization failed", model=model, base_url=base_url)
                raise RuntimeError(
                    f"Ollama não está rodando em {base_url}. "
                    f"Instale: curl -fsSL https://ollama.ai/install.sh | sh"
                )

        debug("Ollama is running", model=model)

        # Verificar se modelo está disponível
        if pull_model and not self._check_model_available():
            print(f"📥 Baixando modelo {model}... (primeira vez, pode demorar)")
            self._pull_model()

    def _check_model_available(self) -> bool:
        """Verifica se o modelo está disponível localmente."""
        try:
            import requests
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = [m["name"].split(":")[0] for m in resp.json().get("models", [])]
                return self.model.split(":")[0] in models
        except Exception:
            pass
        return False

    def _is_model_warm(self) -> bool:
        """Verifica se o modelo já está carregado em RAM via /api/ps."""
        try:
            import requests

            resp = requests.get(f"{self.base_url}/api/ps", timeout=3)
            if resp.status_code != 200:
                return False

            models = resp.json().get("models", [])
            model_name = self.model.split(":")[0]
            for item in models:
                if not isinstance(item, dict):
                    continue
                loaded_name = str(item.get("name", ""))
                if model_name and model_name in loaded_name:
                    return True
        except Exception:
            pass
        return False

    def _check_model_loaded(self) -> bool:
        """Compatibility wrapper expected by tests: return True if model is loaded in RAM."""
        return self._is_model_warm()

    def _fail_fast_if_unloaded(self, fallback_on_error: bool, metrics: dict[str, Any], prompt_type: str, max_tokens: int) -> LLMAnalysisResult | dict[str, Any] | None:
        if not self._check_model_available():
            warning(
                "Ollama model not available via /api/tags; returning immediate fallback",
                model=self.model,
                prompt_type=prompt_type,
            )
            if not fallback_on_error:
                raise RuntimeError(
                    f"Modelo Ollama '{self.model}' não está disponível em /api/tags. Verifique `ollama list` e `ollama run {self.model}`."
                )
            if prompt_type == "profitability_analyzer":
                return self._heuristic_fallback(
                    metrics=metrics,
                    prompt_type=prompt_type,
                    error_reason=f"Modelo Ollama '{self.model}' não disponível em /api/tags; rode `ollama run {self.model}` antes de analisar.",
                    elapsed_ms=0,
                )
            return self._heuristic_fallback_dict(
                metrics=metrics,
                prompt_type=prompt_type,
                error_reason=f"Modelo Ollama '{self.model}' não disponível em /api/tags; rode `ollama run {self.model}` antes de analisar.",
                elapsed_ms=0,
            )

        # Model is available; do not fall back just because it's not warm in RAM.
        # The inference request will load the model automatically.
        return None

    def _pull_model(self) -> None:
        """Baixa o modelo se não estiver disponível."""
        try:
            import requests
            requests.post(f"{self.base_url}/api/pull", json={"name": self.model}, timeout=3600)
        except Exception as e:
            raise RuntimeError(f"Erro ao baixar modelo: {e}")

    def embed_text(self, text: str, dim: int = 128, timeout: int = 15) -> list[float] | None:
        """Attempt to produce a numeric embedding for `text` by invoking the
        local Ollama model via the `ollama run` CLI. Returns a list of floats or
        None on failure.

        This is a best-effort helper: models may not be configured to return
        embeddings, so callers should gracefully fallback when None is returned.
        """
        try:
            import subprocess

            prompt = (
                "Por favor retorne apenas um vetor JSON (array) de '" + str(dim) +
                "' números de ponto flutuante no intervalo [-1,1] que represente\n" +
                "o embedding do texto a seguir:\n\n" + text
            )
            proc = subprocess.run(
                ["ollama", "run", self.model, prompt],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            out = proc.stdout.strip()
            if not out:
                out = proc.stderr.strip()

            candidate = _extract_json_object(out) or out
            if not candidate:
                return None

            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, list) and all(isinstance(x, (int, float)) for x in parsed):
                    vals = [float(x) for x in parsed]
                    if len(vals) > dim:
                        return vals[:dim]
                    if len(vals) < dim:
                        return vals + [0.0] * (dim - len(vals))
                    return vals
            except Exception:
                import re

                nums = re.findall(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", candidate)
                if nums:
                    vals = [float(n) for n in nums]
                    if len(vals) >= dim:
                        return vals[:dim]
                    return vals + [0.0] * (dim - len(vals))

            return None
        except Exception:
            return None

    def analyze_profitability(
        self,
        metrics: dict[str, Any],
        prompt_type: str = "profitability_analyzer",
        max_tokens: int = 256,
        fallback_on_error: bool = True,
    ) -> LLMAnalysisResult:
        """
        Analisa métricas de profitabilidade usando Ollama.
        
        Args:
            metrics: Dicionário com métricas
            prompt_type: Tipo de análise
            max_tokens: Limite de tokens na resposta
        
        Returns:
            LLMAnalysisResult com decisão estruturada
        """
        import requests

        debug("Starting profitability analysis", model=self.model, prompt_type=prompt_type)
        narrador.pensando(
            "Analisando dados da loja com LLM...",
            detalhe=f"Modelo: `{self.model}` | Prompt: `{prompt_type}`",
        )

        # Validar métricas
        required_fields = ["revenue", "cogs", "ad_spend", "shipping_subsidy", "refunds", "orders"]
        missing = [f for f in required_fields if f not in metrics]
        if missing:
            log_error("Missing metrics", missing_fields=missing)
            raise ValueError(f"Métricas incompletas. Faltam: {missing}")

        fast_fallback = self._fail_fast_if_unloaded(fallback_on_error, metrics, prompt_type, max_tokens)
        if fast_fallback is not None:
            narrador.alerta(
                "LLM caiu no fallback heurístico",
                detalhe=f"Modelo `{self.model}` não estava carregado em RAM.",
            )
            return fast_fallback  # type: ignore[return-value]

        # Try LLMEngine first (if available)
        if self._llm_engine is not None:
            try:
                engine_result = self._llm_engine.analyze(prompt_type, metrics)
                if "_llm" in engine_result:
                    inference_time = int(engine_result.get("_llm", {}).get("latency_ms", 0))
                    result = LLMAnalysisResult(
                        decision=engine_result.get("decision", ""),
                        action=engine_result.get("action", ""),
                        priority=engine_result.get("priority", ""),
                        mode=engine_result.get("mode", ""),
                        metrics=engine_result.get("metrics", {}),
                        reasoning=engine_result.get("reasoning", ""),
                        next_steps=engine_result.get("next_steps", ""),
                        confidence=float(engine_result.get("confidence", 0.0)),
                        timestamp=datetime.now(UTC).isoformat(),
                        raw_response=json.dumps(engine_result, ensure_ascii=False),
                        model=engine_result.get("_llm", {}).get("model", self.model),
                        prompt_type=prompt_type,
                        inference_time_ms=inference_time,
                    )
                    narrador.llm_resultado(
                        modelo=result.model,
                        decisao=result.decision,
                        confianca=float(result.confidence),
                        raciocinio=result.reasoning,
                        fallback=False,
                    )
                    debug("Profitability analysis completed (LLMEngine)", model=result.model, inference_ms=inference_time, decision=result.decision)
                    return result
            except Exception:
                debug("LLMEngine failed, falling back to direct Ollama call")

        # Fall back to direct Ollama HTTP call
        # Preparar prompts
        system_prompt = get_system_prompt(prompt_type)
        user_message = self._build_user_message(metrics, prompt_type)

        # Chamar Ollama
        start_time = time.time()
        try:
            payload = {
                "model": self.model,
                "prompt": f"{system_prompt}\n\n{user_message}",
                "stream": False,
                "format": "json",
                "temperature": 0.3,
                "num_predict": max_tokens,
            }

            def _do_request() -> Any:
                return requests.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=(10, self.request_timeout_seconds),
                )

            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(_do_request)
            try:
                response = future.result(timeout=self.request_timeout_seconds + 5)
            except FutureTimeoutError:
                future.cancel()
                executor.shutdown(wait=False, cancel_futures=True)
                raise
            finally:
                if not future.done():
                    executor.shutdown(wait=False, cancel_futures=True)
                else:
                    executor.shutdown(wait=False)

            response.raise_for_status()
        except FutureTimeoutError as e:
            elapsed = int((time.time() - start_time) * 1000)
            warning(
                "LLM request timeout",
                model=self.model,
                timeout_seconds=self.request_timeout_seconds,
                elapsed_ms=elapsed,
            )
            if not fallback_on_error:
                raise RuntimeError(
                    f"Erro ao chamar Ollama: timeout absoluto de {self.request_timeout_seconds}s"
                ) from e
            return self._heuristic_fallback(
                metrics=metrics,
                prompt_type=prompt_type,
                error_reason=(
                    f"Timeout absoluto de inferencia ({self.request_timeout_seconds}s)"
                ),
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = int((time.time() - start_time) * 1000)
            log_error(
                "LLM request error",
                model=self.model,
                elapsed_ms=elapsed,
                error=str(e)[:200],
            )
            if not fallback_on_error:
                raise RuntimeError(f"Erro ao chamar Ollama: {e}")
            return self._heuristic_fallback(
                metrics=metrics,
                prompt_type=prompt_type,
                error_reason=f"Erro ao chamar Ollama: {e}",
                elapsed_ms=elapsed,
            )

        inference_time = int((time.time() - start_time) * 1000)

        # Extrair resposta
        data = response.json()
        raw_response = data.get("response", "")

        # Parsear resultado
        try:
            result = self._parse_response(raw_response, prompt_type)
        except Exception as e:
            if not fallback_on_error:
                raise
            return self._heuristic_fallback(
                metrics=metrics,
                prompt_type=prompt_type,
                error_reason=f"Falha ao parsear resposta LLM: {e}",
                elapsed_ms=inference_time,
                raw_response=raw_response,
            )
        result.raw_response = raw_response
        result.model = self.model
        result.prompt_type = prompt_type
        result.timestamp = datetime.now(UTC).isoformat()
        result.inference_time_ms = inference_time

        narrador.llm_resultado(
            modelo=result.model,
            decisao=result.decision,
            confianca=float(result.confidence),
            raciocinio=result.reasoning,
            fallback=False,
        )

        debug("Profitability analysis completed", model=self.model, inference_ms=inference_time, decision=result.decision)
        return result

    def analyze(
        self,
        metrics: dict[str, Any],
        prompt_type: str = "general_agent",
        max_tokens: int = 256,
        fallback_on_error: bool = True,
    ) -> dict[str, Any]:
        """
        Genérico analyze method que suporta qualquer tipo de prompt.
        
        Args:
            metrics: Dicionário com dados da loja (orders_count, products_count, etc)
            prompt_type: Tipo de análise (general_agent, triage, product_diagnosis, daily_report)
            max_tokens: Limite de tokens na resposta
            fallback_on_error: Se True, retorna fallback heurístico em caso de erro
        
        Returns:
            Dicionário com resultado da análise
        """
        import requests

        debug("Starting analysis", model=self.model, prompt_type=prompt_type)
        narrador.pensando(
            "Analisando dados da loja com LLM...",
            detalhe=f"Modelo: `{self.model}` | Prompt: `{prompt_type}`",
        )

        fast_fallback = self._fail_fast_if_unloaded(fallback_on_error, metrics, prompt_type, max_tokens)
        if fast_fallback is not None:
            narrador.alerta(
                "LLM caiu no fallback heurístico",
                detalhe=f"Modelo `{self.model}` não estava carregado em RAM.",
            )
            return fast_fallback

        # Try LLMEngine first (if available)
        if self._llm_engine is not None:
            try:
                engine_result = self._llm_engine.analyze(prompt_type, metrics)
                if "_llm" in engine_result:
                    inference_time = int(engine_result.get("_llm", {}).get("latency_ms", 0))
                    engine_result["model"] = self.model
                    engine_result["prompt_type"] = prompt_type
                    engine_result["timestamp"] = datetime.now(UTC).isoformat()
                    engine_result["inference_time_ms"] = inference_time
                    engine_result["raw_response"] = json.dumps(engine_result, ensure_ascii=False)

                    narrador.llm_resultado(
                        modelo=engine_result.get("model", self.model),
                        decisao=str(engine_result.get("decision", engine_result.get("action", "?"))),
                        confianca=float(engine_result.get("confidence", 0.0) or 0.0),
                        raciocinio=str(engine_result.get("reasoning", "")),
                        fallback=False,
                    )

                    debug("Analysis completed (LLMEngine)", model=self.model, inference_ms=inference_time)
                    return engine_result
            except Exception:
                debug("LLMEngine failed, falling back to direct Ollama call")

        # Fall back to direct Ollama HTTP call
        # Preparar prompts
        system_prompt = get_system_prompt(prompt_type)
        user_message = json.dumps(metrics, ensure_ascii=False, indent=2)

        # Chamar Ollama
        start_time = time.time()
        try:
            payload = {
                "model": self.model,
                "prompt": f"{system_prompt}\n\nDados da loja:\n{user_message}",
                "stream": False,
                "format": "json",
                "temperature": 0.3,
                "num_predict": max_tokens,
            }

            def _do_request() -> Any:
                return requests.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=(10, self.request_timeout_seconds),
                )

            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(_do_request)
            try:
                response = future.result(timeout=self.request_timeout_seconds + 5)
            except FutureTimeoutError:
                future.cancel()
                executor.shutdown(wait=False, cancel_futures=True)
                raise
            finally:
                if not future.done():
                    executor.shutdown(wait=False, cancel_futures=True)
                else:
                    executor.shutdown(wait=False)

            response.raise_for_status()
        except FutureTimeoutError as e:
            elapsed = int((time.time() - start_time) * 1000)
            warning("LLM request timeout", model=self.model, timeout_seconds=self.request_timeout_seconds, elapsed_ms=elapsed)
            if not fallback_on_error:
                raise RuntimeError(f"LLM timeout after {self.request_timeout_seconds}s") from e
            return self._heuristic_fallback_dict(
                metrics=metrics,
                prompt_type=prompt_type,
                error_reason=f"Timeout absoluto de inferencia ({self.request_timeout_seconds}s)",
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = int((time.time() - start_time) * 1000)
            log_error("LLM request error", model=self.model, elapsed_ms=elapsed, error=str(e)[:200])
            if not fallback_on_error:
                raise RuntimeError(f"LLM error: {e}")
            return self._heuristic_fallback_dict(
                metrics=metrics,
                prompt_type=prompt_type,
                error_reason=f"Erro ao chamar Ollama: {e}",
                elapsed_ms=elapsed,
            )

        inference_time = int((time.time() - start_time) * 1000)

        # Extrair resposta
        data = response.json()
        raw_response = data.get("response", "")

        # Parsear resultado
        try:
            result = self._parse_response_json(raw_response)
        except Exception as e:
            info("LLM response parsing failed", error=str(e)[:100], raw_response_sample=raw_response[:100])
            if not fallback_on_error:
                raise
            return self._heuristic_fallback_dict(
                metrics=metrics,
                prompt_type=prompt_type,
                error_reason=f"Falha ao parsear resposta LLM: {e}",
                elapsed_ms=inference_time,
                raw_response=raw_response,
            )

        result["model"] = self.model
        result["prompt_type"] = prompt_type
        result["timestamp"] = datetime.now(UTC).isoformat()
        result["inference_time_ms"] = inference_time
        result["raw_response"] = raw_response

        narrador.llm_resultado(
            modelo=result.get("model", self.model),
            decisao=str(result.get("decision", result.get("action", "?"))),
            confianca=float(result.get("confidence", 0.0) or 0.0),
            raciocinio=str(result.get("reasoning", "")),
            fallback="fallback" in str(result.get("model", "")).lower(),
        )

        debug("Analysis completed", model=self.model, inference_ms=inference_time)
        return result

    def _build_user_message(self, metrics: dict[str, Any], prompt_type: str) -> str:
        """Constrói mensagem do usuário formatada."""
        revenue = metrics.get("revenue", 0)
        cogs = metrics.get("cogs", 0)
        ad_spend = metrics.get("ad_spend", 0)
        shipping_subsidy = metrics.get("shipping_subsidy", 0)
        refunds = metrics.get("refunds", 0)
        orders = metrics.get("orders", 0)

        gross_profit = revenue - cogs - ad_spend - shipping_subsidy - refunds
        margin_pct = (gross_profit / revenue * 100) if revenue > 0 else 0
        roas = (revenue / ad_spend) if ad_spend > 0 else 0
        refund_rate = (refunds / revenue * 100) if revenue > 0 else 0

        vision_context = metrics.get("vision_context", "")
        vision_section = f"""
## Análise Visual dos Produtos
{vision_context}
""" if vision_context else ""

        return f"""
# Dados de Entrada

## Período
Data/hora: {datetime.now(UTC).isoformat()}

## Métricas Financeiras (últimos 7 dias)
- Receita Total: R$ {revenue:,.2f}
- COGS: R$ {cogs:,.2f}
- Gastos em Publicidade: R$ {ad_spend:,.2f}
- Subsídio de Frete: R$ {shipping_subsidy:,.2f}
- Reembolsos: R$ {refunds:,.2f}
- Lucro Bruto: R$ {gross_profit:,.2f}

## Métricas Calculadas
- Margem de Lucro: {margin_pct:.1f}%
- ROAS: {roas:.2f}x
- Taxa de Reembolsos: {refund_rate:.1f}%
- Volume de Pedidos: {orders} pedidos
{vision_section}
---

Por favor, analise os dados e forneça uma decisão estruturada em JSON.
"""

    def _parse_response_json(self, raw_response: str) -> dict[str, Any]:
        """Parseia resposta extraindo JSON com fallback robusto."""
        json_str = _extract_json_object(raw_response)
        if json_str is None:
            raise ValueError(f"Falha ao parsear resposta JSON: nenhum JSON encontrado. Resposta: {raw_response[:200]}")

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Falha ao parsear resposta JSON: {e}. Resposta: {raw_response[:200]}")

    def _parse_response(self, raw_response: str, prompt_type: str) -> LLMAnalysisResult:
        """Parseia a resposta extraindo JSON."""
        json_str = _extract_json_object(raw_response)
        if json_str is None:
            raise ValueError("Falha ao parsear resposta JSON: nenhum JSON encontrado")

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Falha ao parsear resposta JSON: {e}")

        # Validar campos
        required_fields = ["decision", "action", "priority", "mode", "metrics", "reasoning", "next_steps", "confidence"]
        missing = [f for f in required_fields if f not in data]
        if missing:
            raise ValueError(f"Resposta incompleta. Faltam: {missing}")

        return LLMAnalysisResult(
            decision=data.get("decision", ""),
            action=data.get("action", ""),
            priority=data.get("priority", ""),
            mode=data.get("mode", ""),
            metrics=data.get("metrics", {}),
            reasoning=data.get("reasoning", ""),
            next_steps=data.get("next_steps", ""),
            confidence=float(data.get("confidence", 0.0)),
            timestamp=data.get("timestamp", datetime.now(UTC).isoformat()),
            raw_response="",
            model="",
            prompt_type=prompt_type,
        )

    def _heuristic_fallback_dict(
        self,
        *,
        metrics: dict[str, Any],
        prompt_type: str,
        error_reason: str,
        elapsed_ms: int,
        raw_response: str = "",
    ) -> dict[str, Any]:
        """Fallback heurístico retorna dict em vez de LLMAnalysisResult."""
        return {
            "decision": "MONITOR_ONLY",
            "action": "monitor_only",
            "priority": "MEDIUM",
            "mode": "dry_run",
            "metrics": {
                "orders_count": metrics.get("orders_count", 0),
                "products_count": metrics.get("products_count", 0),
            },
            "shop_status": "Fallback mode - LLM unavailable",
            "alerts": [f"Fallback: {error_reason}"],
            "top_action": "Maintain current operations and retry LLM analysis when service recovers",
            "reasoning": f"Heurístico fallback mode ativado. Motivo: {error_reason}",
            "confidence": 0.30,
            "timestamp": datetime.now(UTC).isoformat(),
            "model": f"{self.model} (fallback)",
            "prompt_type": prompt_type,
            "inference_time_ms": elapsed_ms,
            "raw_response": raw_response,
        }

    def _heuristic_fallback(
        self,
        *,
        metrics: dict[str, Any],
        prompt_type: str,
        error_reason: str,
        elapsed_ms: int,
        raw_response: str = "",
    ) -> LLMAnalysisResult:
        """Fallback deterministico para manter operacao mesmo sem resposta do Ollama."""
        revenue = float(metrics.get("revenue", 0.0) or 0.0)
        cogs = float(metrics.get("cogs", 0.0) or 0.0)
        ad_spend = float(metrics.get("ad_spend", 0.0) or 0.0)
        shipping_subsidy = float(metrics.get("shipping_subsidy", 0.0) or 0.0)
        refunds = float(metrics.get("refunds", 0.0) or 0.0)
        orders = float(metrics.get("orders", 0.0) or 0.0)

        gross_profit = revenue - cogs - ad_spend - shipping_subsidy - refunds
        margin_pct = (gross_profit / revenue * 100.0) if revenue > 0 else 0.0
        roas = (revenue / ad_spend) if ad_spend > 0 else 0.0
        refund_rate = (refunds / revenue * 100.0) if revenue > 0 else 0.0

        # Mesma hierarquia operacional usada no prompt principal.
        if margin_pct < 5.0:
            decision, action, priority = "PROTECT_MARGIN", "protect_margin", "CRITICAL"
            reason = "Fallback heuristico: margem critica abaixo de 5%."
        elif refund_rate > 5.0:
            decision, action, priority = "REFUND_GUARD", "refund_guard", "CRITICAL"
            reason = "Fallback heuristico: taxa de reembolso acima de 5%."
        elif roas < 1.0 and ad_spend > 0:
            decision, action, priority = "PAUSE_LOW_ROAS_ADS", "pause_low_roas_ads", "CRITICAL"
            reason = "Fallback heuristico: ROAS abaixo de 1x."
        elif margin_pct >= 20.0 and roas >= 3.0 and refund_rate < 3.0 and orders >= 10:
            decision, action, priority = "SCALE_WINNERS", "scale_winners", "LOW"
            reason = "Fallback heuristico: sinais saudaveis para escala."
        else:
            decision, action, priority = "MONITOR_ONLY", "monitor_only", "MEDIUM"
            reason = "Fallback heuristico: sinais mistos ou volume insuficiente."

        narrador.alerta("LLM caiu no fallback heurístico", detalhe=reason)

        return LLMAnalysisResult(
            decision=decision,
            action=action,
            priority=priority,
            mode="dry_run",
            metrics={
                "margin_pct": round(margin_pct, 4),
                "roas": round(roas, 4),
                "refund_rate_pct": round(refund_rate, 4),
                "order_volume": round(orders, 4),
            },
            reasoning=(
                f"{reason} Motivo tecnico: {error_reason}"
            ),
            next_steps=(
                "1) Verificar status do Ollama e recursos da maquina. "
                "2) Reexecutar analise quando o modelo responder. "
                "3) Manter monitoramento em dry_run ate estabilizar."
            ),
            confidence=0.45,
            timestamp=datetime.now(UTC).isoformat(),
            raw_response=raw_response,
            model=f"{self.model} (fallback)",
            prompt_type=prompt_type,
            inference_time_ms=elapsed_ms,
        )

    def to_dict(self, result: LLMAnalysisResult) -> dict[str, Any]:
        """Converte resultado para dicionário."""
        if isinstance(result, dict):
            return result
        return asdict(result)


def create_analyzer(model: str = "tinyllama") -> LauraOllamaAnalyzer:
    return LauraOllamaAnalyzer(model=model)


def ask_local(prompt: str, max_tokens: int = 300, model: str = "") -> str | dict:
    """
    Funcao simples para fazer perguntas ao LLM local (Ollama).
    Usada pelo telegram_bot para responder perguntas do usuario.

    Detecta se o prompt contem um system prompt (separado por \n\n) e usa
    /api/chat nesse caso, que tem melhor aderencia a instrucoes.

    Args:
        prompt: Texto completo do prompt
        max_tokens: Maximo de tokens na resposta
        model: Modelo (padrao: LAURA_LLM_MODEL ou qwen2.5:7b)

    Returns:
        str com o texto da resposta, ou dict se houve erro
    """
    import requests as _req
    _model = model or os.getenv("LAURA_LLM_MODEL", "qwen2.5:7b")

    # Try LLMEngine first
    try:
        _parts = prompt.split("\n\n", 1)
        if len(_parts) > 1 and len(_parts[0]) > 50:
            messages = [
                {"role": "system", "content": _parts[0]},
                {"role": "user", "content": _parts[1]},
            ]
        else:
            messages = [{"role": "user", "content": prompt}]
        cfg = LLMConfig(model=_model, max_tokens=max_tokens, temperature=0.1)
        response = _llm_engine.chat(messages, cfg)
        if response.success and response.text.strip():
            return response.text.strip()
    except Exception:
        pass

    # Fall back to direct HTTP calls
    _host = os.getenv("LAURA_OLLAMA_HOST", "http://127.0.0.1:11434")
    try:
        # Detecta se tem system prompt (separador \n\n entre instrucao e contexto)
        _parts = prompt.split("\n\n", 1)
        if len(_parts) > 1 and len(_parts[0]) > 50:
            # Usar /api/chat com system + user para melhor aderencia
            _payload = {
                "model": _model,
                "messages": [
                    {"role": "system", "content": _parts[0]},
                    {"role": "user", "content": _parts[1]},
                ],
                "stream": False,
                "format": "json",
                "options": {"num_predict": max_tokens, "temperature": 0.1},
            }
            _resp = _req.post(f"{_host}/api/chat", json=_payload, timeout=60)
            if _resp.status_code == 200:
                _text = _resp.json().get("message", {}).get("content", "")
                if _text.strip():
                    return _text.strip()
        # Fallback para /api/generate
        _resp = _req.post(
            f"{_host}/api/generate",
            json={"model": _model, "prompt": prompt, "stream": False, "format": "json", "options": {"num_predict": max_tokens, "temperature": 0.1}},
            timeout=60,
        )
        if _resp.status_code == 200:
            _text = _resp.json().get("response", "")
            return _text.strip()
        return {"error": f"HTTP {_resp.status_code}", "text": ""}
    except Exception as _e:
        return {"error": str(_e), "text": ""}
