from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

import shopee_agent.cli as cli
from shopee_agent.vision_analysis import MarketplaceVisionAnalyzer


def _create_test_image(path: Path, size: tuple[int, int], color: tuple[int, int, int], label: str | None = None) -> None:
    image = Image.new("RGB", size, color)
    if label:
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 10, min(size[0] - 10, 220), min(size[1] - 10, 100)), outline=(20, 20, 20), width=4)
        draw.text((20, 30), label, fill=(0, 0, 0))
    image.save(path)


def test_marketplace_vision_analyzer_summarizes_thumbnail_quality(tmp_path):
    good_image = tmp_path / "good.png"
    bad_image = tmp_path / "bad.png"
    _create_test_image(good_image, (1200, 1200), (240, 240, 240), label="Produto")
    _create_test_image(bad_image, (320, 240), (25, 25, 25))

    analyzer = MarketplaceVisionAnalyzer()
    report = analyzer.analyze_paths([good_image, bad_image], perform_ocr=False)

    assert report.total_images == 2
    assert report.thumbnail_ready_count == 1
    assert report.low_resolution_count == 1
    assert report.dark_image_count == 1
    assert report.average_quality_score > 0

    good_analysis = next(analysis for analysis in report.analyses if analysis.path.endswith("good.png"))
    bad_analysis = next(analysis for analysis in report.analyses if analysis.path.endswith("bad.png"))

    assert good_analysis.thumbnail_ready is True
    assert bad_analysis.thumbnail_ready is False
    assert good_analysis.dominant_colors
    assert any("resolução" in recommendation.lower() for recommendation in report.recommendations)


def test_visual_analysis_cli_writes_json_report(tmp_path, monkeypatch):
    image_path = tmp_path / "listing.png"
    output_path = tmp_path / "visual_report.json"
    _create_test_image(image_path, (1000, 1000), (230, 230, 230), label="Oferta")

    monkeypatch.setattr(cli.sys, "argv", [
        "laura",
        "visual-analysis",
        str(image_path),
        "--output",
        str(output_path),
    ])

    exit_code = cli.main()

    assert exit_code == 0
    assert output_path.exists()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["total_images"] == 1
    assert payload["analyses"][0]["path"].endswith("listing.png")
    assert "average_quality_score" in payload