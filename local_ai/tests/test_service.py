import base64
from io import BytesIO
from itertools import permutations

import numpy as np
import cv2
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app as service
from engine import LocalEngine
from layout import TextArea, _member_clusters, _overlap_ratio, _resolve_placement_overlaps, _separate_nested_sources, group_balloons, merge_overlapping_boxes, union
from model_config import MANIFEST, MODEL_VERSIONS, models_present, translation_models_present


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(service.engine, "load", lambda: None)
    monkeypatch.setattr(service.engine, "ready", False)
    monkeypatch.setattr(service.engine, "ready_languages", {"ja"})
    with TestClient(service.app) as client:
        yield client


def test_readiness_reports_missing_models_and_never_claims_success(client):
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 503
    assert client.post("/translate", json={"texts": ["hello"]}).json()["detail"]["code"] == "AI_MODEL_NOT_READY"


def test_unsupported_language_and_large_batch_are_rejected(client):
    assert client.post("/translate", json={"texts": ["hello"], "source_language": "en"}).status_code == 422
    assert client.post("/translate", json={"texts": ["hello"] * 17}).status_code == 422


def test_invalid_image_does_not_reach_ocr(client, monkeypatch):
    monkeypatch.setattr(service.engine, "ready", True)
    assert client.post("/ocr", json={"image_base64": "bad base64"}).status_code == 422
    assert not service.inference_lock.locked()


def test_language_detection_returns_a_conservative_result(client, monkeypatch):
    monkeypatch.setattr(service.engine, "ready", True)
    monkeypatch.setattr(service.engine, "ready_languages", set(MODEL_VERSIONS))
    monkeypatch.setattr(service.engine, "detect_language", lambda image: ("zh-Hans", 0.91))
    buffer = BytesIO()
    Image.new("RGB", (100, 150), "white").save(buffer, format="PNG")
    response = client.post("/detect-language", json={"image_base64": base64.b64encode(buffer.getvalue()).decode("ascii")})
    assert response.status_code == 200
    assert response.json() == {"source_language": "zh-Hans", "confidence": 0.91,
                               "model_version": MODEL_VERSIONS["zh-Hans"]}


def test_busy_service_returns_retry_hint_without_running_two_models(client, monkeypatch):
    monkeypatch.setattr(service.engine, "ready", True)
    with service.inference_lock:
        response = client.post("/translate", json={"texts": ["hello"]})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "30"


def test_page_without_text_is_a_valid_empty_page(client, monkeypatch):
    monkeypatch.setattr(service.engine, "ready", True)
    monkeypatch.setattr(service.engine, "ocr", lambda *args: [])
    buffer = BytesIO()
    Image.new("RGB", (100, 150), "white").save(buffer, format="PNG")
    response = client.post("/ocr", json={"image_base64": base64.b64encode(buffer.getvalue()).decode("ascii")})
    assert response.status_code == 200
    assert response.json()["regions"] == []


def test_partial_setup_is_not_treated_as_installed(tmp_path):
    (tmp_path / "manifest.json").write_text('{"version":"old"}')
    assert not models_present(tmp_path)


