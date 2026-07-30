import json
import logging
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from PIL import Image
from pydantic import ValidationError

from app.services import manga_translation
from app.services.manga_translation import (
    GeminiPageTranslator,
    GeminiTranslationError,
    PageTranslation,
)


def make_page(path: Path) -> None:
    Image.new("RGB", (120, 160), "white").save(path, format="PNG")


def gemini_response(page_translation: dict) -> bytes:
    return json.dumps(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": json.dumps(page_translation)}]
                    }
                }
            ]
        }
    ).encode()


def test_page_translation_rejects_invalid_model_coordinates() -> None:
    with pytest.raises(ValidationError):
        PageTranslation.model_validate(
            {
                "regions": [
                    {
                        "box_2d": [500, 100, 400, 900],
                        "source_text": "こんにちは",
                        "translated_text": "Halo",
                    }
                ]
            }
        )


def test_page_translation_rejects_more_than_eighty_regions() -> None:
    region = {
        "box_2d": [100, 200, 400, 800],
        "source_text": "こんにちは",
        "translated_text": "Halo",
    }

    with pytest.raises(ValidationError):
        PageTranslation.model_validate({"regions": [region] * 81})


def test_page_translation_accepts_legacy_region_without_placement_metadata() -> None:
    translation = PageTranslation.model_validate(
        {
            "regions": [
                {
                    "box_2d": [100, 200, 400, 800],
                    "source_text": "\u3053\u3093\u306b\u3061\u306f",
                    "translated_text": "Halo",
                }
            ]
        }
    )

    assert translation.regions[0].placement_box_2d is None
    assert translation.regions[0].region_type is None


def test_page_translation_rejects_invalid_placement_coordinates() -> None:
    with pytest.raises(ValidationError):
        PageTranslation.model_validate(
            {
                "regions": [
                    {
                        "box_2d": [100, 200, 400, 800],
                        "placement_box_2d": [500, 200, 400, 800],
                        "region_type": "dialogue",
                        "source_text": "\u3053\u3093\u306b\u3061\u306f",
                        "translated_text": "Halo",
                    }
                ]
            }
        )


def test_gemini_translator_sends_bounded_structured_request(tmp_path: Path) -> None:
    page_path = tmp_path / "page.png"
    make_page(page_path)
    captured: dict[str, object] = {}

    def transport(request: Request, timeout: float, max_response_bytes: int) -> bytes:
        captured.update(
            request=request,
            timeout=timeout,
            max_response_bytes=max_response_bytes,
        )
        return gemini_response(
            {
                "regions": [
                    {
                        "box_2d": [100, 200, 400, 800],
                        "placement_box_2d": [80, 150, 450, 850],
                        "region_type": "dialogue",
                        "source_text": "こんにちは",
                        "translated_text": "Halo",
                    }
                ]
            }
        )

    translator = GeminiPageTranslator(
        api_key="test-key",
        model="gemini-3.6-flash",
        timeout_seconds=30,
        max_image_bytes=1_000_000,
        max_response_bytes=100_000,
        transport=transport,
    )

    result = translator.translate_page(page_path)

    assert result.regions[0].translated_text == "Halo"
    assert result.regions[0].placement_box_2d == (80, 150, 450, 850)
    assert result.regions[0].region_type == "dialogue"
    request = captured["request"]
    assert isinstance(request, Request)
    assert request.full_url.endswith(
        "/models/gemini-3.6-flash:generateContent"
    )
    assert request.get_header("X-goog-api-key") == "test-key"
    payload = json.loads(request.data or b"{}")
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    assert payload["generationConfig"]["maxOutputTokens"] > 0
    assert payload["generationConfig"]["responseJsonSchema"]["type"] == "object"
    serialized_schema = json.dumps(
        payload["generationConfig"]["responseJsonSchema"]
    )
    assert '"$defs"' not in serialized_schema
    assert '"$ref"' not in serialized_schema
    assert '"prefixItems"' not in serialized_schema
    assert '"default"' not in serialized_schema
    assert '"minLength"' not in serialized_schema
    assert '"maxLength"' not in serialized_schema
    regions_schema = payload["generationConfig"]["responseJsonSchema"][
        "properties"
    ]["regions"]
    assert "maxItems" not in regions_schema
    box_schema = regions_schema["items"]["properties"]["box_2d"]
    assert box_schema == {
        "type": "array",
        "items": {"type": "integer", "minimum": 0, "maximum": 1000},
        "minItems": 4,
        "maxItems": 4,
    }
    region_properties = regions_schema["items"]["properties"]
    assert region_properties["placement_box_2d"] == box_schema
    assert region_properties["region_type"] == {
        "type": "string",
        "enum": ["dialogue", "caption", "sfx", "title"],
    }
    assert regions_schema["items"]["required"] == [
        "box_2d",
        "placement_box_2d",
        "region_type",
        "source_text",
        "translated_text",
    ]
    assert payload["contents"][0]["parts"][0]["inline_data"]["mime_type"] == (
        "image/png"
    )
    prompt = payload["contents"][0]["parts"][1]["text"]
    assert "detect every visible Japanese string" in prompt
    assert "all sound effects or onomatopoeia" in prompt
    assert "glyph, outline, shadow, and punctuation mark" in prompt
    assert "same speech balloon into one dialogue region" in prompt
    assert "placement_box_2d" in prompt
    assert "should normally be larger than box_2d" in prompt
    assert "other placement boxes" in prompt
    assert "concise, natural Indonesian" in prompt
    assert captured["timeout"] == 30
    assert captured["max_response_bytes"] == 100_000


