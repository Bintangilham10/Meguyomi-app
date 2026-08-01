import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from math import ceil
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
_SOURCE_PADDING_PAGE_RATIO = 0.012
_MIN_SOURCE_PADDING = 4
_MAX_SOURCE_PADDING = 64
_MAX_STROKE_COVERAGE = 0.55
_MAX_COMPONENT_COVERAGE = 0.22
_MIN_REGION_CONTRAST = 6.0
_VECTOR_HEART = "\u2661"
_VECTOR_MUSIC_NOTE = "\u266a"
_VECTOR_SYMBOLS = frozenset({_VECTOR_HEART, _VECTOR_MUSIC_NOTE})
_COMMON_GLYPH_REPLACEMENTS = {
    "\u2665": _VECTOR_HEART,
    "\u2661": _VECTOR_HEART,
    "\u266b": _VECTOR_MUSIC_NOTE,
    "\u266a": _VECTOR_MUSIC_NOTE,
    "\uff5e": "~",
    "\u301c": "~",
    "\u2026": "...",
    "\u2014": "-",
    "\u2013": "-",
    "\u2212": "-",
    "\u3008": "(",
    "\u3009": ")",
    "\uff08": "(",
    "\uff09": ")",
    "\uff01": "!",
    "\uff1f": "?",
    "\uff0c": ",",
    "\uff0e": ".",
    "\uff1a": ":",
    "\uff1b": ";",
    "\ufffd": "",
}
_MOJIBAKE_REPLACEMENTS = {
    "â™¡": _VECTOR_HEART,
    "â™¥": _VECTOR_HEART,
    "ï½ž": "~",
    "ã€œ": "~",
    "â€¦": "...",
    "â€”": "-",
    "â€“": "-",
}
_REGION_MIN_FONT_RATIOS = {
    "dialogue": 0.008,
    "caption": 0.0075,
    "title": 0.008,
    "sfx": 0.007,
}
_REGION_PREFERRED_MIN_FONT_RATIOS = {
    "dialogue": 0.010,
    "caption": 0.0095,
    "title": 0.011,
    "sfx": 0.008,
}
_REGION_MAX_FONT_RATIOS = {
    "dialogue": 0.017,
    "caption": 0.0155,
    "title": 0.022,
    "sfx": 0.013,
}
_REGION_MAX_LINES = {
    "dialogue": 10,
    "caption": 9,
    "title": 6,
    "sfx": 2,
}
_THIN_PAGE_ASPECT_RATIO = 0.12
_THIN_PAGE_MAX_SHORT_EDGE = 512


@dataclass(frozen=True)
class _RegionPlan:
    region: TranslationRegion
    placement_box: tuple[int, int, int, int]
    mask_succeeded: bool
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont
    wrapped: str
    bounds: tuple[int, int, int, int]
    spacing: int


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
        long_thin_boundary = (
            component_height > (bottom - top) * 0.14
            and component_width < component_height * 0.42
        ) or (
            component_width > (right - left) * 0.72
            and component_height < component_width * 0.12
        )
        if component_coverage > _MAX_COMPONENT_COVERAGE or spans_crop:
            continue
        if long_thin_boundary:
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
    if luminance >= 128.0:
        return (255, 255, 255)
    return (24, 24, 24)


def _needs_backdrop(
    region: TranslationRegion,
    region_pixels: np.ndarray,
    mask_succeeded: bool,
) -> bool:
    region_type = region.region_type or "dialogue"
    if region_type == "title":
        return True
    if region_type == "sfx":
        return False
    if not mask_succeeded or region_pixels.size == 0:
        return True
    height, width = region_pixels.shape[:2]
    inset_y = max(0, round(height * 0.12))
    inset_x = max(0, round(width * 0.12))
    central = region_pixels[
        inset_y : max(inset_y + 1, height - inset_y),
        inset_x : max(inset_x + 1, width - inset_x),
    ]
    gray = cv2.cvtColor(central, cv2.COLOR_RGB2GRAY)
    luminance = float(gray.mean())
    texture = float(gray.std())
    edges = cv2.Canny(gray, 80, 160) > 0
    _, _, edge_stats, _ = cv2.connectedComponentsWithStats(
        edges.astype(np.uint8),
        connectivity=8,
    )
    strong_boundary = any(
        component_width >= central.shape[1] * 0.48
        or component_height >= central.shape[0] * 0.28
        for _, _, component_width, component_height, _ in edge_stats[1:]
    )
    # A clean white or black balloon already provides its own professional
    # backdrop and should keep its original silhouette.
    if (
        not strong_boundary
        and texture <= 40.0
        and (luminance >= 185.0 or luminance <= 75.0)
    ):
        return False
    return True