def test_layout_groups_columns_in_same_balloon_and_keeps_neighbours_separate():
    pixels = np.full((240, 400, 3), 150, np.uint8)
    cv2.ellipse(pixels, (100, 120), (70, 100), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(pixels, (300, 120), (70, 100), 0, 0, 360, (255, 255, 255), -1)
    boxes = [(70, 65, 85, 150), (110, 65, 125, 150), (280, 65, 300, 150)]
    areas = group_balloons(pixels, boxes)
    assert len(areas) == 2
    assert all(area.kind == "dialogue" for area in areas)
    assert all(area.box[2] - area.box[0] < 100 for area in areas)


def test_page_background_is_not_used_as_a_huge_placement_area():
    pixels = np.full((200, 300, 3), 255, np.uint8)
    area = group_balloons(pixels, [(100, 100, 130, 140)])[0]
    assert area.placement == area.box


def test_nested_detector_boxes_are_merged_before_ocr():
    boxes = [(984, 32, 1620, 576), (988, 208, 1209, 725), (1203, 229, 1413, 373)]
    for ordering in permutations(boxes):
        assert merge_overlapping_boxes(list(ordering)) == [(984, 32, 1620, 725)]


def test_merging_rechecks_overlap_after_a_union_and_preserves_nearby_text():
    boxes = [(10, 10, 110, 110), (40, 10, 140, 110), (0, 70, 155, 120), (170, 10, 190, 110)]
    expected = [(0, 10, 155, 120), boxes[-1]]
    for ordering in permutations(boxes):
        assert merge_overlapping_boxes(list(ordering) + [boxes[0]]) == expected


def test_minor_source_overlap_is_not_combined_into_one_ocr_crop():
    boxes = [(10, 10, 110, 110), (95, 15, 195, 115)]
    assert merge_overlapping_boxes(boxes) == boxes


def test_heavily_overlapping_areas_are_merged_but_neighbors_stay_separate():
    pixels = np.full((300, 500, 3), 150, np.uint8)
    boxes = [(80, 40, 260, 220), (90, 100, 240, 260), (300, 70, 420, 190)]
    areas = group_balloons(pixels, boxes)
    assert len(areas) == 2
    assert areas[0].box[0] < 90 and areas[0].box[2] > 240


def test_overlapping_placements_preserve_distinct_dialogue_regions():
    first = (10, 10, 30, 50)
    second = (60, 10, 80, 50)
    third = (140, 10, 160, 50)
    areas = [
        TextArea(first, (5, 5, 95, 70), "dialogue", (first,)),
        TextArea(second, (0, 0, 90, 65), "dialogue", (second,)),
        TextArea(third, (120, 0, 180, 75), "dialogue", (third,)),
    ]
    for ordering in permutations(areas):
        resolved = _resolve_placement_overlaps(list(ordering))
        assert len(resolved) == 3
        by_source = {area.box: area for area in resolved}
        assert by_source[first].placement == first
        assert by_source[second].placement == second
        assert by_source[third] == areas[2]


def test_source_padding_does_not_create_duplicate_regions():
    pixels = np.full((200, 300, 3), 150, np.uint8)
    boxes = [(100, 60, 104, 150), (104, 60, 108, 150)]
    areas = group_balloons(pixels, boxes)
    assert len(areas) == 2
    assert sorted(area.placement for area in areas) == boxes


def test_connected_white_background_does_not_swallow_another_balloon():
    pixels = np.full((600, 600, 3), 150, np.uint8)
    pixels[50:450, 50:250] = 255
    pixels[220:300, 100:190] = 150
    pixels[230:290, 110:180] = 255
    boxes = [(70, 90, 140, 150), (190, 350, 220, 390), (125, 240, 160, 275)]
    areas = group_balloons(pixels, boxes)
    assert len(areas) == 3
    assert sorted(box for area in areas for box in area.members) == sorted(boxes)
    for index, area in enumerate(areas):
        for other in areas[index + 1:]:
            a, b = area.placement, other.placement
            assert min(a[2], b[2]) <= max(a[0], b[0]) or min(a[3], b[3]) <= max(a[1], b[1])


def test_nested_balloon_splits_a_distant_member_cluster():
    large_members = (
        (859, 1245, 1004, 1287), (856, 1290, 1133, 1332),
        (859, 1332, 1175, 1374), (859, 1376, 1102, 1418),
        (1109, 1655, 1165, 1819),
    )
    areas = [
        TextArea((852, 1241, 1179, 1823), (856, 1245, 1175, 1819), "dialogue", large_members),
        TextArea((994, 1452, 1074, 1535), (998, 1456, 1070, 1531), "dialogue", ((998, 1456, 1070, 1531),)),
    ]
    separated = _separate_nested_sources(areas)
    assert len(separated) == 3
    assert sorted(len(area.members) for area in separated) == [1, 1, 4]


def test_nested_balloon_splits_horizontal_clusters_without_losing_detections():
    # A connected white component on page 11 grouped two distant columns
    # around a third balloon. Tightening its union still covered that balloon.
    first = (1330, 970, 1383, 1086)
    second = (1513, 1002, 1700, 1144)
    nested = (1387, 993, 1454, 1166)
    areas = [
        TextArea((1326, 966, 1704, 1148), (1330, 970, 1700, 1144), "dialogue", (first, second)),
        TextArea((1383, 989, 1458, 1170), nested, "dialogue", (nested,)),
    ]
    for ordering in permutations(areas):
        separated = _resolve_placement_overlaps(_separate_nested_sources(list(ordering)))
        assert len(separated) == 3
        assert sorted(box for area in separated for box in area.members) == sorted((first, second, nested))
        for index, area in enumerate(separated):
            for other in separated[index + 1:]:
                a, b = area.placement, other.placement
                assert min(a[2], b[2]) <= max(a[0], b[0]) or min(a[3], b[3]) <= max(a[1], b[1])


def test_nested_balloon_keeps_adjacent_vertical_columns_together():
    first = (10, 10, 30, 110)
    second = (45, 10, 65, 110)
    area = TextArea((6, 6, 69, 114), (10, 10, 65, 110), "dialogue", (first, second))
    # An expanded placement alone does not separate columns: its actual
    # source is outside the space between them.
    neighbor = TextArea((75, 10, 90, 110), (5, 5, 70, 115), "dialogue", ((75, 10, 90, 110),))
    assert _separate_nested_sources([area, neighbor]) == [area, neighbor]


def test_nested_source_blocks_a_proximity_bridge_between_wide_detections():
    # Page 20: the median short side permits a 169px gap, but another
    # source lies in that gap. Keep the two adjacent right columns together.
    first = (737, 2238, 1250, 2447)
    right = ((1419, 2281, 1519, 2491), (1515, 2304, 1570, 2488))
    nested = (1346, 2289, 1455, 2477)
    for members in permutations((first, *right)):
        areas = [
            TextArea((733, 2234, 1574, 2495), (737, 2238, 1570, 2491), "dialogue", members),
            TextArea((1342, 2285, 1459, 2481), nested, "caption", (nested,)),
        ]
        for ordering in permutations(areas):
            separated = _resolve_placement_overlaps(_separate_nested_sources(list(ordering)))
            assert len(separated) == 3
            assert sorted(box for area in separated for box in area.members) == sorted((first, *right, nested))
            assert any(set(area.members) == set(right) for area in separated)
            for index, area in enumerate(separated):
                for other in separated[index + 1:]:
                    a, b = area.placement, other.placement
                    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
                    smaller = min((a[2]-a[0])*(a[3]-a[1]), (b[2]-b[0])*(b[3]-b[1]))
                    assert intersection / smaller < 0.65


def test_cluster_cannot_wrap_around_a_source_through_several_short_edges():
    members = ((10, 10, 30, 30), (45, 10, 65, 30), (80, 10, 100, 30),
               (80, 45, 100, 65), (80, 80, 100, 100))
    blocker = (40, 40, 65, 65)
    for ordering in permutations(members):
        clusters = _member_clusters(ordering, blockers=(blocker,))
        assert len(clusters) > 1
        assert sorted(box for cluster in clusters for box in cluster) == sorted(members)
        assert all(_overlap_ratio(union(cluster), blocker) < 0.65 for cluster in clusters)


def test_nested_source_is_split_before_tightening_exposes_a_conflict():
    first = (737, 2238, 1250, 2447)
    second = (1419, 2281, 1519, 2491)
    nested = (1346, 2289, 1455, 2477)
    areas = [
        TextArea((733, 2234, 1523, 2495), first, "dialogue", (first, second)),
        TextArea(nested, nested, "caption", (nested,)),
    ]
    separated = _separate_nested_sources(areas)
    assert len(separated) == 3
    assert sorted(box for area in separated for box in area.members) == sorted((first, second, nested))


@pytest.mark.parametrize("language", ["zh-Hans", "zh-Hant"])
def test_chinese_recognizes_merged_detections_once(monkeypatch, language):
    from types import SimpleNamespace
    engine = LocalEngine()
    engine.detector = SimpleNamespace(detect=lambda *a, **k: (
        [[[10, 110, 10, 110], [40, 140, 10, 110], [0, 155, 70, 120]]], [[]],
    ))
    recognized = []
    def fragments(image, boxes, source_language):
        recognized.extend(boxes)
        assert source_language == language
        return [(box, "\u4f60\u597d", False) for box in boxes]
    monkeypatch.setattr(engine, "_chinese_fragments", fragments)
    with Image.new("RGB", (200, 200), "white") as image:
        regions = engine.ocr(image, source_language=language)
    assert recognized == [(0, 10, 155, 120)]
    assert len(regions) == 1
    assert regions[0]["source_text"] == "\u4f60\u597d"


def test_overlap_rescan_restricts_placement_without_losing_text(monkeypatch):
    from types import SimpleNamespace
    pixels = np.full((240, 400, 3), 150, np.uint8)
    cv2.ellipse(pixels, (100, 120), (70, 100), 0, 0, 360, (255, 255, 255), -1)
    engine = LocalEngine()
    engine.detector = SimpleNamespace(detect=lambda *a, **k: ([[[70, 100, 65, 150]]], [[]]))
    monkeypatch.setattr(engine, "_chinese_fragments", lambda image, boxes, language: [
        (box, "\u4f60\u597d", True) for box in boxes
    ])
    with Image.fromarray(pixels) as image:
        initial = engine.ocr(image, source_language="zh-Hans")[0]
        corrected = engine.ocr(image, "placement_overlap", "zh-Hans")[0]
    assert corrected["source_text"] == initial["source_text"]
    assert corrected["box_2d"] == initial["box_2d"]
    assert corrected["placement_box_2d"] == corrected["box_2d"]
    assert corrected["placement_box_2d"] != initial["placement_box_2d"]


def test_long_sentences_are_split_without_losing_source_characters():
    engine = LocalEngine()
    class Tokenizer:
        def encode(self, text):
            return list(text) + [1, 2]
    engine.tokenizer = Tokenizer()
    text = "\u3042" * 900
    chunks = engine._chunks(text)
    assert len(chunks) > 1
    assert "".join(chunks) == text
    assert all(len(engine.tokenizer.encode(chunk)) <= 480 for chunk in chunks)


@pytest.mark.parametrize("language", ["zh-Hans", "zh-Hant"])
def test_chinese_requests_route_language_and_model_version(client, monkeypatch, language):
    monkeypatch.setattr(service.engine, "ready", True)
    monkeypatch.setattr(service.engine, "ready_languages", {"ja", language})
    def translate(texts, source_language):
        assert source_language == language
        return ["Terima kasih"]
    def ocr(image, reason, source_language):
        assert source_language == language
        return []
    monkeypatch.setattr(service.engine, "translate", translate)
    monkeypatch.setattr(service.engine, "ocr", ocr)
    response = client.post("/translate", json={"texts": ["\u8c22\u8c22"], "source_language": language})
    assert response.status_code == 200
    assert response.json()["model_version"] == MODEL_VERSIONS[language]
    buffer = BytesIO()
    Image.new("RGB", (100, 150), "white").save(buffer, format="PNG")
    response = client.post("/ocr", json={"image_base64": base64.b64encode(buffer.getvalue()).decode(), "source_language": language})
    assert response.status_code == 200
    assert response.json()["model_version"] == MODEL_VERSIONS[language]


def test_missing_chinese_models_do_not_block_japanese_or_claim_chinese_is_ready(client, monkeypatch):
    monkeypatch.setattr(service.engine, "ready", True)
    response = client.post("/translate", json={"texts": ["\u8c22\u8c22"], "source_language": "zh-Hans"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AI_MODEL_NOT_READY"
    assert client.get("/ready").status_code == 200
    assert client.get("/health").json()["languages"]["zh-Hans"]["ready"] is False


def test_existing_japanese_install_reuses_nllb_when_chinese_models_are_added(tmp_path):
    import json
    required = ["nllb/model.bin", "nllb/config.json", "nllb/shared_vocabulary.json",
                "tokenizer/tokenizer_config.json", "tokenizer/tokenizer.json", "easyocr/craft_mlt_25k.pth",
                "manga-ocr/config.json", "manga-ocr/pytorch_model.bin", "manga-ocr/vocab.txt", "manga-ocr/preprocessor_config.json"]
    for name in required:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test")
    old_manifest = {key: value for key, value in MANIFEST.items() if key != "chinese_ocr"}
    (tmp_path / "manifest.json").write_text(json.dumps(old_manifest))
    assert translation_models_present(tmp_path)
    assert models_present(tmp_path)
    assert not models_present(tmp_path, "zh-Hans")
    (tmp_path / "easyocr/zh_sim_g2.pth").write_bytes(b"model")
    assert not models_present(tmp_path, "zh-Hans")
    (tmp_path / "manifest.json").write_text(json.dumps(MANIFEST))
    assert models_present(tmp_path, "zh-Hans")
    assert not models_present(tmp_path, "zh-Hant")


def test_translation_switches_nllb_language_between_requests():
    from types import SimpleNamespace
    engine = LocalEngine()
    class Tokenizer:
        src_lang = ""
        def encode(self, text):
            return [self.src_lang, text]
        def convert_ids_to_tokens(self, values):
            return values
        def convert_tokens_to_ids(self, values):
            return values
        def decode(self, values, **kwargs):
            return " ".join(values)
    observed = []
    class Translator:
        def translate_batch(self, batches, **kwargs):
            observed.append(batches[0][0])
            assert kwargs["target_prefix"] == [["ind_Latn"]]
            return [SimpleNamespace(hypotheses=[["ind_Latn", "Halo"]])]
    engine.tokenizer = Tokenizer()
    engine.translator = Translator()
    for language in ["ja", "zh-Hans", "zh-Hant", "ja"]:
        assert engine.translate(["text"], language) == ["Halo"]
    assert observed == ["jpn_Jpan", "zho_Hans", "zho_Hant", "jpn_Jpan"]