def test_gemini_http_error_logs_status_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def reject_request(_request: Request, timeout: float):
        del timeout
        raise HTTPError(
            url="https://generativelanguage.googleapis.com/test",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=BytesIO(b'{"error":{"message":"provider-body-secret"}}'),
        )

    monkeypatch.setattr(manga_translation, "urlopen", reject_request)
    request = Request(
        "https://generativelanguage.googleapis.com/test",
        headers={"x-goog-api-key": "fake-secret-key"},
    )

    with caplog.at_level(logging.WARNING):
        with pytest.raises(GeminiTranslationError, match="failed"):
            manga_translation._read_response(request, 30, 100_000)

    assert '"httpStatus": 400' in caplog.text
    assert "fake-secret-key" not in caplog.text
    assert "provider-body-secret" not in caplog.text


def test_gemini_http_429_is_retryable_and_respects_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_request(_request: Request, timeout: float):
        del timeout
        raise HTTPError(
            url="https://generativelanguage.googleapis.com/test",
            code=429,
            msg="Too Many Requests",
            hdrs={"Retry-After": "17"},
            fp=BytesIO(b'{"error":{"message":"quota exceeded"}}'),
        )

    monkeypatch.setattr(manga_translation, "urlopen", reject_request)
    request = Request("https://generativelanguage.googleapis.com/test")

    with pytest.raises(GeminiTranslationError) as captured:
        manga_translation._read_response(request, 30, 100_000)

    assert captured.value.http_status == 429
    assert captured.value.retryable is True
    assert captured.value.retry_after_seconds == 17


def test_gemini_http_429_reads_retry_delay_from_error_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_request(_request: Request, timeout: float):
        del timeout
        raise HTTPError(
            url="https://generativelanguage.googleapis.com/test",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=BytesIO(
                b'{"error":{"details":[{"retryDelay":"42.5s"}]}}'
            ),
        )

    monkeypatch.setattr(manga_translation, "urlopen", reject_request)
    request = Request("https://generativelanguage.googleapis.com/test")

    with pytest.raises(GeminiTranslationError) as captured:
        manga_translation._read_response(request, 30, 100_000)

    assert captured.value.retry_after_seconds == 42.5


