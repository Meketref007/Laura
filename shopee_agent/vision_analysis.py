"""
Phase 6: Vision Computacional.

Analisa imagens locais de marketplace para avaliar qualidade visual,
detectabilidade de texto, adequacao para thumbnail e sinais basicos de OCR.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageOps, ImageStat

try:  # Optional OCR support when pytesseract is installed.
    import pytesseract  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pytesseract = None


SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
_VISION_CACHE_DIR: Path | None = None


def _get_vision_cache() -> Path:
    global _VISION_CACHE_DIR
    if _VISION_CACHE_DIR is None:
        _VISION_CACHE_DIR = Path(tempfile.gettempdir()) / "laura_vision_cache"
        _VISION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _VISION_CACHE_DIR


@dataclass
class VisualAssetAnalysis:
    path: str
    width: int
    height: int
    aspect_ratio: float
    mode: str
    brightness: float
    contrast: float
    edge_density: float
    dominant_colors: list[str] = field(default_factory=list)
    ocr_text: str | None = None
    ocr_available: bool = False
    text_char_count: int = 0
    quality_score: float = 0.0
    thumbnail_ready: bool = False
    issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VisualAnalysisReport:
    total_images: int
    thumbnail_ready_count: int
    low_resolution_count: int
    dark_image_count: int
    text_heavy_count: int
    average_quality_score: float
    analyses: list[VisualAssetAnalysis] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_images": self.total_images,
            "thumbnail_ready_count": self.thumbnail_ready_count,
            "low_resolution_count": self.low_resolution_count,
            "dark_image_count": self.dark_image_count,
            "text_heavy_count": self.text_heavy_count,
            "average_quality_score": self.average_quality_score,
            "analyses": [analysis.to_dict() for analysis in self.analyses],
            "recommendations": list(self.recommendations),
        }


class MarketplaceVisionAnalyzer:
    """Lightweight visual intelligence for marketplace images."""

    def __init__(self, min_thumbnail_size: int = 800):
        self.min_thumbnail_size = min_thumbnail_size

    def analyze_paths(self, inputs: list[str | Path], perform_ocr: bool = True) -> VisualAnalysisReport:
        image_paths = self._collect_image_paths(inputs)
        analyses = [self.analyze_image(path, perform_ocr=perform_ocr) for path in image_paths]

        total_images = len(analyses)
        thumbnail_ready_count = sum(1 for analysis in analyses if analysis.thumbnail_ready)
        low_resolution_count = sum(1 for analysis in analyses if min(analysis.width, analysis.height) < self.min_thumbnail_size)
        dark_image_count = sum(1 for analysis in analyses if analysis.brightness < 70)
        text_heavy_count = sum(1 for analysis in analyses if analysis.text_char_count >= 25)
        average_quality_score = round(sum(analysis.quality_score for analysis in analyses) / total_images, 2) if analyses else 0.0

        recommendations = self._aggregate_recommendations(analyses)

        return VisualAnalysisReport(
            total_images=total_images,
            thumbnail_ready_count=thumbnail_ready_count,
            low_resolution_count=low_resolution_count,
            dark_image_count=dark_image_count,
            text_heavy_count=text_heavy_count,
            average_quality_score=average_quality_score,
            analyses=analyses,
            recommendations=recommendations,
        )

    def analyze_image(self, image_path: str | Path, perform_ocr: bool = True) -> VisualAssetAnalysis:
        path = Path(image_path)
        with Image.open(path) as handle:
            image = ImageOps.exif_transpose(handle).convert("RGB")

        width, height = image.size
        aspect_ratio = round(width / height, 3) if height else 0.0
        brightness, contrast = self._brightness_and_contrast(image)
        edge_density = self._edge_density(image)
        dominant_colors = self._dominant_colors(image)
        ocr_text = self._extract_ocr_text(image) if perform_ocr else None
        text_char_count = len((ocr_text or "").strip())

        issues: list[str] = []
        recommendations: list[str] = []
        quality_score = 100.0

        if min(width, height) < self.min_thumbnail_size:
            issues.append("low_resolution")
            recommendations.append("Aumentar a resolução para uso seguro em thumbnail")
            quality_score -= 25

        if brightness < 70:
            issues.append("dark_image")
            recommendations.append("Melhorar a iluminação ou clarear a imagem")
            quality_score -= 15
        elif brightness > 220:
            issues.append("overexposed")
            recommendations.append("Reduzir brilho/exposição para recuperar detalhes")
            quality_score -= 10

        if contrast < 35:
            issues.append("low_contrast")
            recommendations.append("Aumentar contraste para destacar o produto")
            quality_score -= 15

        if edge_density < 0.04:
            issues.append("flat_visuals")
            recommendations.append("Adicionar detalhes visuais ou reforçar contornos")
            quality_score -= 10

        if abs(aspect_ratio - 1.0) > 0.30:
            issues.append("non_square_thumbnail")
            recommendations.append("Ajustar o enquadramento para um formato mais quadrado")
            quality_score -= 8

        if text_char_count >= 25:
            issues.append("text_heavy")
            recommendations.append("Reduzir texto sobreposto para preservar legibilidade da thumbnail")
            quality_score -= 10

        ocr_available = pytesseract is not None and perform_ocr
        thumbnail_ready = quality_score >= 60 and min(width, height) >= self.min_thumbnail_size and brightness >= 70

        return VisualAssetAnalysis(
            path=str(path),
            width=width,
            height=height,
            aspect_ratio=aspect_ratio,
            mode=image.mode,
            brightness=round(brightness, 2),
            contrast=round(contrast, 2),
            edge_density=round(edge_density, 4),
            dominant_colors=dominant_colors,
            ocr_text=ocr_text,
            ocr_available=ocr_available,
            text_char_count=text_char_count,
            quality_score=round(max(0.0, quality_score), 2),
            thumbnail_ready=thumbnail_ready,
            issues=issues,
            recommendations=recommendations,
        )

    def analyze_directory(self, directory: str | Path, perform_ocr: bool = True) -> VisualAnalysisReport:
        return self.analyze_paths([directory], perform_ocr=perform_ocr)

    def _collect_image_paths(self, inputs: list[str | Path]) -> list[Path]:
        paths: list[Path] = []
        for raw_input in inputs:
            candidate = Path(raw_input)
            if candidate.is_dir():
                for child in sorted(candidate.rglob("*")):
                    if child.is_file() and child.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES:
                        paths.append(child)
                continue
            if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES:
                paths.append(candidate)
        return paths

    def _brightness_and_contrast(self, image: Image.Image) -> tuple[float, float]:
        grayscale = image.convert("L")
        stats = ImageStat.Stat(grayscale)
        mean = float(stats.mean[0])
        contrast = float(stats.stddev[0]) if stats.stddev else 0.0
        return mean, contrast

    def _edge_density(self, image: Image.Image) -> float:
        edges = image.convert("L").filter(ImageFilter.FIND_EDGES)
        stats = ImageStat.Stat(edges)
        return float(stats.mean[0]) / 255.0 if stats.mean else 0.0

    def _dominant_colors(self, image: Image.Image, colors: int = 3) -> list[str]:
        quantized = image.convert("RGB").resize((64, 64)).quantize(colors=colors)
        palette = quantized.getpalette() or []
        counts = quantized.getcolors() or []
        ranked = sorted(counts, reverse=True)[:colors]

        dominant: list[str] = []
        for _count, index in ranked:
            offset = index * 3
            if offset + 2 >= len(palette):
                continue
            dominant.append(f"#{palette[offset]:02x}{palette[offset + 1]:02x}{palette[offset + 2]:02x}")
        return dominant

    def _extract_ocr_text(self, image: Image.Image) -> str | None:
        if pytesseract is None:
            return None
        try:
            return pytesseract.image_to_string(image).strip() or None
        except Exception:
            return None

    def _aggregate_recommendations(self, analyses: list[VisualAssetAnalysis]) -> list[str]:
        if not analyses:
            return ["Nenhuma imagem suportada foi encontrada para análise."]

        recommendations: list[str] = []
        if any("low_resolution" in analysis.issues for analysis in analyses):
            recommendations.append("Aumentar a resolução das imagens para pelo menos 800px no menor lado.")
        if any("dark_image" in analysis.issues for analysis in analyses):
            recommendations.append("Revisar iluminação para evitar thumbnails escuras.")
        if any("text_heavy" in analysis.issues for analysis in analyses):
            recommendations.append("Reduzir texto sobreposto para preservar foco no produto.")
        if any(analysis.thumbnail_ready for analysis in analyses):
            recommendations.append("Promover os ativos com melhor score visual como thumbnails principais.")
        return recommendations or ["Pipeline visual saudável; continuar monitorando novos ativos."]


def dump_visual_report(report: VisualAnalysisReport, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def download_product_image(url: str, item_id: int | str, index: int = 0) -> Path | None:
    """Download a product image from URL to local cache for vision analysis."""
    try:
        import requests as _req
        cache = _get_vision_cache()
        ext = Path(url.split("?")[0]).suffix or ".jpg"
        dest = cache / f"item_{item_id}_{index}{ext}"
        if dest.exists():
            return dest
        resp = _req.get(url, timeout=30)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return dest
    except Exception:
        return None


def analyze_product_images(
    image_urls: list[str],
    item_id: int | str,
    perform_ocr: bool = True,
) -> dict[str, Any]:
    """Download and analyze product images; return a summary dict for LLM prompts."""
    analyzer = MarketplaceVisionAnalyzer()
    local_paths = []
    for i, url in enumerate(image_urls):
        p = download_product_image(url, item_id, i)
        if p:
            local_paths.append(str(p))
    if not local_paths:
        return {
            "item_id": str(item_id),
            "images_analyzed": 0,
            "vision_summary": "Nenhuma imagem disponivel para analise",
        }
    report = analyzer.analyze_paths(local_paths, perform_ocr=perform_ocr)
    avg_q = report.average_quality_score
    text_found = any(a.ocr_text for a in report.analyses if a.ocr_text)
    ocr_texts = [a.ocr_text for a in report.analyses if a.ocr_text]
    return {
        "item_id": str(item_id),
        "images_analyzed": report.total_images,
        "average_quality_score": avg_q,
        "thumbnail_ready": report.thumbnail_ready_count,
        "low_resolution": report.low_resolution_count,
        "dark_images": report.dark_image_count,
        "text_detected": text_found,
        "ocr_texts": ocr_texts[:3],
        "vision_summary": (
            f"Qualidade visual media: {avg_q}/100. "
            f"{report.thumbnail_ready_count}/{report.total_images} imagens prontas para thumbnail. "
            + (f"Texto detectado em {len(ocr_texts)} imagem(ns). " if text_found else "")
            + " ".join(report.recommendations[:2])
        ),
        "recommendations": report.recommendations,
    }


def build_vision_context(image_data: list[dict[str, Any]]) -> str:
    """Build a compact text snippet about image quality for LLM prompt injection."""
    if not image_data:
        return ""
    parts = []
    for d in image_data:
        parts.append(
            f"Item {d.get('item_id', '?')}: "
            f"qualidade {d.get('average_quality_score', 0):.0f}/100, "
            f"{d.get('images_analyzed', 0)} imagens"
        )
        if d.get("text_detected"):
            parts.append("(OCR detectou texto)")
    return "Analise visual:\n" + "\n".join(parts)


def analyze_items_visuals(
    items: list[dict[str, Any]],
    max_items: int = 5,
    max_images_per_item: int = 1,
    perform_ocr: bool = True,
) -> str:
    """Analyze visuals of Shopee product items and return LLM-ready vision context.
    
    Args:
        items: List of product items from get_item_list / get_item_detail (each must have item_id and image/image_id_list)
        max_items: Maximum number of items to analyze (to limit I/O)
        max_images_per_item: Images to analyze per item
        perform_ocr: Whether to run OCR on images
    Returns:
        Compact vision context string ready to inject into LLM prompts
    """
    if not items:
        return ""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    selected = items[:max_items]
    image_data: list[dict[str, Any]] = []

    def _extract_image_ids(item: dict[str, Any]) -> list[str]:
        img = item.get("image", {})
        if isinstance(img, dict):
            ids = img.get("image_id_list", [])
            if ids:
                return ids[:max_images_per_item]
        raw = item.get("image_id_list", [])
        if raw:
            return raw[:max_images_per_item]
        return []

    def _process_item(item: dict[str, Any]) -> dict[str, Any] | None:
        item_id = item.get("item_id", 0)
        image_ids = _extract_image_ids(item)
        if not image_ids:
            return None
        urls = [f"https://cf.shopee.com.br/file/{img_id}" for img_id in image_ids]
        try:
            return analyze_product_images(urls, item_id, perform_ocr=perform_ocr)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_process_item, item): item for item in selected}
        for future in as_completed(futures):
            result = future.result()
            if result:
                image_data.append(result)

    return build_vision_context(image_data)
