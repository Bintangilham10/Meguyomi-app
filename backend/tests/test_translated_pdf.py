from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader

from app.services.manga_translation import PageTranslation
from app.services.translated_pdf import (
    _choose_region_layout,
    _load_font,
    _normalize_display_text,
    _placement_candidates,
    _source_text_mask,
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
    draw.rectangle((20, 30, 26, 37), fill=(220, 0, 0))
    draw.rectangle((34, 52, 40, 60), fill=(220, 0, 0))
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


def test_source_text_mask_keeps_interior_thin_cjk_stroke() -> None:
    pixels = np.full((120, 120, 3), 255, dtype=np.uint8)
    pixels[10:111, 20:23] = (0, 0, 0)
    pixels[35:76, 55:59] = (28, 68, 136)

    mask, succeeded = _source_text_mask(
        pixels,
        (20, 20, 100, 100),
    )

    assert succeeded is True
    assert mask[55, 57] == 255
    assert mask[55, 21] == 0


def test_render_translated_page_preserves_art_inside_safe_placement(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    destination = tmp_path / "translated.png"
    image = Image.new("RGB", (200, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((62, 80, 68, 86), fill="black")
    image.save(source, format="PNG")
    translation = PageTranslation.model_validate(
        {
            "regions": [
                {
                    "box_2d": [100, 100, 200, 200],
                    "placement_box_2d": [80, 80, 300, 350],
                    "region_type": "dialogue",
                    "source_text": "日本語",
                    "translated_text": "Hai",
                }
            ]
        }
    )

    render_translated_page(source, destination, translation)

    with Image.open(destination) as rendered:
        artwork = rendered.crop((62, 80, 69, 87))
        assert all(
            all(channel < 32 for channel in artwork.getpixel((x, y)))
            for y in range(artwork.height)
            for x in range(artwork.width)
        )


def test_normalize_display_text_replaces_unsupported_comic_symbols() -> None:
    assert _normalize_display_text("Sayang♡…") == "Sayang♡..."


def test_normalize_display_text_only_applies_rendering_normalization() -> None:
    assert _normalize_display_text(
        "Istilah khusus すごい tetap sama."
    ) == "Istilah khusus tetap sama."
    assert _normalize_display_text("*DENTUM!*", "sfx") == "DENTUM!"
    assert _normalize_display_text("JUDUL CONTOH") == "JUDUL CONTOH"


def test_choose_region_layout_keeps_short_text_in_declared_box() -> None:
    translation = PageTranslation.model_validate(
        {
            "regions": [
                {
                    "box_2d": [120, 120, 360, 360],
                    "placement_box_2d": [100, 100, 400, 400],
                    "region_type": "dialogue",
                    "source_text": "こんにちは",
                    "translated_text": "Halo, apa kabar?",
                }
            ]
        }
    )
    source_pixels = np.full((1400, 1000, 3), 255, dtype=np.uint8)
    measure_image = Image.new("RGB", (8, 8), "white")
    draw = ImageDraw.Draw(measure_image)

    placement_box, font, _, _, _ = _choose_region_layout(
        draw,
        source_pixels,
        translation.regions[0],
        1000,
        1400,
        [],
    )

    assert placement_box == (100, 140, 400, 560)
    assert getattr(font, "size", 0) <= 17
    measure_image.close()


def test_placement_candidates_expand_only_modestly() -> None:
    base_box = (100, 100, 300, 300)

    candidates = _placement_candidates(
        base_box,
        width=1000,
        height=1000,
        region_type="dialogue",
    )

    assert candidates[0] == base_box
    assert max(box[2] - box[0] for box in candidates) <= 250
    assert max(box[3] - box[1] for box in candidates) <= 220


def test_build_result_pdf_keeps_page_order(tmp_path: Path) -> None:
    first = tmp_path / "page-0001.png"
    second = tmp_path / "page-0002.png"
    result = tmp_path / "result.pdf"
    make_image(first, "white")
    make_image(second, "black")

    build_result_pdf([first, second], result)

    assert result.is_file()
    assert len(PdfReader(result).pages) == 2


def test_build_result_pdf_skips_thin_extraction_artifact(
    tmp_path: Path,
) -> None:
    page = tmp_path / "page-0001.png"
    thin_artifact = tmp_path / "page-0002.png"
    result = tmp_path / "result.pdf"
    make_image(page, "white")
    Image.new("RGB", (2560, 100), "white").save(
        thin_artifact,
        format="PNG",
    )

    build_result_pdf([page, thin_artifact], result)

    assert len(PdfReader(result).pages) == 1
