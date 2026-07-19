from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter

from app.services.manga_translation import PageTranslation, TranslationRegion


class ResultBuildError(Exception):
    pass


def _pixel_box(region: TranslationRegion, width: int, height: int) -> tuple[int, int, int, int]:
    ymin, xmin, ymax, xmax = region.box_2d
    left = max(0, min(width - 1, round(xmin * width / 1000)))
    top = max(0, min(height - 1, round(ymin * height / 1000)))
    right = max(left + 1, min(width, round(xmax * width / 1000)))
    bottom = max(top + 1, min(height, round(ymax * height / 1000)))
    return left, top, right, bottom


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    max_width: int,
) -> str:
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        current = ""
        for word in paragraph.split() or [paragraph]:
            candidate = f"{current} {word}".strip()
            if not current or draw.textlength(candidate, font=font) <= max_width:
                current = candidate
                continue
            lines.append(current)
            current = word
        if current:
            lines.append(current)
    return "\n".join(lines)


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    box_width: int,
    box_height: int,
) -> tuple[ImageFont.ImageFont | ImageFont.FreeTypeFont, str, tuple[int, int, int, int]]:
    available_width = max(1, box_width - 8)
    available_height = max(1, box_height - 8)
    largest_size = min(48, max(8, box_height // 3))
    fallback: tuple[
        ImageFont.ImageFont | ImageFont.FreeTypeFont,
        str,
        tuple[int, int, int, int],
    ] | None = None
    for size in range(largest_size, 7, -1):
        font = ImageFont.load_default(size=size)
        wrapped = _wrap_text(draw, text, font, available_width)
        bounds = draw.multiline_textbbox(
            (0, 0),
            wrapped,
            font=font,
            spacing=2,
            align="center",
        )
        fallback = (font, wrapped, bounds)
        if bounds[2] - bounds[0] <= available_width and bounds[3] - bounds[1] <= available_height:
            return fallback
    assert fallback is not None
    return fallback


def render_translated_page(
    source: Path,
    destination: Path,
    translation: PageTranslation,
) -> None:
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as opened:
            image = opened.convert("RGB")
        try:
            for region in translation.regions:
                left, top, right, bottom = _pixel_box(
                    region,
                    image.width,
                    image.height,
                )
                box_width = right - left
                box_height = bottom - top
                region_image = Image.new("RGB", (box_width, box_height), "white")
                region_draw = ImageDraw.Draw(region_image)
                font, wrapped, bounds = _fit_text(
                    region_draw,
                    region.translated_text,
                    box_width,
                    box_height,
                )
                text_width = bounds[2] - bounds[0]
                text_height = bounds[3] - bounds[1]
                text_x = max(4, (box_width - text_width) // 2)
                text_y = max(4, (box_height - text_height) // 2)
                region_draw.multiline_text(
                    (text_x, text_y),
                    wrapped,
                    font=font,
                    fill="black",
                    spacing=2,
                    align="center",
                )
                image.paste(region_image, (left, top))
                region_image.close()
            image.save(destination, format="PNG", compress_level=6)
        finally:
            image.close()
    except Exception as error:
        destination.unlink(missing_ok=True)
        raise ResultBuildError("Translated page rendering failed.") from error


def build_result_pdf(page_paths: list[Path], destination: Path) -> None:
    if not page_paths:
        raise ResultBuildError("A result PDF requires at least one page.")
    buffers: list[BytesIO] = []
    writer = PdfWriter()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        for page_path in page_paths:
            with Image.open(page_path) as opened:
                image = opened.convert("RGB")
                buffer = BytesIO()
                image.save(buffer, format="PDF", resolution=150.0)
                image.close()
            buffer.seek(0)
            buffers.append(buffer)
            reader = PdfReader(buffer)
            if len(reader.pages) != 1:
                raise ResultBuildError("Translated page PDF is invalid.")
            writer.add_page(reader.pages[0])
        with destination.open("xb") as output:
            writer.write(output)
    except ResultBuildError:
        destination.unlink(missing_ok=True)
        raise
    except Exception as error:
        destination.unlink(missing_ok=True)
        raise ResultBuildError("Result PDF creation failed.") from error
    finally:
        for buffer in buffers:
            buffer.close()
