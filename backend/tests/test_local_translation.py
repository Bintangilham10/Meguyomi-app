from io import BytesIO
import base64
from pathlib import Path
from urllib.error import HTTPError

import pytest
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.translation_memory import TranslationMemory
from app.services import local_translation as local
from app.core.languages import MODEL_VERSIONS
from app.services.indonesian_style import DIALOGUE_STYLE_VERSION
from app.services.translation_memory import MODEL_VERSION, TranslationMemoryStore, save_entry

SOURCE = "\u3053\u3093\u306b\u3061\u306f"


@pytest.fixture
def memory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'memory.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    yield sessions
    engine.dispose()


def region(text=SOURCE):
    return dict(box_2d=[100, 100, 300, 400], placement_box_2d=[80, 80, 340, 500],
                source_text=text, source_language="ja", region_type="dialogue")


def page(tmp_path, size=(120, 160)):
    path = tmp_path / "page.png"
    Image.new("RGB", size, "white").save(path)
    return path


def detection_response(language="zh-Hans", confidence=0.9):
    return {"source_language": language, "confidence": confidence,
            "model_version": MODEL_VERSIONS.get(language)}


def test_detection_skips_blank_cover_and_confirms_with_another_page(tmp_path, monkeypatch):
    path = page(tmp_path, size=(100, 800))
    responses = iter([detection_response(None, 0), detection_response(), detection_response()])
    calls = []
    def post(url, payload, **kwargs):
        calls.append(url)
        assert url == "http://local-ai/detect-language"
        assert "source_language" not in payload
        with Image.open(BytesIO(base64.b64decode(payload["image_base64"]))) as sample:
            assert sample.size == (100, 200)
        return next(responses)
    monkeypatch.setattr(local, "_post_json", post)
    assert local.detect_source_language([path] * 4, base_url="http://local-ai/") == "zh-Hans"
    assert len(calls) == 3


@pytest.mark.parametrize("responses", [
    [detection_response(None, 0)] * 3,
    [detection_response("ja"), detection_response("zh-Hans")],
    [detection_response("zh-Hans", 0.3)] * 3,
    [detection_response(), detection_response(None, 0), detection_response(None, 0)],
])
def test_detection_does_not_guess_for_ambiguous_or_mixed_documents(tmp_path, monkeypatch, responses):
    path = page(tmp_path)
    values = iter(responses)
    monkeypatch.setattr(local, "_post_json", lambda *a, **k: next(values))
    with pytest.raises(local.LocalTranslationError) as raised:
        local.detect_source_language([path] * 3, base_url="http://local-ai")
    assert raised.value.code == "AI_LANGUAGE_DETECTION_FAILED"


@pytest.mark.parametrize("response", [
    {}, detection_response("en"), detection_response("auto"),
    detection_response() | {"confidence": True}, detection_response() | {"confidence": float("nan")},
    detection_response() | {"confidence": 1.1}, detection_response() | {"model_version": "old"},
    detection_response() | {"source_language": []},
])
def test_detection_validates_language_confidence_and_model_version(tmp_path, monkeypatch, response):
    path = page(tmp_path)
    monkeypatch.setattr(local, "_post_json", lambda *a, **k: response)
    with pytest.raises(local.LocalTranslationError) as raised:
        local.detect_source_language([path], base_url="http://local-ai")
    assert raised.value.code == "AI_LANGUAGE_DETECTION_FAILED"


@pytest.mark.parametrize("language", list(MODEL_VERSIONS))
def test_single_page_detection_supports_all_languages(tmp_path, monkeypatch, language):
    path = page(tmp_path)
    monkeypatch.setattr(local, "_post_json", lambda *a, **k: detection_response(language))
    assert local.detect_source_language([path], base_url="http://local-ai") == language


@pytest.mark.parametrize("error", [
    local.LocalTranslationError("busy", retryable=True, http_status=429),
    local.LocalTranslationError("unavailable", retryable=True),
    local.LocalTranslationError("missing", code="AI_MODEL_NOT_READY", http_status=503),
])
def test_detection_preserves_service_failures_for_retry(tmp_path, monkeypatch, error):
    path = page(tmp_path)
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(local, "_post_json", fail)
    with pytest.raises(local.LocalTranslationError) as raised:
        local.detect_source_language([path], base_url="http://local-ai")
    assert raised.value is error


