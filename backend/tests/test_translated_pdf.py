from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from app.services.manga_translation import PageTranslation
from app.services.translated_pdf import build_result_pdf, render_translated_page


def make_image(path: Path, color: str = "gray") -> None:
    Image.new("RGB", (200, 300), color).save(path, format="PNG")


def test_render_translated_page_replaces_detected_text_region(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    destination = tmp_path / "translated.png"
    make_image(source)
    translation = PageTranslation.model_validate(
        {
            "regions": [
                {
                    "box_2d": [100, 100, 600, 900],
                    "source_text": "こんにちは",
                    "translated_text": "Halo dari Meguyomi",
                }
            ]
        }
    )

    render_translated_page(source, destination, translation)

    with Image.open(destination) as rendered:
        assert rendered.size == (200, 300)
        assert rendered.getpixel((22, 32)) == (255, 255, 255)


def test_render_translated_page_never_draws_text_outside_detected_region(
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

    render_translated_page(source, destination, translation)

    with Image.open(destination) as rendered:
        for y in range(rendered.height):
            for x in range(rendered.width):
                if 20 <= x <= 100 and 30 <= y <= 180:
                    continue
                assert rendered.getpixel((x, y)) == (128, 128, 128)


def test_build_result_pdf_keeps_page_order(tmp_path: Path) -> None:
    first = tmp_path / "page-0001.png"
    second = tmp_path / "page-0002.png"
    result = tmp_path / "result.pdf"
    make_image(first, "white")
    make_image(second, "black")

    build_result_pdf([first, second], result)

    assert result.is_file()
    assert len(PdfReader(result).pages) == 2
