import base64
from io import BytesIO

import pytest
import numpy as np
from PIL import Image

import app as service
from engine import LocalEngine
from language_detection import choose_language
from model_config import MODEL_VERSIONS
from test_service import client


JAPANESE = "\u3069\u3046\u3057\u3066\u3053\u3053\u306b\u3044\u308b\u306e"
SIMPLIFIED = "\u6211\u4eec\u8fd9\u4e2a\u65f6\u5019\u8bf4\u8bdd"
TRADITIONAL = "\u6211\u5011\u9019\u500b\u6642\u5019\u8aaa\u8a71"


@pytest.mark.parametrize("japanese,chinese,expected", [
    ([(JAPANESE, 0.95)], {"zh-Hans": [(SIMPLIFIED, 0.4)]}, "ja"),
    ([("\u4eca\u5929\u5929\u6c23", 0.95)], {"zh-Hans": [(SIMPLIFIED, 0.91)]}, "zh-Hans"),
    ([(JAPANESE, 0.71)], {"zh-Hans": [(SIMPLIFIED, 0.95)]}, "zh-Hans"),
    ([], {"zh-Hans": [(SIMPLIFIED, 0.4)], "zh-Hant": [(TRADITIONAL, 0.94)]}, "zh-Hant"),
    ([], {"zh-Hans": [(SIMPLIFIED, 0.96)], "zh-Hant": [(TRADITIONAL, 0.65)]}, "zh-Hans"),
    ([], {"zh-Hans": [(SIMPLIFIED, 0.76)], "zh-Hant": [(TRADITIONAL, 0.80)]}, "zh-Hans"),
    ([(JAPANESE, 0.92)], {"zh-Hans": [(SIMPLIFIED, 0.91)]}, None),
    ([("\u30fb\u30fc\u3001\u3002", 0.99)], {}, None),
    ([("English title", 0.99)], {"zh-Hans": [("Chapter 1", 0.99)]}, None),
    ([], {"zh-Hans": [("\u4f60", 0.99)]}, None),
    ([], {}, None),
])
def test_select_language_requires_script_evidence_and_independent_confidence(japanese, chinese, expected):
    language, confidence = choose_language(japanese, chinese)
    assert language == expected
    assert 0 <= confidence <= 1
    assert (confidence == 0) == (expected is None)


def image_payload():
    buffer = BytesIO()
    Image.new("RGB", (100, 100), "white").save(buffer, format="PNG")
    return {"image_base64": base64.b64encode(buffer.getvalue()).decode("ascii")}


def test_detector_blank_page_skips_recognizers(monkeypatch):
    engine = LocalEngine()
    monkeypatch.setattr(engine, "_detect_boxes", lambda image: [])
    with Image.new("RGB", (100, 100), "white") as image:
        assert engine.detect_language(image) == (None, 0.0)


def test_detector_samples_both_chinese_readers_and_limits_work(monkeypatch):
    engine = LocalEngine()
    monkeypatch.setattr(engine, "_detect_boxes", lambda image: [(i * 12, 0, i * 12 + 10, 20) for i in range(12)])
    seen = []
    monkeypatch.setattr(engine, "_japanese_sample", lambda *a, **k: ("", 0))
    def chinese(image, boxes, language):
        seen.append(language)
        assert len(boxes) == 8
        text = SIMPLIFIED if language == "zh-Hans" else TRADITIONAL
        return [(text, 0.95 if language == "zh-Hans" else 0.4) for box in boxes]
    monkeypatch.setattr(engine, "_detection_chinese_samples", chinese)
    with Image.new("RGB", (200, 100), "white") as image:
        assert engine.detect_language(image)[0] == "zh-Hans"
    assert set(seen) == {"zh-Hans", "zh-Hant"}


def test_detection_reflows_multiple_vertical_columns_without_rotating_glyphs(monkeypatch):
    engine = LocalEngine()
    pixels = np.full((60, 32), 255, dtype=np.uint8)
    for left, value in [(2, 40), (20, 80)]:
        for top in [4, 21, 38]:
            pixels[top:top + 12, left:left + 9] = value
    lines = []
    def samples(image, boxes, language):
        assert image.width > image.height
        lines.append(np.asarray(image).copy())
        return [(boxes[0], SIMPLIFIED, False, 0.9)]
    monkeypatch.setattr(engine, "_chinese_samples", samples)
    with Image.fromarray(pixels) as image:
        result = engine._detection_chinese_samples(image, [(0, 0, 32, 60)], "zh-Hans")
    assert len(result) == 2
    assert len(lines) == 2
    assert lines[0].min() == 80  # Right-hand column comes first.
    assert lines[1].min() == 40
    assert all((line < 160).sum() == 3 * 12 * 9 for line in lines)