def test_memory_reuses_normalized_text_and_preserves_corrections(memory):
    store = TranslationMemoryStore(memory)
    assert store.remember(SOURCE, "Halo") == "Halo"
    assert store.resolve(SOURCE[:2] + "\n" + SOURCE[2:]) == "Halo"
    with memory() as session:
        save_entry(session, SOURCE, "Selamat siang", category="verified")
        session.commit()
    assert store.remember(SOURCE, "Wrong machine output") == "Selamat siang"
    with memory() as session:
        entry = session.scalar(select(TranslationMemory))
        assert entry.category == "verified"
        assert entry.usage_count == 1
        assert len(entry.source_hash) == 64


def test_machine_memory_keeps_raw_text_but_returns_dialogue_style(memory):
    store = TranslationMemoryStore(memory)
    assert store.remember(SOURCE, "Saya tidak tahu.") == "Aku nggak tahu."
    with memory() as session:
        entry = session.scalar(select(TranslationMemory))
        assert entry.translated_text == "Saya tidak tahu."
    assert store.resolve(SOURCE, region_type="caption") == "Saya tidak tahu."


@pytest.mark.parametrize("category", ["verified", "glossary"])
def test_manual_wording_is_never_restyled_or_overwritten(memory, category):
    wording = "Saya tidak tahu. Terima kasih."
    with memory() as session:
        save_entry(session, SOURCE, wording, category=category)
        session.commit()
    store = TranslationMemoryStore(memory)
    assert store.resolve(SOURCE) == wording
    assert store.remember(SOURCE, "Aku tahu.") == wording
    with memory() as session:
        entry = session.scalar(select(TranslationMemory))
        assert entry.translated_text == wording
        assert entry.category == category


@pytest.mark.parametrize("language", list(MODEL_VERSIONS))
def test_same_source_uses_its_own_region_style_on_cache_miss_and_hit(
    tmp_path, memory, monkeypatch, language,
):
    raw_text = "Saya tidak tahu."
    kinds = ["dialogue", "title", "caption", "sfx", "dialogue"]
    calls = []

    def post(url, payload, **kwargs):
        calls.append(url)
        if url.endswith("/ocr"):
            return {
                "regions": [region() | {"region_type": kind, "source_language": language} for kind in kinds],
                "model_version": MODEL_VERSIONS[language],
            }
        assert payload["texts"] == [SOURCE]
        return {"translations": [raw_text], "model_version": MODEL_VERSIONS[language]}

    monkeypatch.setattr(local, "_post_json", post)
    translator = local.LocalPageTranslator(
        base_url="http://local-ai", session_factory=memory, source_language=language,
    )
    path = page(tmp_path)
    expected = ["Aku nggak tahu.", raw_text, raw_text, raw_text, "Aku nggak tahu."]
    assert [r.translated_text for r in translator.translate_page(path).regions] == expected
    assert calls.count("http://local-ai/translate") == 1
    calls.clear()
    assert [r.translated_text for r in translator.translate_page(path).regions] == expected
    assert calls == ["http://local-ai/ocr"]
    with memory() as session:
        entry = session.scalar(select(TranslationMemory))
        assert entry.translated_text == raw_text
        assert entry.model_version == MODEL_VERSIONS[language]


def test_similar_negation_is_never_automatically_reused(memory):
    store = TranslationMemoryStore(memory)
    affirmative = "\u4eca\u65e5\u306f\u5b66\u6821\u306b\u884c\u304d\u307e\u3059"
    negative = "\u4eca\u65e5\u306f\u5b66\u6821\u306b\u884c\u304d\u307e\u305b\u3093"
    store.remember(affirmative, "Hari ini aku pergi ke sekolah.")
    assert store.resolve(negative) is None


def test_memory_ignores_stale_machine_version_but_uses_manual_entries(memory):
    old = TranslationMemoryStore(memory, model_version="old")
    old.remember(SOURCE, "Old")
    assert TranslationMemoryStore(memory).resolve(SOURCE) is None
    with memory() as session:
        save_entry(session, SOURCE, "Halo", category="glossary")
        session.commit()
    assert TranslationMemoryStore(memory).resolve(SOURCE) == "Halo"