def _text_style(region_pixels: np.ndarray) -> tuple[str, str | None]:
    luminance = float(cv2.cvtColor(region_pixels, cv2.COLOR_RGB2GRAY).mean())
    if luminance >= 160.0:
        return "black", None
    if luminance <= 96.0:
        return "white", None
    return "white", "black"


def _is_cjk_character(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x3040 <= codepoint <= 0x30FF
        or 0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
    )


def _normalize_display_text(
    text: str,
    region_type: str | None = None,
) -> str:
    normalized = text
    for source, replacement in _MOJIBAKE_REPLACEMENTS.items():
        normalized = normalized.replace(source, replacement)
    normalized = normalized.replace("<3", _VECTOR_HEART)
    normalized = unicodedata.normalize("NFKC", normalized)
    normalized = "".join(
        _COMMON_GLYPH_REPLACEMENTS.get(character, character)
        for character in normalized
        if not _is_cjk_character(character)
    )
    if region_type == "sfx":
        normalized = normalized.replace("*", "")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = re.sub(r"\s+([,.;:!?])", r"\1", normalized)
    return normalized


def _font_size(
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
) -> int:
    return int(getattr(font, "size", _MIN_FONT_SIZE))


def _symbol_advance(
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    symbol: str,
) -> int:
    ratio = 0.78 if symbol == _VECTOR_HEART else 0.62
    return max(4, round(_font_size(font) * ratio))


def _text_length(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
) -> float:
    width = 0.0
    segment = ""
    for character in text:
        if character not in _VECTOR_SYMBOLS:
            segment += character
            continue
        if segment:
            width += float(draw.textlength(segment, font=font))
            segment = ""
        width += _symbol_advance(font, character)
    if segment:
        width += float(draw.textlength(segment, font=font))
    return width


def _line_height(
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
) -> int:
    bounds = font.getbbox("Ag")
    return max(_font_size(font), bounds[3] - bounds[1])


def _wrapped_bounds(
    draw: ImageDraw.ImageDraw,
    wrapped: str,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    spacing: int,
) -> tuple[int, int, int, int]:
    lines = wrapped.splitlines() or [wrapped]
    width = ceil(max((_text_length(draw, line, font) for line in lines), default=0))
    height = _line_height(font) * len(lines) + spacing * max(0, len(lines) - 1)
    return 0, 0, width, height


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
            if not current or _text_length(draw, candidate, font) <= max_width:
                current = candidate
                continue
            lines.append(current)
            current = word
        if current:
            lines.append(current)
    return "\n".join(lines)


