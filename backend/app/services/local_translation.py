"""Local OCR/translation provider used by the Celery worker."""

import base64
import json
import math
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image
from pydantic import ValidationError

from app.services.manga_translation import (
    TranslationError,
    PageTranslation,
    TranslationRegion,
    _map_tile_translation,
    _merge_tile_regions,
    _prepare_tile_cache,
    _read_cached_tile,
    _tile_cache_manifest,
    _tile_spans,
    _write_cached_tile,
)
from app.core.languages import MODEL_VERSIONS, SourceLanguage
from app.services.indonesian_style import DIALOGUE_STYLE_VERSION
from app.services.translation_memory import TranslationMemoryStore


LOCAL_LAYOUT_VERSION = "local-layout-v3"


class LocalTranslationError(TranslationError):
    """Error raised by the local AI HTTP service."""


def detect_source_language(
    preview_pages: list[Path], *, base_url: str, timeout_seconds: float = 600.0,
    max_image_bytes: int = 16 * 1024 * 1024,
    before_sample: Callable[[], None] | None = None,
) -> SourceLanguage:
    votes: list[str] = []
    # Include an interior page so an untranslated cover does not choose the OCR.
    indices = dict.fromkeys(index for index in (0, len(preview_pages) // 2, 1, 2, len(preview_pages) - 1)
                            if 0 <= index < len(preview_pages))
    for index in indices:
        if before_sample is not None:
            before_sample()
        try:
            with Image.open(preview_pages[index]) as opened:
                if opened.format != "PNG":
                    raise ValueError("Invalid preview format.")
                height = min(opened.height, opened.width * 2)
                top = (opened.height - height) // 2
                with opened.crop((0, top, opened.width, top + height)).convert("RGB") as sample:
                    sample.thumbnail((1600, 2400))
                    with BytesIO() as buffer:
                        sample.save(buffer, format="PNG")
                        data = buffer.getvalue()
            if len(data) > max_image_bytes:
                raise ValueError("Language sample exceeds local AI input limit.")
            response = _post_json(
                f"{base_url.rstrip('/')}/detect-language",
                {"image_base64": base64.b64encode(data).decode("ascii")},
                timeout_seconds=timeout_seconds,
            )
        except LocalTranslationError as error:
            if error.retryable or error.code == "AI_MODEL_NOT_READY":
                raise
            raise LocalTranslationError("Language detection failed.", code="AI_LANGUAGE_DETECTION_FAILED") from error
        except (OSError, ValueError) as error:
            raise LocalTranslationError("Invalid language sample.", code="AI_LANGUAGE_DETECTION_FAILED") from error
        language = response.get("source_language")
        confidence = response.get("confidence")
        if (
            "source_language" not in response or "model_version" not in response
            or type(confidence) not in (int, float) or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
            or (language is not None and (not isinstance(language, str) or language not in MODEL_VERSIONS))
            or response.get("model_version") != MODEL_VERSIONS.get(language)
            or (language is None and confidence != 0)
        ):
            raise LocalTranslationError("Invalid language detection response.", code="AI_LANGUAGE_DETECTION_FAILED")
        if language is None or confidence < 0.6:
            continue
        votes.append(language)
        if len(set(votes)) > 1:
            break
        if len(votes) >= 2 or len(preview_pages) == 1:
            return language
    raise LocalTranslationError("Source language is uncertain or mixed.", code="AI_LANGUAGE_DETECTION_FAILED")


def _error_code(error: HTTPError, max_response_bytes: int) -> str | None:
    try:
        payload = json.loads(error.read(max_response_bytes))
        detail = payload.get("detail")
        if isinstance(detail, dict) and isinstance(detail.get("code"), str):
            return detail["code"]
    except (AttributeError, OSError, TypeError, ValueError, json.JSONDecodeError):
        pass
    return None


def _post_json(url: str, payload: dict[str, Any], *, timeout_seconds: float, max_response_bytes: int = 4 * 1024 * 1024) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            body = response.read(max_response_bytes + 1)
            status = getattr(response, "status", 200)
    except HTTPError as error:
        code = _error_code(error, max_response_bytes)
        retryable = code != "AI_MODEL_NOT_READY" and (error.code in {408, 429} or 500 <= error.code < 600)
        try:
            retry_after = max(0.0, float(error.headers.get("Retry-After", "0")))
        except (ValueError, TypeError, AttributeError):
            retry_after = None
        raise LocalTranslationError(
            "Local AI service returned an error.",
            http_status=error.code,
            retryable=retryable,
            code=code,
            retry_after_seconds=retry_after,
        ) from error
    except (URLError, TimeoutError, OSError) as error:
        raise LocalTranslationError("Local AI service is unavailable.", retryable=True) from error
    if status >= 400:
        raise LocalTranslationError("Local AI service returned an error.", http_status=status, retryable=status >= 500)
    if len(body) > max_response_bytes:
        raise LocalTranslationError("Local AI response exceeds the size limit.")
    try:
        decoded = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LocalTranslationError("Local AI returned invalid JSON.") from error
    if not isinstance(decoded, dict):
        raise LocalTranslationError("Local AI returned an invalid response.")
    return decoded


class LocalPageTranslator:
    def __init__(self, *, base_url: str, session_factory, timeout_seconds: float = 600.0, max_image_bytes: int = 16 * 1024 * 1024, source_language: str = "ja", target_language: str = "id", max_tile_aspect_ratio: float = 2.0, tile_overlap_ratio: float = 0.2) -> None:
        if not base_url.strip():
            raise ValueError("LOCAL_AI_URL is not configured.")
        if source_language not in MODEL_VERSIONS or target_language != "id":
            raise ValueError("Unsupported language pair for local translation.")
        self.model_version = MODEL_VERSIONS[source_language]
        self.engine_version = f"{self.model_version}+{DIALOGUE_STYLE_VERSION}+{LOCAL_LAYOUT_VERSION}"
        if timeout_seconds <= 0 or max_image_bytes <= 0:
            raise ValueError("Request limits must be positive.")
        if not 1 <= max_tile_aspect_ratio <= 4 or not 0.05 <= tile_overlap_ratio <= 0.4:
            raise ValueError("Invalid tile geometry.")
        self.base_url = base_url.rstrip("/")
        self.session_factory = session_factory
        self.timeout_seconds = timeout_seconds
        self.max_image_bytes = max_image_bytes
        self.source_language = source_language
        self.target_language = target_language
        self.max_tile_aspect_ratio = max_tile_aspect_ratio
        self.tile_overlap_ratio = tile_overlap_ratio
        self.memory = TranslationMemoryStore(session_factory, source_language=source_language)

    def translate_page(self, page_path: Path, *, quality_reason: str | None = None, tile_cache_directory: Path | None = None) -> PageTranslation:
        image = self._read_page_image(page_path)
        try:
            spans = _tile_spans(image.width, image.height, self.max_tile_aspect_ratio, self.tile_overlap_ratio)
            cache_enabled = len(spans) > 1 and tile_cache_directory is not None
            if cache_enabled:
                cache_enabled = _prepare_tile_cache(tile_cache_directory, _tile_cache_manifest(
                    page_path, image, spans, model=self.engine_version, max_tile_aspect_ratio=self.max_tile_aspect_ratio,
                    tile_overlap_ratio=self.tile_overlap_ratio, quality_reason=quality_reason,
                ))
            mapped = []
            for index, (top, bottom) in enumerate(spans, start=1):
                cache_path = tile_cache_directory / f"tile-{index:04d}-{top}-{bottom}.json" if cache_enabled else None
                translation = _read_cached_tile(cache_path) if cache_path is not None else None
                if translation is not None and translation.engine_version != self.engine_version:
                    translation = None
                if translation is None:
                    tile = image.crop((0, top, image.width, bottom))
                    try:
                        translation = self._translate_tile(tile, quality_reason=quality_reason)
                    finally:
                        tile.close()
                    if cache_path is not None:
                        _write_cached_tile(cache_path, translation)
                if len(spans) == 1:
                    return translation
                mapped.extend(_map_tile_translation(translation, tile_top=top, tile_bottom=bottom, page_height=image.height))
            merged = _merge_tile_regions(mapped)
            merged.engine_version = self.engine_version
            return merged
        finally:
            image.close()

    def _translate_tile(self, image: Image.Image, *, quality_reason: str | None) -> PageTranslation:
        image_data = self._encode_image(image)
        ocr_response = _post_json(
            f"{self.base_url}/ocr",
            {"image_base64": base64.b64encode(image_data).decode("ascii"), "source_language": self.source_language, "quality_reason": quality_reason},
            timeout_seconds=self.timeout_seconds,
        )
        raw_regions = ocr_response.get("regions")
        if not isinstance(raw_regions, list) or len(raw_regions) > 80:
            raise LocalTranslationError("Local OCR response omitted regions.")
        if ocr_response.get("model_version") != self.model_version:
            raise LocalTranslationError("Local OCR model version does not match the worker.")
        regions: list[TranslationRegion] = []
        missing: list[tuple[int, str]] = []
        for raw in raw_regions:
            try:
                if not isinstance(raw, dict) or raw.get("source_language") != self.source_language:
                    raise ValueError("Invalid OCR region or language.")
                region = TranslationRegion.model_validate({**raw, "translated_text": "pending"})
            except (ValidationError, ValueError, TypeError) as error:
                raise LocalTranslationError("Local OCR returned an invalid region.") from error
            source_text = region.source_text
            translated = self.memory.resolve(
                source_text,
                region_type=region.region_type or "dialogue",
            )
            if translated is None:
                missing.append((len(regions), source_text.strip()))
                translated = source_text.strip()
            regions.append(TranslationRegion.model_validate({**region.model_dump(), "translated_text": translated}))
        if missing:
            unique = list(dict.fromkeys(text for _, text in missing))
            positions = {text: [index for index, value in missing if value == text] for text in unique}
            for start in range(0, len(unique), 16):
                batch = unique[start:start+16]
                response = _post_json(
                    f"{self.base_url}/translate",
                    {"texts": batch, "source_language": self.source_language, "target_language": "id"},
                    timeout_seconds=self.timeout_seconds,
                )
                values = response.get("translations")
                if response.get("model_version") != self.model_version or not isinstance(values, list) or len(values) != len(batch):
                    raise LocalTranslationError("Local translation response does not match OCR regions.")
                if any(not isinstance(v, str) or not v.strip() or len(v) > 1000 for v in values):
                    raise LocalTranslationError("Local translator returned invalid text.")
                for source_text, value in zip(batch, values):
                    translations_by_type: dict[str, str] = {}
                    for index in positions[source_text]:
                        region_type = regions[index].region_type or "dialogue"
                        if region_type not in translations_by_type:
                            translations_by_type[region_type] = self.memory.remember(
                                source_text, value.strip(), region_type=region_type,
                            )
                        translated = translations_by_type[region_type]
                        regions[index] = TranslationRegion.model_validate({**regions[index].model_dump(), "translated_text": translated})
        return PageTranslation(regions=regions, engine_version=self.engine_version)

    def _read_page_image(self, page_path: Path) -> Image.Image:
        if page_path.suffix.lower() != ".png" or not page_path.is_file():
            raise LocalTranslationError("Preview image is missing or invalid.")
        try:
            with Image.open(page_path) as opened:
                if opened.format != "PNG" or opened.width < 1 or opened.height < 1:
                    raise OSError("invalid PNG")
                return opened.convert("RGB")
        except (OSError, ValueError) as error:
            raise LocalTranslationError("Preview image is missing or invalid.") from error

    def _encode_image(self, image: Image.Image) -> bytes:
        buffer = BytesIO()
        image.save(buffer, format="PNG", compress_level=6)
        data = buffer.getvalue()
        buffer.close()
        if not data or len(data) > self.max_image_bytes:
            raise LocalTranslationError("Preview image exceeds local AI input limit.")
        return data