def test_page_translates_misses_then_reuses_database(tmp_path, memory, monkeypatch):
    calls = []
    def post(url, payload, **kwargs):
        calls.append(url)
        if url.endswith("/ocr"):
            return {"regions": [region(), region()], "model_version": MODEL_VERSION}
        assert payload["texts"] == [SOURCE]
        return {"translations": ["Halo"], "model_version": MODEL_VERSION}
    monkeypatch.setattr(local, "_post_json", post)
    translator = local.LocalPageTranslator(base_url="http://local-ai:8001", session_factory=memory)
    path = page(tmp_path)
    assert [r.translated_text for r in translator.translate_page(path).regions] == ["Halo", "Halo"]
    calls.clear()
    assert translator.translate_page(path).regions[0].translated_text == "Halo"
    assert calls == ["http://local-ai:8001/ocr"]


def test_model_requests_are_bounded_to_sixteen_texts(tmp_path, monkeypatch):
    sizes = []
    def post(url, payload, **kwargs):
        if url.endswith("/ocr"):
            return {"regions": [region(SOURCE + str(i)) for i in range(35)], "model_version": MODEL_VERSION}
        sizes.append(len(payload["texts"]))
        return {"translations": ["Halo"] * len(payload["texts"]), "model_version": MODEL_VERSION}
    monkeypatch.setattr(local, "_post_json", post)
    translator = local.LocalPageTranslator(base_url="http://local-ai:8001", session_factory=None)
    assert len(translator.translate_page(page(tmp_path)).regions) == 35
    assert sizes == [16, 16, 3]


@pytest.mark.parametrize("bad_region", [None, {}, region() | {"source_language": "en"}, region() | {"box_2d": [500, 100, 400, 300]}])
def test_invalid_ocr_is_rejected_without_publishing_blank_success(tmp_path, monkeypatch, bad_region):
    monkeypatch.setattr(local, "_post_json", lambda *a, **k: {"regions": [bad_region], "model_version": MODEL_VERSION})
    with pytest.raises(local.LocalTranslationError):
        local.LocalPageTranslator(base_url="http://local-ai:8001", session_factory=None).translate_page(page(tmp_path))


@pytest.mark.parametrize("output", [[], [""], ["x" * 1001], [None]])
def test_invalid_translation_is_not_learned(tmp_path, memory, monkeypatch, output):
    monkeypatch.setattr(local, "_post_json", lambda url, *a, **k: {
        **({"regions": [region()]} if url.endswith("/ocr") else {"translations": output}), "model_version": MODEL_VERSION,
    })
    with pytest.raises(local.LocalTranslationError):
        local.LocalPageTranslator(base_url="http://local-ai:8001", session_factory=memory).translate_page(page(tmp_path))
    assert TranslationMemoryStore(memory).resolve(SOURCE) is None