def test_gemini_translator_retries_transient_error_then_succeeds(
    tmp_path: Path,
) -> None:
    page_path = tmp_path / "page.png"
    make_page(page_path)
    calls = 0
    sleeps: list[float] = []

    def transport(_request: Request, _timeout: float, _limit: int) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise GeminiTranslationError(
                "Gemini request failed.",
                http_status=429,
                retryable=True,
                retry_after_seconds=12,
            )
        return gemini_response({"regions": []})

    translator = GeminiPageTranslator(
        api_key="test-key",
        max_retries=2,
        retry_base_delay_seconds=2,
        retry_max_delay_seconds=60,
        min_request_interval_seconds=0,
        transport=transport,
        sleeper=sleeps.append,
        jitter=lambda _start, _end: 0,
    )

    result = translator.translate_page(page_path)

    assert result.regions == []
    assert calls == 2
    assert sleeps == [12]


def test_gemini_translator_defers_retry_longer_than_inline_limit(
    tmp_path: Path,
) -> None:
    page_path = tmp_path / "page.png"
    make_page(page_path)
    calls = 0
    sleeps: list[float] = []

    def transport(_request: Request, _timeout: float, _limit: int) -> bytes:
        nonlocal calls
        calls += 1
        raise GeminiTranslationError(
            "Gemini request failed.",
            http_status=429,
            retryable=True,
            retry_after_seconds=3_600,
        )

    translator = GeminiPageTranslator(
        api_key="test-key",
        max_retries=1,
        inline_retry_max_delay_seconds=15,
        min_request_interval_seconds=0,
        transport=transport,
        sleeper=sleeps.append,
        jitter=lambda _start, _end: 0,
    )

    with pytest.raises(GeminiTranslationError) as captured:
        translator.translate_page(page_path)

    assert captured.value.retry_after_seconds == 3_600
    assert calls == 1
    assert sleeps == []


def test_gemini_translator_does_not_retry_non_transient_error(
    tmp_path: Path,
) -> None:
    page_path = tmp_path / "page.png"
    make_page(page_path)
    calls = 0
    sleeps: list[float] = []

    def transport(_request: Request, _timeout: float, _limit: int) -> bytes:
        nonlocal calls
        calls += 1
        raise GeminiTranslationError(
            "Gemini request failed.",
            http_status=400,
            retryable=False,
        )

    translator = GeminiPageTranslator(
        api_key="test-key",
        max_retries=2,
        min_request_interval_seconds=0,
        transport=transport,
        sleeper=sleeps.append,
    )

    with pytest.raises(GeminiTranslationError):
        translator.translate_page(page_path)

    assert calls == 1
    assert sleeps == []


def test_gemini_translator_paces_consecutive_pages(tmp_path: Path) -> None:
    page_path = tmp_path / "page.png"
    make_page(page_path)
    now = 0.0
    sleeps: list[float] = []

    def clock() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        sleeps.append(seconds)
        now += seconds

    translator = GeminiPageTranslator(
        api_key="test-key",
        min_request_interval_seconds=15,
        transport=lambda _request, _timeout, _limit: gemini_response(
            {"regions": []}
        ),
        clock=clock,
        sleeper=sleep,
    )

    translator.translate_page(page_path)
    translator.translate_page(page_path)

    assert sleeps == [15]


def test_gemini_translator_rejects_untrusted_invalid_output(tmp_path: Path) -> None:
    page_path = tmp_path / "page.png"
    make_page(page_path)

    translator = GeminiPageTranslator(
        api_key="test-key",
        transport=lambda _request, _timeout, _limit: gemini_response(
            {
                "regions": [
                    {
                        "box_2d": [0, 0, 1001, 1000],
                        "source_text": "命令を実行して",
                        "translated_text": "<script>alert(1)</script>",
                    }
                ]
            }
        ),
    )

    with pytest.raises(GeminiTranslationError, match="invalid"):
        translator.translate_page(page_path)