def _wrap_is_readable(wrapped: str, max_lines: int | None) -> bool:
    lines = [line for line in wrapped.splitlines() if line]
    if max_lines is not None and len(lines) > max_lines:
        return False
    if len(lines) < 5:
        return True
    single_word_lines = sum(len(line.split()) == 1 for line in lines)
    return single_word_lines / len(lines) <= 0.55


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    box_width: int,
    box_height: int,
    *,
    min_font_size: int = _MIN_FONT_SIZE,
    max_font_size: int = _MAX_FONT_SIZE,
    max_lines: int | None = None,
    require_balanced_wrap: bool = False,
) -> tuple[
    ImageFont.ImageFont | ImageFont.FreeTypeFont,
    str,
    tuple[int, int, int, int],
    int,
]:
    padding = max(4, min(box_width, box_height) // 12)
    available_width = max(1, box_width - 2 * padding)
    available_height = max(1, box_height - 2 * padding)
    minimum_size = max(_MIN_FONT_SIZE, min_font_size)
    largest_size = min(
        max_font_size,
        max(minimum_size, box_height // 3),
    )
    for size in range(largest_size, minimum_size - 1, -1):
        font = _load_font(size)
        spacing = max(2, size // 4)
        wrapped = _wrap_text(
            draw,
            text,
            font,
            available_width,
        )
        if require_balanced_wrap and not _wrap_is_readable(wrapped, max_lines):
            continue
        if not require_balanced_wrap and max_lines is not None:
            if len(wrapped.splitlines()) > max_lines:
                continue
        bounds = _wrapped_bounds(draw, wrapped, font, spacing)
        if (
            bounds[2] - bounds[0] <= available_width
            and bounds[3] - bounds[1] <= available_height
        ):
            return font, wrapped, bounds, spacing
    raise ResultBuildError("Translated text does not fit inside its region.")


def _desired_min_font_size(
    width: int,
    height: int,
    region_type: str,
) -> int:
    ratio = _REGION_MIN_FONT_RATIOS.get(region_type, 0.011)
    return max(_MIN_FONT_SIZE, round(min(width, height) * ratio))


def _preferred_min_font_size(
    width: int,
    height: int,
    region_type: str,
) -> int:
    ratio = _REGION_PREFERRED_MIN_FONT_RATIOS.get(region_type, 0.0095)
    return max(
        _desired_min_font_size(width, height, region_type),
        round(min(width, height) * ratio),
    )


def _maximum_font_size(
    width: int,
    height: int,
    region_type: str,
) -> int:
    ratio = _REGION_MAX_FONT_RATIOS.get(region_type, 0.016)
    hard_limit = 80 if region_type == "title" else _MAX_FONT_SIZE
    return max(
        _preferred_min_font_size(width, height, region_type),
        min(hard_limit, round(min(width, height) * ratio)),
    )


def _box_area(box: tuple[int, int, int, int]) -> int:
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def _intersection_area(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> int:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    return max(0, right - left) * max(0, bottom - top)


def _scaled_box(
    box: tuple[int, int, int, int],
    width: int,
    height: int,
    width_factor: float,
    height_factor: float,
) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    target_width = min(width, max(1, round((right - left) * width_factor)))
    target_height = min(
        height,
        max(1, round((bottom - top) * height_factor)),
    )
    new_left = round(center_x - target_width / 2)
    new_top = round(center_y - target_height / 2)
    new_left = max(0, min(width - target_width, new_left))
    new_top = max(0, min(height - target_height, new_top))
    return (
        new_left,
        new_top,
        new_left + target_width,
        new_top + target_height,
    )


def _candidate_overlaps_other_regions(
    candidate: tuple[int, int, int, int],
    other_boxes: list[tuple[int, int, int, int]],
) -> bool:
    candidate_area = max(1, _box_area(candidate))
    for other in other_boxes:
        overlap = _intersection_area(candidate, other)
        if overlap <= 0:
            continue
        if overlap / min(candidate_area, max(1, _box_area(other))) > 0.15:
            return True
    return False


def _candidate_background_is_safe(
    source_pixels: np.ndarray,
    base_box: tuple[int, int, int, int],
    candidate: tuple[int, int, int, int],
) -> bool:
    if candidate == base_box:
        return True
    left, top, right, bottom = candidate
    crop = source_pixels[top:bottom, left:right]
    if crop.size == 0:
        return False
    base_left = max(0, base_box[0] - left)
    base_top = max(0, base_box[1] - top)
    base_right = min(right - left, base_box[2] - left)
    base_bottom = min(bottom - top, base_box[3] - top)
    ring_mask = np.ones(crop.shape[:2], dtype=bool)
    ring_mask[base_top:base_bottom, base_left:base_right] = False
    ring_pixels = crop[ring_mask]
    if ring_pixels.size == 0:
        return True
    base_pixels = source_pixels[
        base_box[1] : base_box[3],
        base_box[0] : base_box[2],
    ]
    if base_pixels.size == 0:
        return False
    background = np.median(base_pixels.reshape(-1, 3), axis=0)
    color_distance = np.linalg.norm(
        ring_pixels.astype(np.float32) - background.astype(np.float32),
        axis=1,
    )
    compatible_ratio = float((color_distance <= 78.0).mean())
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 80, 160) > 0
    edge_density = float(edges[ring_mask].mean())
    return compatible_ratio >= 0.52 and edge_density <= 0.22


def _placement_candidates(
    box: tuple[int, int, int, int],
    width: int,
    height: int,
    region_type: str,
) -> list[tuple[int, int, int, int]]:
    if region_type == "title":
        factors = ((1.0, 1.0), (1.08, 1.04), (1.16, 1.08))
    else:
        factors = (
            (1.0, 1.0),
            (1.08, 1.03),
            (1.16, 1.06),
            (1.25, 1.10),
        )
    candidates: list[tuple[int, int, int, int]] = []
    for width_factor, height_factor in factors:
        candidate = _scaled_box(
            box,
            width,
            height,
            width_factor,
            height_factor,
        )
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _choose_region_layout(
    draw: ImageDraw.ImageDraw,
    source_pixels: np.ndarray,
    region: TranslationRegion,
    width: int,
    height: int,
    other_boxes: list[tuple[int, int, int, int]],
) -> tuple[
    tuple[int, int, int, int],
    ImageFont.ImageFont | ImageFont.FreeTypeFont,
    str,
    tuple[int, int, int, int],
    int,
]:
    region_type = region.region_type or "dialogue"
    display_text = _normalize_display_text(region.translated_text, region_type)
    if not display_text:
        raise ResultBuildError("Translated text is empty after normalization.")
    base_box = _placement_pixel_box(region, width, height)
    minimum_size = _desired_min_font_size(width, height, region_type)
    preferred_minimum = _preferred_min_font_size(width, height, region_type)
    max_lines = _REGION_MAX_LINES.get(region_type)
    maximum_size = _maximum_font_size(width, height, region_type)
    candidates = _placement_candidates(
        base_box,
        width,
        height,
        region_type,
    )
    # The model-provided placement box is already the largest area declared
    # safe for typesetting. Prefer a slightly smaller font inside it instead
    # of growing the text block over nearby artwork.
    for candidate, candidate_minimum in (
        (base_box, preferred_minimum),
        (base_box, minimum_size),
    ):
        try:
            font, wrapped, bounds, spacing = _fit_text(
                draw,
                display_text,
                candidate[2] - candidate[0],
                candidate[3] - candidate[1],
                min_font_size=candidate_minimum,
                max_font_size=maximum_size,
                max_lines=max_lines,
                require_balanced_wrap=region_type in {"dialogue", "caption"},
            )
        except ResultBuildError:
            continue
        return candidate, font, wrapped, bounds, spacing

    # Expand only as a last resort, in small increments, and only across
    # background that looks compatible and does not overlap another region.
    for candidate in candidates[1:]:
        if (
            not _candidate_background_is_safe(
                source_pixels,
                base_box,
                candidate,
            )
        ):
            continue
        if _candidate_overlaps_other_regions(
            candidate,
            other_boxes,
        ):
            continue
        try:
            font, wrapped, bounds, spacing = _fit_text(
                draw,
                display_text,
                candidate[2] - candidate[0],
                candidate[3] - candidate[1],
                min_font_size=minimum_size,
                max_font_size=maximum_size,
                max_lines=max_lines,
                require_balanced_wrap=region_type in {"dialogue", "caption"},
            )
        except ResultBuildError:
            continue
        return candidate, font, wrapped, bounds, spacing
    raise ResultBuildError("Translated text does not fit inside its safe region.")


def _draw_vector_symbol(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    symbol: str,
    fill: str | tuple[int, int, int],
    stroke_fill: str | tuple[int, int, int] | None,
) -> None:
    size = _font_size(font)
    width = _symbol_advance(font, symbol)
    height = _line_height(font)
    stroke = max(1, size // 24) if stroke_fill is not None else 0

    def draw_symbol(
        color: str | tuple[int, int, int],
        inset: int,
    ) -> None:
        left = x + inset
        top = y + max(1, round(height * 0.12)) + inset
        right = x + width - inset
        bottom = y + height - inset
        if right <= left or bottom <= top:
            return
        if symbol == _VECTOR_HEART:
            points: list[tuple[float, float]] = []
            for point_index in range(49):
                angle = point_index * 2 * np.pi / 48
                raw_x = 16 * np.sin(angle) ** 3
                raw_y = (
                    13 * np.cos(angle)
                    - 5 * np.cos(2 * angle)
                    - 2 * np.cos(3 * angle)
                    - np.cos(4 * angle)
                )
                points.append(
                    (
                        left + (raw_x + 17) / 34 * (right - left),
                        top + (12 - raw_y) / 29 * (bottom - top),
                    )
                )
            draw.line(
                points,
                fill=color,
                width=max(2, round(size * 0.075)),
                joint="curve",
            )
            return
        note_width = max(2, round((right - left) * 0.48))
        stem_x = left + note_width
        note_bottom = bottom - max(1, round(height * 0.08))
        draw.ellipse(
            (
                left,
                note_bottom - max(3, round(height * 0.25)),
                left + note_width,
                note_bottom,
            ),
            fill=color,
        )
        line_width = max(2, round(size * 0.08))
        draw.line(
            (stem_x, note_bottom - 2, stem_x, top),
            fill=color,
            width=line_width,
        )
        draw.polygon(
            (
                (stem_x, top),
                (right, top + height * 0.12),
                (stem_x, top + height * 0.32),
            ),
            fill=color,
        )

    if stroke_fill is not None:
        draw_symbol(stroke_fill, -stroke)
    draw_symbol(fill, stroke)


def _draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    position: tuple[float, float],
    wrapped: str,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    fill: str | tuple[int, int, int],
    spacing: int,
    block_width: int,
    stroke_fill: str | tuple[int, int, int] | None = None,
) -> None:
    origin_x, origin_y = position
    line_height = _line_height(font)
    glyph_top = font.getbbox("Ag")[1]
    stroke_width = max(1, _font_size(font) // 24) if stroke_fill else 0
    for line_index, line in enumerate(wrapped.splitlines() or [wrapped]):
        line_width = _text_length(draw, line, font)
        cursor_x = origin_x + (block_width - line_width) / 2
        line_y = origin_y + line_index * (line_height + spacing)
        segment = ""
        for character in line:
            if character not in _VECTOR_SYMBOLS:
                segment += character
                continue
            if segment:
                draw.text(
                    (cursor_x, line_y - glyph_top),
                    segment,
                    font=font,
                    fill=fill,
                    stroke_width=stroke_width,
                    stroke_fill=stroke_fill,
                )
                cursor_x += _text_length(draw, segment, font)
                segment = ""
            _draw_vector_symbol(
                draw,
                cursor_x,
                line_y,
                font,
                character,
                fill,
                stroke_fill,
            )
            cursor_x += _symbol_advance(font, character)
        if segment:
            draw.text(
                (cursor_x, line_y - glyph_top),
                segment,
                font=font,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill,
            )


def _apply_translucent_backdrop(
    image: Image.Image,
    box: tuple[int, int, int, int],
    color: tuple[int, int, int],
    *,
    rounded: bool,
    alpha: int = 232,
) -> Image.Image:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    radius = max(4, min(box[2] - box[0], box[3] - box[1]) // 8)
    if rounded:
        overlay_draw.rounded_rectangle(
            box,
            radius=radius,
            fill=(*color, alpha),
        )
    else:
        overlay_draw.rectangle(box, fill=(*color, alpha))
    base = image.convert("RGBA")
    combined = Image.alpha_composite(base, overlay).convert("RGB")
    base.close()
    overlay.close()
    return combined


def _compact_backdrop_box(
    plan: _RegionPlan,
    text_x: int,
    text_y: int,
    box_width: int,
    box_height: int,
) -> tuple[int, int, int, int]:
    padding = max(4, min(12, round(_font_size(plan.font) * 0.24)))
    text_width = plan.bounds[2] - plan.bounds[0]
    text_height = plan.bounds[3] - plan.bounds[1]
    left = text_x - padding
    top = text_y - padding
    right = text_x + text_width + padding
    bottom = text_y + text_height + padding
    return (
        max(0, left),
        max(0, top),
        min(box_width - 1, right),
        min(box_height - 1, bottom),
    )


def _sfx_candidate_boxes(
    source_box: tuple[int, int, int, int],
    label_width: int,
    label_height: int,
    page_width: int,
    page_height: int,
) -> list[tuple[int, int, int, int]]:
    left, top, right, bottom = source_box
    center_x = (left + right) // 2
    center_y = (top + bottom) // 2
    gap = max(6, round(min(page_width, page_height) * 0.004))
    raw = (
        (center_x - label_width // 2, top - gap - label_height),
        (center_x - label_width // 2, bottom + gap),
        (left - gap - label_width, center_y - label_height // 2),
        (right + gap, center_y - label_height // 2),
        (left, top - gap - label_height),
        (right - label_width, bottom + gap),
    )
    candidates: list[tuple[int, int, int, int]] = []
    for candidate_left, candidate_top in raw:
        candidate = (
            candidate_left,
            candidate_top,
            candidate_left + label_width,
            candidate_top + label_height,
        )
        if (
            candidate[0] < 2
            or candidate[1] < 2
            or candidate[2] > page_width - 2
            or candidate[3] > page_height - 2
        ):
            continue
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _render_sfx_annotations(
    image: Image.Image,
    source_pixels: np.ndarray,
    regions: list[TranslationRegion],
    occupied_boxes: list[tuple[int, int, int, int]],
) -> None:
    page_width, page_height = image.size
    short_edge = min(page_width, page_height)
    desired_size = max(_MIN_FONT_SIZE, round(short_edge * 0.0105))
    max_label_width = max(120, round(page_width * 0.18))
    max_label_height = max(60, desired_size * 4)
    measure_image = Image.new("RGB", (8, 8), "white")
    measure_draw = ImageDraw.Draw(measure_image)
    seen: list[tuple[str, float, float]] = []
    rendered_count = 0
    rendered_per_text: dict[str, int] = {}
    for region in regions:
        if rendered_count >= 8:
            break
        display_text = _normalize_display_text(region.translated_text, "sfx")
        if not display_text:
            continue
        normalized_key = display_text.casefold()
        if rendered_per_text.get(normalized_key, 0) >= 2:
            continue
        source_box = _pixel_box(region, page_width, page_height)
        center_x = (source_box[0] + source_box[2]) / 2
        center_y = (source_box[1] + source_box[3]) / 2
        duplicate_distance = short_edge * 0.10
        if any(
            previous_text.casefold() == display_text.casefold()
            and ((center_x - previous_x) ** 2 + (center_y - previous_y) ** 2)
            ** 0.5
            < duplicate_distance
            for previous_text, previous_x, previous_y in seen
        ):
            continue
        try:
            font, wrapped, bounds, spacing = _fit_text(
                measure_draw,
                display_text,
                max_label_width,
                max_label_height,
                min_font_size=desired_size,
                max_font_size=min(42, desired_size + 8),
                max_lines=2,
            )
        except ResultBuildError:
            continue
        padding_x = max(8, _font_size(font) // 2)
        padding_y = max(5, _font_size(font) // 4)
        label_width = bounds[2] - bounds[0] + 2 * padding_x
        label_height = bounds[3] - bounds[1] + 2 * padding_y
        candidates = _sfx_candidate_boxes(
            source_box,
            label_width,
            label_height,
            page_width,
            page_height,
        )
        best_box: tuple[int, int, int, int] | None = None
        best_score: float | None = None
        for candidate in candidates:
            candidate_area = max(1, _box_area(candidate))
            occupied_overlap = sum(
                _intersection_area(candidate, occupied)
                for occupied in occupied_boxes
            )
            if occupied_overlap / candidate_area > 0.18:
                continue
            crop = source_pixels[
                candidate[1] : candidate[3],
                candidate[0] : candidate[2],
            ]
            texture = (
                float(cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY).std())
                if crop.size
                else 255.0
            )
            distance = (
                ((candidate[0] + candidate[2]) / 2 - center_x) ** 2
                + ((candidate[1] + candidate[3]) / 2 - center_y) ** 2
            ) ** 0.5
            score = occupied_overlap * 10 + texture * 2 + distance
            if best_score is None or score < best_score:
                best_score = score
                best_box = candidate
        if best_box is None:
            continue
        label = image.crop(best_box)
        background = (250, 249, 246)
        fill = (24, 24, 24)
        replaced = _apply_translucent_backdrop(
            label,
            (0, 0, label.width - 1, label.height - 1),
            background,
            rounded=True,
            alpha=226,
        )
        label.close()
        label = replaced
        label_draw = ImageDraw.Draw(label)
        _draw_wrapped_text(
            label_draw,
            (padding_x, padding_y),
            wrapped,
            font,
            fill,
            spacing,
            bounds[2] - bounds[0],
        )
        image.paste(label, (best_box[0], best_box[1]))
        label.close()
        occupied_boxes.append(best_box)
        seen.append((display_text, center_x, center_y))
        rendered_per_text[normalized_key] = (
            rendered_per_text.get(normalized_key, 0) + 1
        )
        rendered_count += 1
    measure_image.close()


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
            source_pixels = np.asarray(image, dtype=np.uint8).copy()
            measure_image = Image.new("RGB", (8, 8), "white")
            measure_draw = ImageDraw.Draw(measure_image)
            main_regions = [
                region
                for region in translation.regions
                if (region.region_type or "dialogue") != "sfx"
                and _normalize_display_text(
                    region.translated_text,
                    region.region_type or "dialogue",
                )
            ]
            initial_boxes = [
                _placement_pixel_box(region, image.width, image.height)
                for region in main_regions
            ]
            layouts: list[
                tuple[
                    TranslationRegion,
                    tuple[int, int, int, int],
                    tuple[int, int, int, int],
                    ImageFont.ImageFont | ImageFont.FreeTypeFont,
                    str,
                    tuple[int, int, int, int],
                    int,
                ]
            ] = []
            for index, region in enumerate(main_regions):
                other_boxes = [
                    box
                    for other_index, box in enumerate(initial_boxes)
                    if other_index != index
                ]
                placement_box, font, wrapped, bounds, spacing = (
                    _choose_region_layout(
                        measure_draw,
                        source_pixels,
                        region,
                        image.width,
                        image.height,
                        other_boxes,
                    )
                )
                layouts.append(
                    (
                        region,
                        _pixel_box(region, image.width, image.height),
                        placement_box,
                        font,
                        wrapped,
                        bounds,
                        spacing,
                    )
                )

            page_mask = np.zeros(
                (image.height, image.width),
                dtype=np.uint8,
            )
            plans: list[_RegionPlan] = []

            # Build one union mask first. This prevents a later overlapping
            # region from erasing Indonesian text drawn for an earlier one.
            for (
                region,
                source_box,
                placement_box,
                font,
                wrapped,
                bounds,
                spacing,
            ) in layouts:
                region_type = region.region_type or "dialogue"
                source_padding = max(
                    _MIN_SOURCE_PADDING,
                    min(
                        _MAX_SOURCE_PADDING,
                        round(
                            min(image.width, image.height)
                            * _SOURCE_PADDING_PAGE_RATIO
                        ),
                    ),
                )
                padded_source_box = _expand_box(
                    source_box,
                    image.width,
                    image.height,
                    source_padding,
                )
                # Erase only the detected source text plus a conservative
                # margin. The wider placement box may contain panel artwork.
                mask_target_box = padded_source_box
                target_width = mask_target_box[2] - mask_target_box[0]
                target_height = mask_target_box[3] - mask_target_box[1]
                margin = _analysis_margin(target_width, target_height)
                analysis_box = _expand_box(
                    mask_target_box,
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
                    mask_target_box[0] - crop_left,
                    mask_target_box[1] - crop_top,
                    mask_target_box[2] - crop_left,
                    mask_target_box[3] - crop_top,
                )
                if region_type == "title":
                    local_mask = np.zeros(
                        region_pixels.shape[:2],
                        dtype=np.uint8,
                    )
                    local_mask.fill(0)
                    mask_succeeded = False
                else:
                    local_mask, mask_succeeded = _source_text_mask(
                        region_pixels,
                        content_box,
                    )
                page_mask[crop_top:crop_bottom, crop_left:crop_right] = (
                    np.maximum(
                        page_mask[
                            crop_top:crop_bottom,
                            crop_left:crop_right,
                        ],
                        local_mask,
                    )
                )
                plans.append(
                    _RegionPlan(
                        region=region,
                        placement_box=placement_box,
                        mask_succeeded=mask_succeeded,
                        font=font,
                        wrapped=wrapped,
                        bounds=bounds,
                        spacing=spacing,
                    )
                )

            if np.any(page_mask):
                erased_pixels = cv2.inpaint(
                    source_pixels,
                    page_mask,
                    5,
                    cv2.INPAINT_TELEA,
                )
                image.close()
                image = Image.fromarray(erased_pixels)

            occupied_boxes = [plan.placement_box for plan in plans]
            for plan in plans:
                region = plan.region
                left, top, right, bottom = plan.placement_box
                box_width = right - left
                box_height = bottom - top
                text_layer = image.crop((left, top, right, bottom))
                text_pixels = np.asarray(text_layer, dtype=np.uint8)
                text_width = plan.bounds[2] - plan.bounds[0]
                text_height = plan.bounds[3] - plan.bounds[1]
                text_x = (box_width - text_width) // 2
                text_y = (box_height - text_height) // 2
                if _needs_backdrop(
                    region,
                    text_pixels,
                    plan.mask_succeeded,
                ):
                    region_type = region.region_type or "dialogue"
                    color = (
                        (255, 255, 255)
                        if region_type == "caption"
                        else _backdrop_color(text_pixels)
                    )
                    backdrop_box = _compact_backdrop_box(
                        plan,
                        text_x,
                        text_y,
                        box_width,
                        box_height,
                    )
                    replaced = _apply_translucent_backdrop(
                        text_layer,
                        backdrop_box,
                        color,
                        rounded=region_type in {"dialogue", "title"},
                        alpha=202
                        if region_type == "title"
                        else 220,
                    )
                    text_layer.close()
                    text_layer = replaced
                    text_pixels = np.asarray(text_layer, dtype=np.uint8)
                fill, stroke_fill = _text_style(text_pixels)
                text_draw = ImageDraw.Draw(text_layer)
                _draw_wrapped_text(
                    text_draw,
                    (text_x, text_y),
                    plan.wrapped,
                    plan.font,
                    fill,
                    plan.spacing,
                    text_width,
                    stroke_fill,
                )
                image.paste(text_layer, (left, top))
                text_layer.close()

            _render_sfx_annotations(
                image,
                source_pixels,
                [
                    region
                    for region in translation.regions
                    if (region.region_type or "dialogue") == "sfx"
                ],
                occupied_boxes,
            )
            image.save(destination, format="PNG", compress_level=6)
            measure_image.close()
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
    added_pages = 0
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        for page_path in page_paths:
            with Image.open(page_path) as opened:
                short_edge = min(opened.size)
                long_edge = max(opened.size)
                if (
                    short_edge <= _THIN_PAGE_MAX_SHORT_EDGE
                    and short_edge / max(1, long_edge)
                    < _THIN_PAGE_ASPECT_RATIO
                ):
                    logger.info(
                        json.dumps(
                            {
                                "event": "result_page_skipped",
                                "pagePath": str(page_path),
                                "width": opened.width,
                                "height": opened.height,
                                "reason": "thin_artifact",
                            }
                        )
                    )
                    continue
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
            added_pages += 1
        if added_pages == 0:
            raise ResultBuildError("A result PDF requires a meaningful page.")
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