def test_long_page_resumes_completed_tiles_after_local_service_error(tmp_path, monkeypatch):
    calls = 0
    def interrupted(url, payload, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise local.LocalTranslationError("offline", retryable=True)
        return {"regions": [], "model_version": MODEL_VERSION}
    monkeypatch.setattr(local, "_post_json", interrupted)
    translator = local.LocalPageTranslator(base_url="http://local-ai:8001", session_factory=None)
    path = page(tmp_path, (120, 700))
    cache = tmp_path / "tiles"
    with pytest.raises(local.LocalTranslationError):
        translator.translate_page(path, tile_cache_directory=cache)
    assert len(list(cache.glob("tile-*.json"))) == 1
    remaining = []
    monkeypatch.setattr(local, "_post_json", lambda *a, **k: remaining.append(1) or {"regions": [], "model_version": MODEL_VERSION})
    assert translator.translate_page(path, tile_cache_directory=cache).regions == []
    assert len(remaining) == 3


def test_missing_model_http_error_is_distinct_from_temporary_outage(monkeypatch):
    def unavailable(*args, **kwargs):
        raise HTTPError("http://local-ai:8001/ocr", 503, "Unavailable", {}, BytesIO(b'{"detail":{"code":"AI_MODEL_NOT_READY"}}'))
    monkeypatch.setattr(local, "urlopen", unavailable)
    with pytest.raises(local.LocalTranslationError) as error:
        local._post_json("http://local-ai:8001/ocr", {}, timeout_seconds=1)
    assert error.value.code == "AI_MODEL_NOT_READY"
    assert error.value.retryable is False


@pytest.mark.parametrize("language", ["zh-Hans", "zh-Hant"])
def test_chinese_translation_and_memory_never_use_japanese_homographs(tmp_path, memory, monkeypatch, language):
    source = "\u5927\u4e08\u592b"
    with memory() as session:
        save_entry(session, source, "Tidak apa-apa", source_language="ja")
        session.commit()
    calls = []
    def post(url, payload, **kwargs):
        assert payload["source_language"] == language
        calls.append(url)
        if url.endswith("/ocr"):
            return {"regions": [region(source) | {"source_language": language}], "model_version": MODEL_VERSIONS[language]}
        return {"translations": ["Pria sejati"], "model_version": MODEL_VERSIONS[language]}
    monkeypatch.setattr(local, "_post_json", post)
    translator = local.LocalPageTranslator(base_url="http://local-ai", session_factory=memory, source_language=language)
    path = page(tmp_path)
    result = translator.translate_page(path)
    assert result.engine_version == f"{MODEL_VERSIONS[language]}+{DIALOGUE_STYLE_VERSION}+{local.LOCAL_LAYOUT_VERSION}"
    assert result.regions[0].translated_text == "Pria sejati"
    calls.clear()
    assert translator.translate_page(path).regions[0].translated_text == "Pria sejati"
    assert calls == ["http://local-ai/ocr"]
    with memory() as session:
        save_entry(session, source, "Seorang pria sejati", source_language=language)
        session.commit()
    assert translator.translate_page(path).regions[0].translated_text == "Seorang pria sejati"
    assert TranslationMemoryStore(memory).resolve(source) == "Tidak apa-apa"


def test_chinese_job_cannot_reuse_japanese_tile_checkpoint(tmp_path, monkeypatch):
    calls = []
    def post(url, payload, **kwargs):
        calls.append(payload["source_language"])
        return {"regions": [], "model_version": MODEL_VERSIONS[payload["source_language"]]}
    monkeypatch.setattr(local, "_post_json", post)
    path = page(tmp_path, (120, 700))
    cache = tmp_path / "tiles"
    local.LocalPageTranslator(base_url="http://local-ai", session_factory=None).translate_page(path, tile_cache_directory=cache)
    tile_count = len(calls)
    calls.clear()
    result = local.LocalPageTranslator(base_url="http://local-ai", session_factory=None, source_language="zh-Hans").translate_page(path, tile_cache_directory=cache)
    assert calls == ["zh-Hans"] * tile_count
    assert result.engine_version == f"{MODEL_VERSIONS['zh-Hans']}+{DIALOGUE_STYLE_VERSION}+{local.LOCAL_LAYOUT_VERSION}"


@pytest.mark.parametrize("old_version", ["model", "style"])
def test_pipeline_update_invalidates_old_tiles_and_page_records(tmp_path, monkeypatch, old_version):
    from app.tasks.translation import checkpoint_record_is_valid

    calls = []
    def post(url, payload, **kwargs):
        calls.append(url)
        return {"regions": [], "model_version": MODEL_VERSION}

    monkeypatch.setattr(local, "_post_json", post)
    path = page(tmp_path, (120, 700))
    cache = tmp_path / "tiles"
    previous = local.LocalPageTranslator(base_url="http://local-ai", session_factory=None)
    previous.engine_version = previous.model_version
    if old_version == "style":
        previous.engine_version += f"+{DIALOGUE_STYLE_VERSION}"
    old_page = previous.translate_page(path, tile_cache_directory=cache)
    tile_count = len(calls)
    record = tmp_path / "page.json"
    record.write_text(old_page.model_dump_json(), encoding="utf-8")
    current = local.LocalPageTranslator(base_url="http://local-ai", session_factory=None)
    assert not checkpoint_record_is_valid(record, engine_version=current.engine_version)
    calls.clear()
    new_page = current.translate_page(path, tile_cache_directory=cache)
    assert len(calls) == tile_count
    record.write_text(new_page.model_dump_json(), encoding="utf-8")
    assert checkpoint_record_is_valid(record, engine_version=current.engine_version)
    calls.clear()
    current.translate_page(path, tile_cache_directory=cache)
    assert calls == []
