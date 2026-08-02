"""
Modulo de visao computacional via Ollama.

Usa modelos multimodais (moondream, llava) para:
- OCR: extrair texto de imagens
- Analisar: descrever e interpretar imagens
- Comparar: verificar se imagem corresponde a descricao de produto

CLI usage:
    laura vision ocr <image_path>
    laura vision describe <image_path>
    laura vision analyze <image_path> --product "name"
    laura vision match <image_path> --product "name"
    laura vision batch <dir> --task describe
    laura vision compare <img_a> <img_b>
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import requests

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
VISION_MODEL = os.getenv("LAURA_VISION_MODEL", "moondream")
TEMP_DIR = Path(tempfile.gettempdir()) / "laura_vision"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "reports"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE = CACHE_DIR / "vision_cache.json"


# ------------------------------------------------------------------ #
# Internal helpers
# ------------------------------------------------------------------ #

def _cache_load() -> dict[str, Any]:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _cache_save(data: dict[str, Any]) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _cache_key(image_path: str | Path, prompt: str) -> str:
    raw = str(Path(image_path).resolve()) + "::" + prompt
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_get(image_path: str | Path, prompt: str) -> str | None:
    cache = _cache_load()
    return cache.get(_cache_key(image_path, prompt))


def _cache_set(image_path: str | Path, prompt: str, result: str) -> None:
    cache = _cache_load()
    cache[_cache_key(image_path, prompt)] = result
    _cache_save(cache)


def _imagem_para_base64(caminho_ou_url: str | Path) -> str:
    """Converte imagem local para base64."""
    path = Path(caminho_ou_url)
    if not path.exists():
        raise FileNotFoundError(f"Imagem nao encontrada: {path}")
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _chamar_ollama(mensagens: list[dict], modelo: str | None = None) -> str:
    """Chama Ollama API e retorna resposta de texto.

    Usa /api/generate para modelos de visao (moondream, llava, etc)
    que podem nao suportar /api/chat com imagens.
    """
    model = modelo or VISION_MODEL

    ultima = mensagens[-1] if mensagens else {}
    prompt = str(ultima.get("content", ""))
    imagens = ultima.get("images", [])

    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if imagens:
        payload["images"] = imagens

    try:
        r = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json=payload,
            timeout=300,
        )
        r.raise_for_status()
        return r.json().get("response", "")
    except requests.exceptions.ConnectionError:
        return f"[ERRO] Nao foi possivel conectar ao Ollama em {OLLAMA_HOST}. Verifique se o servidor esta rodando."
    except requests.exceptions.Timeout:
        return "[ERRO] Ollama nao respondeu em 300s. Tente um modelo menor ou verifique o servidor."
    except requests.exceptions.RequestException as e:
        return f"[ERRO] Falha ao chamar Ollama: {e}"
    except (json.JSONDecodeError, KeyError) as e:
        return f"[ERRO] Resposta inesperada do Ollama: {e}"


# ------------------------------------------------------------------ #
# LauraVision class
# ------------------------------------------------------------------ #

class LauraVision:
    """Vision agent powered by Ollama multimodal models."""

    def __init__(self, model: str | None = None):
        self.model = model or os.getenv("LAURA_VISION_MODEL", "moondream")

    # --- low-level ---

    def _call(self, prompt: str, image_path: str | Path) -> str:
        path = Path(image_path)
        if not path.exists():
            return f"[ERRO] Imagem nao encontrada: {path}"
        cached = _cache_get(image_path, prompt)
        if cached is not None:
            return cached
        img_b64 = _imagem_para_base64(image_path)
        result = _chamar_ollama(
            [{"role": "user", "content": prompt, "images": [img_b64]}],
            modelo=self.model,
        )
        _cache_set(image_path, prompt, result)
        return result

    # --- OCR ---

    def ocr(self, image_path: str | Path) -> str:
        """Extract text from an image."""
        return self._call(
            "Read the text in this image. What does it say?",
            image_path,
        )

    # --- Describe ---

    def describe(self, image_path: str | Path) -> str:
        """Describe an image in natural language."""
        return self._call(
            "Describe this image in detail. What product is shown, what text is visible, what is the condition?",
            image_path,
        )

    def descrever(self, image_path: str | Path) -> str:
        """Alias portugues para describe()."""
        return self.describe(image_path)

    # --- Complaint analysis ---

    def analyze_complaint(
        self,
        image_path: str | Path,
        product_description: str,
        variation: str = "",
    ) -> dict[str, Any]:
        """Analyze a product complaint image.

        Returns:
            dict with keys: corresponde, analise, texto_extraido, precisa_atencao
        """
        path = Path(image_path)
        if not path.exists():
            return {
                "corresponde": "erro",
                "analise": f"[ERRO] Imagem nao encontrada: {path}",
                "texto_extraido": "",
                "precisa_atencao": True,
            }

        prompt = (
            f"I am a customer support agent. The customer ordered: {product_description}"
        )
        if variation:
            prompt += f" (variant: {variation})"
        prompt += (
            ".\n\nLook at the photo the customer sent. "
            "Does the product in the photo match what was ordered? "
            "Read any visible text. Is the product damaged?\n\n"
            "Answer concisely in Portuguese."
        )
        resposta = self._call(prompt, image_path)

        texto_extraido = self._call(
            "Read the text in this image. What does it say?",
            image_path,
        )

        corresponde = "nao_analisado"
        resp_lower = resposta.lower()
        if any(w in resp_lower for w in ["correto", "match", "igual", "mesmo", "sim"]):
            corresponde = "sim"
        elif any(w in resp_lower for w in ["diferente", "errado", "outro", "nao", "no", "not"]):
            corresponde = "nao"

        return {
            "corresponde": corresponde,
            "analise": resposta,
            "texto_extraido": texto_extraido,
            "precisa_atencao": corresponde == "nao" or any(
                w in resp_lower for w in ["danificado", "quebrado", "avariado", "defeito", "rasgado"]
            ),
        }

    def analisar_reclamacao(
        self,
        image_path: str | Path,
        produto_comprado: str,
        variacao: str = "",
    ) -> dict[str, Any]:
        """Alias portugues para analyze_complaint()."""
        return self.analyze_complaint(image_path, produto_comprado, variacao)

    # --- Product matching ---

    def match_product(self, image_path: str | Path, product_name: str) -> dict[str, Any]:
        """Check if image matches a product description.

        Returns:
            dict with keys: match (bool), confidence (float), reason (str)
        """
        desc = self.describe(image_path)
        ocr_text = self.ocr(image_path)
        combined = f"{desc}\n{ocr_text}".lower()
        query = product_name.lower()
        words = query.split()
        matched = sum(1 for w in words if w in combined)
        confidence = matched / len(words) if words else 0.0
        return {
            "match": confidence >= 0.3,
            "confidence": round(confidence, 3),
            "reason": f"{matched}/{len(words)} keywords matched" if words else "No keywords to match",
        }

    def produto_por_imagem(self, image_path: str | Path) -> dict[str, Any]:
        """Identifica produto atraves de foto."""
        texto = self.ocr(image_path)
        desc = self.describe(image_path)
        return {
            "texto_extraido": texto,
            "descricao": desc,
            "possivel_produto": texto[:200] if texto else desc[:200],
        }

    # --- Batch ---

    def batch_process(
        self,
        image_paths: list[str | Path],
        task: str = "describe",
    ) -> list[dict[str, Any]]:
        """Process multiple images in batch."""
        results: list[dict[str, Any]] = []
        task_map = {
            "ocr": self.ocr,
            "describe": self.describe,
            "descrever": self.descrever,
        }
        fn = task_map.get(task)
        if fn is None:
            return [{"path": str(p), "error": f"Unknown task: {task}"} for p in image_paths]

        for path in image_paths:
            path = Path(path)
            entry: dict[str, Any] = {"path": str(path)}
            try:
                result = fn(path)
                if isinstance(result, str):
                    entry["result"] = result
                else:
                    entry.update(result)
            except Exception as e:
                entry["error"] = str(e)
            results.append(entry)

        return results

    # --- Compare ---

    def compare_images(self, image_a: str | Path, image_b: str | Path) -> dict[str, Any]:
        """Compare two images and return similarity assessment."""
        for name, p in [("image_a", image_a), ("image_b", image_b)]:
            if not Path(p).exists():
                return {"error": f"{name} nao encontrada: {p}", "similar": None}

        desc_a = self.describe(image_a)
        desc_b = self.describe(image_b)

        prompt = (
            f"Compare these two image descriptions and assess how similar the images are.\n\n"
            f"IMAGE A: {desc_a}\n\n"
            f"IMAGE B: {desc_b}\n\n"
            f"On a scale of 0.0 to 1.0, how similar are they? Respond with a JSON object: "
            f'{{"similarity_score": 0.0-1.0, "reason": "..."}}'
        )
        # Use a dummy path — we just want the LLM comparison, no new image
        compare_img_b64 = _imagem_para_base64(image_a)
        compare_result = _chamar_ollama([
            {"role": "user", "content": prompt, "images": [compare_img_b64]},
        ], modelo=self.model)

        try:
            parsed = json.loads(compare_result)
            return {
                "similarity_score": float(parsed.get("similarity_score", 0.0)),
                "reason": parsed.get("reason", compare_result),
                "description_a": desc_a,
                "description_b": desc_b,
            }
        except (json.JSONDecodeError, ValueError, TypeError):
            return {
                "similarity_score": 0.0,
                "reason": compare_result,
                "description_a": desc_a,
                "description_b": desc_b,
            }

    # --- Extract table ---

    def extract_table(self, image_path: str | Path) -> list[list[str]]:
        """Extract tabular data from an image (e.g. screenshots of spreadsheets)."""
        prompt = (
            "This image contains a table or spreadsheet. "
            "Extract all data as a JSON array of rows, where each row is an array of cell values. "
            "Respond ONLY with valid JSON, no other text."
        )
        raw = self._call(prompt, image_path)
        try:
            data = json.loads(raw)
            if isinstance(data, list) and all(isinstance(r, list) for r in data):
                return [[str(c) for c in row] for row in data]
            return [["erro: resposta inesperada", raw[:200]]]
        except json.JSONDecodeError:
            return [["erro: nao foi possivel interpretar tabela", raw[:200]]]


# ------------------------------------------------------------------ #
# Module-level singleton instance
# ------------------------------------------------------------------ #

_vision = LauraVision()


# ------------------------------------------------------------------ #
# Module-level functions (backward-compatible wrappers)
# ------------------------------------------------------------------ #

def ocr(imagem_path: str | Path) -> str:
    """Extrai texto de uma imagem usando modelo de visao."""
    return _vision.ocr(imagem_path)


def descrever(imagem_path: str | Path) -> str:
    """Descreve o conteudo de uma imagem em detalhes."""
    return _vision.descrever(imagem_path)


def analisar_reclamacao(
    imagem_path: str | Path,
    produto_comprado: str,
    variacao: str = "",
) -> dict:
    """Analisa foto de reclamacao de cliente."""
    return _vision.analisar_reclamacao(imagem_path, produto_comprado, variacao)


def produto_por_imagem(imagem_path: str | Path) -> dict:
    """Identifica produto atraves de foto."""
    return _vision.produto_por_imagem(imagem_path)


# ------------------------------------------------------------------ #
# CLI
# ------------------------------------------------------------------ #

def build_parser(subparsers) -> None:
    """Build CLI subparsers for vision commands."""
    vision_parser = subparsers.add_parser("vision", help="Vision / image analysis commands")
    vision_sub = vision_parser.add_subparsers(dest="vision_command", required=True)

    # ocr
    p_ocr = vision_sub.add_parser("ocr", help="Extract text from an image")
    p_ocr.add_argument("image_path", help="Path to the image file")

    # describe
    p_describe = vision_sub.add_parser("describe", help="Describe an image in natural language")
    p_describe.add_argument("image_path", help="Path to the image file")

    # analyze
    p_analyze = vision_sub.add_parser("analyze", help="Analyze a product complaint image")
    p_analyze.add_argument("image_path", help="Path to the image file")
    p_analyze.add_argument("--product", "-p", required=True, help="Product description / name")
    p_analyze.add_argument("--variation", "-v", default="", help="Product variation")

    # match
    p_match = vision_sub.add_parser("match", help="Check if image matches a product description")
    p_match.add_argument("image_path", help="Path to the image file")
    p_match.add_argument("--product", "-p", required=True, help="Product name to match")

    # batch
    p_batch = vision_sub.add_parser("batch", help="Batch process images in a directory")
    p_batch.add_argument("directory", help="Directory containing images")
    p_batch.add_argument("--task", "-t", default="describe",
                        choices=["ocr", "describe", "descrever"],
                        help="Task to perform on each image")
    p_batch.add_argument("--pattern", default="*.*", help="Glob pattern for images (default: *.*)")
    p_batch.add_argument("--output", "-o", default=None, help="Output JSON file path")

    # compare
    p_compare = vision_sub.add_parser("compare", help="Compare two images")
    p_compare.add_argument("image_a", help="Path to first image")
    p_compare.add_argument("image_b", help="Path to second image")

    # extract-table
    p_table = vision_sub.add_parser("extract-table", help="Extract tabular data from an image")
    p_table.add_argument("image_path", help="Path to the image file")


def handle_vision_command(args) -> None:
    """Handle parsed vision CLI command."""
    vision = LauraVision()

    cmd = args.vision_command

    if cmd == "ocr":
        print(vision.ocr(args.image_path))

    elif cmd == "describe":
        print(vision.describe(args.image_path))

    elif cmd == "analyze":
        result = vision.analyze_complaint(args.image_path, args.product, args.variation)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif cmd == "match":
        result = vision.match_product(args.image_path, args.product)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif cmd == "batch":
        directory = Path(args.directory)
        if not directory.is_dir():
            print(f"[ERRO] Diretorio nao encontrado: {directory}")
            sys.exit(1)
        image_paths = sorted(directory.glob(args.pattern))
        if not image_paths:
            print(f"Nenhuma imagem encontrada com padrao '{args.pattern}' em {directory}")
            sys.exit(0)
        results = vision.batch_process(image_paths, task=args.task)
        output = json.dumps(results, indent=2, ensure_ascii=False)
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
            print(f"Resultados salvos em: {args.output}")
        else:
            print(output)

    elif cmd == "compare":
        result = vision.compare_images(args.image_a, args.image_b)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif cmd == "extract-table":
        result = vision.extract_table(args.image_path)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    else:
        print(f"Comando desconhecido: {cmd}")
        sys.exit(1)


# ------------------------------------------------------------------ #
# Main
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="laura vision", description="Laura Vision CLI")
    sub = parser.add_subparsers(dest="command")

    # Also support direct commands as first arg (backward compat)
    p_ocr = sub.add_parser("ocr", help="Extrai texto de imagem")
    p_ocr.add_argument("image_path", help="Caminho da imagem")
    p_ocr.add_argument("--model", default=None, help="Modelo Ollama")

    p_descrever = sub.add_parser("descrever", help="Descreve imagem")
    p_descrever.add_argument("image_path", help="Caminho da imagem")

    p_analisar = sub.add_parser("analisar", help="Analisa reclamacao")
    p_analisar.add_argument("image_path", help="Caminho da imagem")
    p_analisar.add_argument("produto", nargs="?", default="Produto nao especificado",
                            help="Descricao do produto")
    p_analisar.add_argument("--model", default=None)

    args = parser.parse_args()

    if args.command == "ocr":
        v = LauraVision(model=args.model) if args.model else _vision
        print(v.ocr(args.image_path))
    elif args.command == "descrever":
        print(_vision.descrever(args.image_path))
    elif args.command == "analisar":
        result = _vision.analisar_reclamacao(args.image_path, args.produto)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        parser.print_help()
        sys.exit(1)
