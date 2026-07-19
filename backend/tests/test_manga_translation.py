import json
from pathlib import Path
from urllib.request import Request

import pytest
from PIL import Image
from pydantic import ValidationError

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
                        "source_text": "こんにちは",
                        "translated_text": "Halo",
                    }
                ]
            }
        )

    translator = GeminiPageTranslator(
        api_key="test-key",
        model="gemini-3.5-flash",
        timeout_seconds=30,
        max_image_bytes=1_000_000,
        max_response_bytes=100_000,
        transport=transport,
    )

    result = translator.translate_page(page_path)

    assert result.regions[0].translated_text == "Halo"
    request = captured["request"]
    assert isinstance(request, Request)
    assert request.full_url.endswith("/models/gemini-3.5-flash:generateContent")
    assert request.get_header("X-goog-api-key") == "test-key"
    payload = json.loads(request.data or b"{}")
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    assert payload["generationConfig"]["maxOutputTokens"] > 0
    assert payload["generationConfig"]["responseJsonSchema"]["type"] == "object"
    serialized_schema = json.dumps(
        payload["generationConfig"]["responseJsonSchema"]
    )
    assert '"default"' not in serialized_schema
    assert '"minLength"' not in serialized_schema
    assert '"maxLength"' not in serialized_schema
    assert payload["contents"][0]["parts"][0]["inline_data"]["mime_type"] == (
        "image/png"
    )
    assert captured["timeout"] == 30
    assert captured["max_response_bytes"] == 100_000


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
