import json
import logging
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter

from app.services.manga_translation import PageTranslation, TranslationRegion


logger = logging.getLogger(__name__)


class ResultBuildError(Exception):
    pass


_FONT_PATH = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "fonts"
    / "ComicNeue-Bold.ttf"
)
_MIN_FONT_SIZE = 9
_MAX_FONT_SIZE = 64
# Analisis penghapusan meluas beberapa piksel melewati box_2d supaya glyph
# yang menempel tepi box tidak ikut terklasifikasi sebagai border region.
_ANALYSIS_MARGIN = 4
# Batas rasio piksel goresan: di atas ini region dianggap artwork, bukan teks,
# sehingga inpainting dilewati agar gambar tidak ikut terhapus.
_MAX_STROKE_COVERAGE = 0.45
_MIN_REGION_CONTRAST = 8.0


@lru_cache(maxsize=None)
def _load_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(_FONT_PATH), size=size)
    except OSError:
        logger.warning(
            json.dumps(
                {
                    "event": "comic_font_missing",
                    "fontPath": str(_FONT_PATH),
                }
            )
        )
        return ImageFont.load_default(size=size)


def _pixel_box(region: TranslationRegion, width: int, height: int) -> tuple[int, int, int, int]:
    ymin, xmin, ymax, xmax = region.box_2d
    left = max(0, min(width - 1, round(xmin * width / 1000)))
    top = max(0, min(height - 1, round(ymin * height / 1000)))
    right = max(left + 1, min(width, round(xmax * width / 1000)))
    bottom = max(top + 1, min(height, round(ymax * height / 1000)))
    return left, top, right, bottom


def _erase_source_text(region_pixels: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(region_pixels, cv2.COLOR_RGB2GRAY)
    if float(gray.std()) < _MIN_REGION_CONTRAST:
        return region_pixels
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bright_ratio = float((binary == 255).mean())
    stroke_mask = (binary == 0) if bright_ratio >= 0.5 else (binary == 255)

    # Komponen yang menyentuh tepi region adalah border balon, panel, atau
    # latar — bukan goresan teks — dan tidak boleh ikut di-inpaint.
    component_count, labels = cv2.connectedComponents(
        stroke_mask.astype(np.uint8),
        connectivity=8,
    )
    border_labels = np.unique(
        np.concatenate(
            (labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1])
        )
    )
    interior_labels = [
        label
        for label in range(1, component_count)
        if label not in border_labels
    ]
    if not interior_labels:
        return region_pixels
    text_mask = np.isin(labels, interior_labels)
    if float(text_mask.mean()) > _MAX_STROKE_COVERAGE:
        return region_pixels
    mask = cv2.dilate(
        text_mask.astype(np.uint8) * 255,
        np.ones((3, 3), np.uint8),
        iterations=2,
    )
    return cv2.inpaint(region_pixels, mask, 3, cv2.INPAINT_TELEA)


def _text_style(region_pixels: np.ndarray) -> tuple[str, str | None]:
    luminance = float(cv2.cvtColor(region_pixels, cv2.COLOR_RGB2GRAY).mean())
    if luminance >= 160.0:
        return "black", None
    if luminance <= 96.0:
        return "white", None
    return "white", "black"


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
) -> tuple[
    ImageFont.ImageFont | ImageFont.FreeTypeFont,
    str,
    tuple[int, int, int, int],
    int,
]:
    padding = max(4, min(box_width, box_height) // 12)
    available_width = max(1, box_width - 2 * padding)
    available_height = max(1, box_height - 2 * padding)
    largest_size = min(_MAX_FONT_SIZE, max(_MIN_FONT_SIZE, box_height // 3))
    fallback: tuple[
        ImageFont.ImageFont | ImageFont.FreeTypeFont,
        str,
        tuple[int, int, int, int],
        int,
    ] | None = None
    for size in range(largest_size, _MIN_FONT_SIZE - 1, -1):
        font = _load_font(size)
        spacing = max(2, size // 4)
        wrapped = _wrap_text(draw, text, font, available_width)
        bounds = draw.multiline_textbbox(
            (0, 0),
            wrapped,
            font=font,
            spacing=spacing,
            align="center",
        )
        fallback = (font, wrapped, bounds, spacing)
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
                crop_left = max(0, left - _ANALYSIS_MARGIN)
                crop_top = max(0, top - _ANALYSIS_MARGIN)
                crop_right = min(image.width, right + _ANALYSIS_MARGIN)
                crop_bottom = min(image.height, bottom + _ANALYSIS_MARGIN)
                region_pixels = np.asarray(
                    image.crop((crop_left, crop_top, crop_right, crop_bottom)),
                    dtype=np.uint8,
                )
                erased = _erase_source_text(region_pixels)
                fill, stroke_fill = _text_style(erased)
                erased_image = Image.fromarray(erased)
                offset_x = left - crop_left
                offset_y = top - crop_top
                text_layer = erased_image.crop(
                    (
                        offset_x,
                        offset_y,
                        offset_x + box_width,
                        offset_y + box_height,
                    )
                )
                text_draw = ImageDraw.Draw(text_layer)
                font, wrapped, bounds, spacing = _fit_text(
                    text_draw,
                    region.translated_text,
                    box_width,
                    box_height,
                )
                text_width = bounds[2] - bounds[0]
                text_height = bounds[3] - bounds[1]
                text_x = (box_width - text_width) // 2 - bounds[0]
                text_y = (box_height - text_height) // 2 - bounds[1]
                text_draw.multiline_text(
                    (text_x, text_y),
                    wrapped,
                    font=font,
                    fill=fill,
                    spacing=spacing,
                    align="center",
                    stroke_width=2 if stroke_fill else 0,
                    stroke_fill=stroke_fill,
                )
                erased_image.paste(text_layer, (offset_x, offset_y))
                image.paste(erased_image, (crop_left, crop_top))
                text_layer.close()
                erased_image.close()
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
