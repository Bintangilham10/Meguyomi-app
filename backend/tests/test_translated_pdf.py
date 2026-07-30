from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader

from app.services.manga_translation import PageTranslation
from app.services.translated_pdf import (
    _load_font,
    _normalize_display_text,
    ResultBuildError,
    build_result_pdf,
    render_translated_page,
)


def make_image(path: Path, color: str = "gray") -> None:
    Image.new("RGB", (200, 300), color).save(path, format="PNG")


def test_render_translated_page_erases_source_strokes_and_draws_text(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    destination = tmp_path / "translated.png"
    image = Image.new("RGB", (200, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 40, 60, 50), fill="black")
    image.save(source, format="PNG")
    translation = PageTranslation.model_validate(
        {
            "regions": [
                {
                    "box_2d": [100, 100, 600, 900],
                    "source_text": "こんにちは",
                    "translated_text": "Halo",
                }
            ]
        }
    )

    render_translated_page(source, destination, translation)

    with Image.open(destination) as rendered:
        assert rendered.size == (200, 300)
        stroke_pixel = rendered.getpixel((45, 45))
        assert all(channel > 200 for channel in stroke_pixel)
        region_pixels = [
            rendered.getpixel((x, y))
            for y in range(30, 180)
            for x in range(20, 180)
        ]
        assert any(
            all(channel < 64 for channel in pixel) for pixel in region_pixels
        )


def test_render_translated_page_uses_bundled_comic_font() -> None:
    font = _load_font(24)

    assert font.getname()[0] == "Comic Neue"


def test_render_translated_page_rejects_text_that_cannot_fit(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    destination = tmp_path / "translated.png"
    make_image(source)
    translation = PageTranslation.model_validate(
        {
            "regions": [
                {
                    "box_2d": [100, 100, 600, 500],
                    "source_text": "長い文字",
                    "translated_text": "katayangsangatpanjangtanpaspasi" * 10,
                }
            ]
        }
    )

    with pytest.raises(ResultBuildError):
        render_translated_page(source, destination, translation)

    assert not destination.exists()


def test_render_translated_page_erases_tight_edge_touching_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    destination = tmp_path / "translated.png"
    image = Image.new("RGB", (200, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 30, 40, 60), fill=(220, 0, 0))
    image.save(source, format="PNG")
    translation = PageTranslation.model_validate(
        {
            "regions": [
                {
                    "box_2d": [100, 100, 200, 200],
                    "placement_box_2d": [80, 80, 240, 400],
                    "region_type": "dialogue",
                    "source_text": "赤",
                    "translated_text": "Merah",
                }
            ]
        }
    )

    render_translated_page(source, destination, translation)

    with Image.open(destination) as rendered:
        source_area = rendered.crop((18, 28, 43, 63))
        assert not any(
            source_area.getpixel((x, y))[0] > 160
            and source_area.getpixel((x, y))[1] < 80
            and source_area.getpixel((x, y))[2] < 80
            for y in range(source_area.height)
            for x in range(source_area.width)
        )


def test_normalize_display_text_replaces_unsupported_comic_symbols() -> None:
    assert _normalize_display_text("Sayang♡…") == "Sayang<3..."


def test_build_result_pdf_keeps_page_order(tmp_path: Path) -> None:
    first = tmp_path / "page-0001.png"
    second = tmp_path / "page-0002.png"
    result = tmp_path / "result.pdf"
    make_image(first, "white")
    make_image(second, "black")

    build_result_pdf([first, second], result)

    assert result.is_file()
    assert len(PdfReader(result).pages) == 2
