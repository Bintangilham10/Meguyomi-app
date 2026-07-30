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
_MIN_ANALYSIS_MARGIN = 12
_MAX_ANALYSIS_MARGIN = 96
_ANALYSIS_MARGIN_RATIO = 0.08
_SOURCE_PADDING_RATIO = 0.025
_MAX_SOURCE_PADDING = 32
_MAX_STROKE_COVERAGE = 0.55
_MAX_COMPONENT_COVERAGE = 0.22
_MIN_REGION_CONTRAST = 6.0
_TEXTURED_REGION_STD = 48.0
_COMMON_GLYPH_REPLACEMENTS = str.maketrans(
    {
        "♡": "<3",
        "♥": "<3",
        "～": "~",
        "〜": "~",
        "…": "...",
        "—": "-",
        "–": "-",
    }
)


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


def _normalized_pixel_box(
    box_2d: tuple[int, int, int, int],
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    ymin, xmin, ymax, xmax = box_2d
    left = max(0, min(width - 1, round(xmin * width / 1000)))
    top = max(0, min(height - 1, round(ymin * height / 1000)))
    right = max(left + 1, min(width, round(xmax * width / 1000)))
    bottom = max(top + 1, min(height, round(ymax * height / 1000)))
    return left, top, right, bottom


def _pixel_box(
    region: TranslationRegion,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    return _normalized_pixel_box(region.box_2d, width, height)


def _placement_pixel_box(
    region: TranslationRegion,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    placement_box = region.placement_box_2d or region.box_2d
    return _normalized_pixel_box(placement_box, width, height)


def _expand_box(
    box: tuple[int, int, int, int],
    width: int,
    height: int,
    amount: int,
) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    return (
        max(0, left - amount),
        max(0, top - amount),
        min(width, right + amount),
        min(height, bottom + amount),
    )


def _analysis_margin(box_width: int, box_height: int) -> int:
    proportional = round(min(box_width, box_height) * _ANALYSIS_MARGIN_RATIO)
    return max(
        _MIN_ANALYSIS_MARGIN,
        min(_MAX_ANALYSIS_MARGIN, proportional),
    )


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


def _source_text_mask(
    region_pixels: np.ndarray,
    content_box: tuple[int, int, int, int],
) -> tuple[np.ndarray, bool]:
    gray = cv2.cvtColor(region_pixels, cv2.COLOR_RGB2GRAY)
    left, top, right, bottom = content_box
    content_gray = gray[top:bottom, left:right]
    empty_mask = np.zeros(gray.shape, dtype=np.uint8)
    if (
        content_gray.size == 0
        or float(content_gray.std()) < _MIN_REGION_CONTRAST
    ):
        return empty_mask, False

    threshold, _ = cv2.threshold(
        content_gray,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )
    # Infer text polarity from the dominant background luminance. Choosing
    # the minority tone fails for white captions placed over gray artwork.
    background_luminance = float(np.median(content_gray))
    if background_luminance >= 128.0:
        stroke_mask = gray <= threshold
    else:
        stroke_mask = gray > threshold

    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        stroke_mask.astype(np.uint8),
        connectivity=8,
    )
    content_area = max(1, (right - left) * (bottom - top))
    crop_height, crop_width = gray.shape
    selected_labels: list[int] = []
    for label in range(1, component_count):
        x, y, component_width, component_height, area = stats[label]
        overlap_left = max(left, x)
        overlap_top = max(top, y)
        overlap_right = min(right, x + component_width)
        overlap_bottom = min(bottom, y + component_height)
        if overlap_right <= overlap_left or overlap_bottom <= overlap_top:
            continue
        component_coverage = area / content_area
        spans_crop = (
            component_width >= crop_width * 0.88
            or component_height >= crop_height * 0.88
        )
        touches_crop_edge = (
            x == 0
            or y == 0
            or x + component_width >= crop_width
            or y + component_height >= crop_height
        )
        if component_coverage > _MAX_COMPONENT_COVERAGE or spans_crop:
            continue
        if touches_crop_edge and component_coverage > 0.015:
            continue
        selected_labels.append(label)

    if not selected_labels:
        return empty_mask, False
    text_mask = np.isin(labels, selected_labels).astype(np.uint8)
    allowed = np.zeros_like(text_mask)
    allowed[top:bottom, left:right] = 1
    text_mask *= allowed
    stroke_coverage = float(text_mask.sum() / content_area)
    if stroke_coverage <= 0.0001 or stroke_coverage > _MAX_STROKE_COVERAGE:
        return empty_mask, False

    dilation_radius = max(
        2,
        min(8, round(min(right - left, bottom - top) * 0.012)),
    )
    kernel_size = dilation_radius * 2 + 1
    text_mask = cv2.dilate(
        text_mask * 255,
        np.ones((kernel_size, kernel_size), np.uint8),
        iterations=1,
    )
    text_mask *= allowed
    return text_mask, True


def _backdrop_color(region_pixels: np.ndarray) -> tuple[int, int, int]:
    if region_pixels.size == 0:
        return (255, 255, 255)
    height, width = region_pixels.shape[:2]
    border_size = max(1, min(height, width) // 12)
    border_pixels = np.concatenate(
        (
            region_pixels[:border_size].reshape(-1, 3),
            region_pixels[-border_size:].reshape(-1, 3),
            region_pixels[:, :border_size].reshape(-1, 3),
            region_pixels[:, -border_size:].reshape(-1, 3),
        ),
        axis=0,
    )
    median = np.median(border_pixels, axis=0)
    luminance = float(
        0.2126 * median[0] + 0.7152 * median[1] + 0.0722 * median[2]
    )
    if luminance >= 150.0:
        return (255, 255, 255)
    if luminance <= 90.0:
        return (24, 24, 24)
    return tuple(int(channel) for channel in median)


def _needs_backdrop(
    region: TranslationRegion,
    region_pixels: np.ndarray,
    mask_succeeded: bool,
) -> bool:
    if region.region_type == "sfx":
        return False
    if region.region_type in {"dialogue", "caption", "title"}:
        return True
    if not mask_succeeded or region_pixels.size == 0:
        return True
    gray = cv2.cvtColor(region_pixels, cv2.COLOR_RGB2GRAY)
    return float(gray.std()) >= _TEXTURED_REGION_STD


def _text_style(region_pixels: np.ndarray) -> tuple[str, str | None]:
    luminance = float(cv2.cvtColor(region_pixels, cv2.COLOR_RGB2GRAY).mean())
    if luminance >= 160.0:
        return "black", None
    if luminance <= 96.0:
        return "white", None
    return "white", "black"


def _normalize_display_text(text: str) -> str:
    normalized = text.translate(_COMMON_GLYPH_REPLACEMENTS)
    return " ".join(normalized.split())


def _split_long_token(
    draw: ImageDraw.ImageDraw,
    token: str,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    chunks: list[str] = []
    current = ""
    for character in token:
        candidate = current + character
        if current and draw.textlength(candidate, font=font) > max_width:
            chunks.append(current)
            current = character
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    max_width: int,
    *,
    split_long_tokens: bool = False,
) -> str:
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        current = ""
        words: list[str] = []
        for word in paragraph.split() or [paragraph]:
            if (
                split_long_tokens
                and draw.textlength(word, font=font) > max_width
            ):
                words.extend(
                    _split_long_token(draw, word, font, max_width)
                )
            else:
                words.append(word)
        for word in words:
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
    for size in range(largest_size, _MIN_FONT_SIZE - 1, -1):
        font = _load_font(size)
        spacing = max(2, size // 4)
        wrapped = _wrap_text(
            draw,
            text,
            font,
            available_width,
            split_long_tokens=size == _MIN_FONT_SIZE,
        )
        bounds = draw.multiline_textbbox(
            (0, 0),
            wrapped,
            font=font,
            spacing=spacing,
            align="center",
        )
        if bounds[2] - bounds[0] <= available_width and bounds[3] - bounds[1] <= available_height:
            return font, wrapped, bounds, spacing
    raise ResultBuildError("Translated text does not fit inside its region.")


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
            source_pixels = np.asarray(image, dtype=np.uint8)
            page_mask = np.zeros(
                (image.height, image.width),
                dtype=np.uint8,
            )
            plans: list[
                tuple[
                    TranslationRegion,
                    tuple[int, int, int, int],
                    bool,
                ]
            ] = []

            # Build one union mask first. This prevents a later overlapping
            # region from erasing Indonesian text drawn for an earlier one.
            for region in translation.regions:
                source_box = _pixel_box(
                    region,
                    image.width,
                    image.height,
                )
                source_width = source_box[2] - source_box[0]
                source_height = source_box[3] - source_box[1]
                source_padding = max(
                    2,
                    min(
                        _MAX_SOURCE_PADDING,
                        round(
                            min(source_width, source_height)
                            * _SOURCE_PADDING_RATIO
                        ),
                    ),
                )
                padded_source_box = _expand_box(
                    source_box,
                    image.width,
                    image.height,
                    source_padding,
                )
                margin = _analysis_margin(source_width, source_height)
                analysis_box = _expand_box(
                    padded_source_box,
                    image.width,
                    image.height,
                    margin,
                )
                crop_left, crop_top, crop_right, crop_bottom = analysis_box
                region_pixels = source_pixels[
                    crop_top:crop_bottom,
                    crop_left:crop_right,
                ]
                content_box = (
                    padded_source_box[0] - crop_left,
                    padded_source_box[1] - crop_top,
                    padded_source_box[2] - crop_left,
                    padded_source_box[3] - crop_top,
                )
                local_mask, mask_succeeded = _source_text_mask(
                    region_pixels,
                    content_box,
                )
                if region.region_type == "sfx":
                    # Stylized SFX is part of the artwork. Classical inpainting
                    # leaves conspicuous smears, so retain it and add a compact
                    # Indonesian annotation instead.
                    local_mask.fill(0)
                    mask_succeeded = False
                page_mask[crop_top:crop_bottom, crop_left:crop_right] = (
                    np.maximum(
                        page_mask[
                            crop_top:crop_bottom,
                            crop_left:crop_right,
                        ],
                        local_mask,
                    )
                )
                plans.append((region, padded_source_box, mask_succeeded))

            if np.any(page_mask):
                erased_pixels = cv2.inpaint(
                    source_pixels,
                    page_mask,
                    5,
                    cv2.INPAINT_TELEA,
                )
                image.close()
                image = Image.fromarray(erased_pixels)

            for region, _source_box, mask_succeeded in plans:
                left, top, right, bottom = _placement_pixel_box(
                    region,
                    image.width,
                    image.height,
                )
                box_width = right - left
                box_height = bottom - top
                text_layer = image.crop((left, top, right, bottom))
                text_pixels = np.asarray(text_layer, dtype=np.uint8)
                text_draw = ImageDraw.Draw(text_layer)
                if _needs_backdrop(region, text_pixels, mask_succeeded):
                    color = _backdrop_color(text_pixels)
                    if region.region_type == "dialogue":
                        radius = max(
                            4,
                            min(box_width, box_height) // 16,
                        )
                        text_draw.rounded_rectangle(
                            (0, 0, box_width - 1, box_height - 1),
                            radius=radius,
                            fill=color,
                        )
                    else:
                        text_draw.rectangle(
                            (0, 0, box_width - 1, box_height - 1),
                            fill=color,
                        )
                    text_pixels = np.asarray(text_layer, dtype=np.uint8)
                fill, stroke_fill = _text_style(text_pixels)
                display_text = _normalize_display_text(
                    region.translated_text
                )
                font, wrapped, bounds, spacing = _fit_text(
                    text_draw,
                    display_text,
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
                image.paste(text_layer, (left, top))
                text_layer.close()
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