def test_detection_ignores_dark_art_boxes_before_sampling_dialogue(monkeypatch):
    engine = LocalEngine()
    pixels = np.zeros((100, 200, 3), dtype=np.uint8)
    pixels[10:90, 110:190] = 255
    monkeypatch.setattr(engine, "_detect_boxes", lambda image: [(0, 0, 100, 100), (110, 10, 190, 90)])
    seen = []
    def japanese(image, box, **kwargs):
        seen.append(box)
        return JAPANESE, 0.98
    monkeypatch.setattr(engine, "_japanese_sample", japanese)
    monkeypatch.setattr(engine, "_detection_chinese_samples", lambda *a: [])
    with Image.fromarray(pixels) as image:
        assert engine.detect_language(image)[0] == "ja"
    assert seen == [(110, 10, 190, 90)]


def test_detection_falls_back_to_all_boxes_on_a_dark_page(monkeypatch):
    engine = LocalEngine()
    pixels = np.zeros((100, 200, 3), dtype=np.uint8)
    monkeypatch.setattr(engine, "_detect_boxes", lambda image: [(0, 0, 100, 100)])
    monkeypatch.setattr(engine, "_japanese_sample", lambda image, box, **kwargs: (JAPANESE, 0.98))
    monkeypatch.setattr(engine, "_detection_chinese_samples", lambda *a: [])
    with Image.fromarray(pixels) as image:
        assert engine.detect_language(image)[0] == "ja"


def test_japanese_confidence_tracks_the_selected_beam():
    import torch
    from types import SimpleNamespace
    engine = LocalEngine()
    engine.ocr_processor = lambda **kwargs: SimpleNamespace(pixel_values=torch.zeros(1))
    engine.ocr_tokenizer = SimpleNamespace(decode=lambda *a, **k: JAPANESE)
    output = SimpleNamespace(sequences=torch.tensor([[1, 2, 3]]), scores=(torch.zeros(2, 4),),
                             beam_indices=torch.tensor([[0, 1, -1]]))
    def scores(sequences, values, **kwargs):
        assert kwargs["beam_indices"] is output.beam_indices
        assert kwargs["normalize_logits"] is True
        return torch.tensor([[-0.01, -0.01]])
    engine.ocr_model = SimpleNamespace(generate=lambda *a, **k: output, compute_transition_scores=scores)
    with Image.new("RGB", (30, 30), "white") as image:
        text, confidence = engine._japanese_sample(image, (0, 0, 30, 30), with_confidence=True)
    assert text == JAPANESE
    assert confidence > 0.98


def test_detection_requires_all_models_and_uses_the_inference_lock(client, monkeypatch):
    monkeypatch.setattr(service.engine, "ready", True)
    assert client.post("/detect-language", json=image_payload()).status_code == 503
    monkeypatch.setattr(service.engine, "ready_languages", set(MODEL_VERSIONS))
    with service.inference_lock:
        assert client.post("/detect-language", json=image_payload()).status_code == 429
    assert client.post("/detect-language", json={"image_base64": "invalid"}).status_code == 422
    assert not service.inference_lock.locked()


def test_uncertain_page_is_explicit_and_inference_errors_have_detection_code(client, monkeypatch):
    monkeypatch.setattr(service.engine, "ready", True)
    monkeypatch.setattr(service.engine, "ready_languages", set(MODEL_VERSIONS))
    monkeypatch.setattr(service.engine, "detect_language", lambda image: (None, 0.0))
    assert client.post("/detect-language", json=image_payload()).json() == {
        "source_language": None, "confidence": 0.0, "model_version": None,
    }
    def fail(image):
        raise RuntimeError("OCR failed")
    monkeypatch.setattr(service.engine, "detect_language", fail)
    response = client.post("/detect-language", json=image_payload())
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "AI_LANGUAGE_DETECTION_FAILED"
    assert not service.inference_lock.locked()
