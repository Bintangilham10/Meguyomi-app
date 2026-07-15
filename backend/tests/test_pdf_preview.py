from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfWriter

from app.services.pdf_preview import PreviewRenderError, render_pdf_previews


def make_pdf(page_count: int = 1) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=600, height=800)
    writer.write(output)
    return output.getvalue()


def test_render_pdf_previews_creates_numbered_png_pages(tmp_path: Path) -> None:
    source = tmp_path / "chapter.pdf"
    destination = tmp_path / "previews"
    source.write_bytes(make_pdf(page_count=2))

    page_count = render_pdf_previews(source, destination, scale=1.0)

    assert page_count == 2
    assert sorted(path.name for path in destination.iterdir()) == [
        "page-0001.png",
        "page-0002.png",
    ]
    with Image.open(destination / "page-0001.png") as preview:
        assert preview.format == "PNG"
        assert preview.size == (600, 800)


def test_render_pdf_previews_removes_partial_output_on_failure(
    tmp_path: Path,
) -> None:
    source = tmp_path / "invalid.pdf"
    destination = tmp_path / "previews"
    source.write_bytes(b"not a PDF")

    with pytest.raises(PreviewRenderError):
        render_pdf_previews(source, destination, scale=1.0)

    assert not destination.exists()


def test_render_pdf_previews_enforces_pixel_budget(tmp_path: Path) -> None:
    source = tmp_path / "chapter.pdf"
    destination = tmp_path / "previews"
    source.write_bytes(make_pdf())

    with pytest.raises(PreviewRenderError):
        render_pdf_previews(source, destination, scale=1.0, max_pixels=100)

    assert not destination.exists()
