import os
import re
import unicodedata

import numpy as np
from PIL import Image

from layout import group_balloons, merge_overlapping_boxes, normalized_box
from language_detection import choose_language
from model_config import CHINESE_MODELS, MODEL_ROOT, MODEL_VERSIONS, NLLB_LANGUAGES, models_present


JAPANESE_TEXT = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
CHINESE_TEXT = re.compile(r"[\u3400-\u9fff\U00020000-\U0002fa1f]")


class LocalEngine:
    def __init__(self):
        self.ready = False
        self.ready_languages = set()
        self.chinese_readers = {}

    def load(self):
        if not models_present():
            raise FileNotFoundError("Run the model-setup service first.")
        import torch
        import easyocr
        import ctranslate2
        from transformers import AutoTokenizer, AutoImageProcessor, VisionEncoderDecoderModel

        torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "4")))
        self.detector = easyocr.Reader(
            ["ja", "en"], gpu=False, recognizer=False,
            model_storage_directory=str(MODEL_ROOT / "easyocr"),
            user_network_directory="/tmp/meguyomi-easyocr",
            download_enabled=False,
        )
        ocr_path = MODEL_ROOT / "manga-ocr"
        self.ocr_processor = AutoImageProcessor.from_pretrained(ocr_path, local_files_only=True)
        self.ocr_tokenizer = AutoTokenizer.from_pretrained(ocr_path, local_files_only=True)
        self.ocr_model = VisionEncoderDecoderModel.from_pretrained(ocr_path, local_files_only=True).eval()
        self.tokenizer = AutoTokenizer.from_pretrained(
            MODEL_ROOT / "tokenizer", src_lang="jpn_Jpan", local_files_only=True,
        )
        device = os.environ.get("LOCAL_AI_DEVICE", "cpu")
        self.translator = ctranslate2.Translator(
            str(MODEL_ROOT / "nllb"), device=device,
            compute_type="int8_float16" if device == "cuda" else "int8",
            inter_threads=1, intra_threads=int(os.environ.get("OMP_NUM_THREADS", "4")),
        )
        self.ready = True
        self.ready_languages = {language for language in MODEL_VERSIONS if models_present(source_language=language)}

    def _chinese_samples(self, image, boxes, source_language):
        import easyocr

        if source_language not in self.chinese_readers:
            self.chinese_readers[source_language] = easyocr.Reader(
                [CHINESE_MODELS[source_language][0], "en"], gpu=False, detector=False,
                model_storage_directory=str(MODEL_ROOT / "easyocr"),
                user_network_directory="/tmp/meguyomi-easyocr", download_enabled=False,
            )
        reader = self.chinese_readers[source_language]
        fragments = []
        for box in boxes:
            with image.crop(box).convert("L") as crop:
                vertical = crop.height > crop.width * 1.8
                if vertical:
                    # Recognize upright glyphs top-to-bottom; rotating the entire
                    # column also rotates the glyphs and confuses the recognizer.
                    pixels = np.asarray(crop)
                    rows = np.flatnonzero((pixels < 150).any(axis=1))
                    runs = []
                    for y in rows:
                        if not runs or y - runs[-1][1] > max(2, crop.width * 0.18):
                            runs.append([int(y), int(y)])
                        else:
                            runs[-1][1] = int(y)
                    lines = [[0, crop.width, max(0, start-2), min(crop.height, end+3)] for start, end in runs]
                    values = reader.recognize(pixels, horizontal_list=lines, free_list=[], detail=1) if lines else []
                else:
                    values = reader.recognize(np.asarray(crop), detail=1)
            text = "".join(value[1] for value in values)
            confidence = sum(len(value[1]) * float(value[2]) for value in values) / max(1, len(text))
            fragments.append((box, text, vertical, confidence))
        return fragments

    def _chinese_fragments(self, image, boxes, source_language):
        return [(box, text, vertical) for box, text, vertical, _ in self._chinese_samples(image, boxes, source_language)]

    def _japanese_sample(self, image, box, *, with_confidence=False):
        import torch

        with image.crop(box) as crop:
            values = self.ocr_processor(images=crop.convert("L").convert("RGB"), return_tensors="pt").pixel_values
        options = {"return_dict_in_generate": True, "output_scores": True} if with_confidence else {}
        limit = 128 if with_confidence else 256
        with torch.inference_mode():
            output = self.ocr_model.generate(values, max_new_tokens=limit, **options)
        sequence = output.sequences[0] if with_confidence else output[0]
        if len(sequence) >= limit:
            if with_confidence:
                return "", 0.0
            raise ValueError("OCR text exceeds the generation limit.")
        text = self.ocr_tokenizer.decode(sequence, skip_special_tokens=True)
        confidence = 0.0
        if with_confidence and output.scores:
            scores = self.ocr_model.compute_transition_scores(
                output.sequences, output.scores,
                beam_indices=getattr(output, "beam_indices", None), normalize_logits=True,
            )
            confidence = float(scores.mean().exp())
        return text, confidence

    def _detect_boxes(self, image):
        pixels = np.asarray(image)
        horizontal, free = self.detector.detect(
            pixels, min_size=8, text_threshold=0.6, low_text=0.3,
            link_threshold=0.4, canvas_size=2560, mag_ratio=1.5,
            width_ths=0.25, add_margin=0.02,
        )
        boxes = []
        for left, right, top, bottom in horizontal[0]:
            boxes.append((left, top, right, bottom))
        for polygon in free[0]:
            points = np.asarray(polygon)
            boxes.append((points[:,0].min(), points[:,1].min(), points[:,0].max(), points[:,1].max()))
        boxes = [
            (max(0, int(l)), max(0, int(t)), min(image.width, int(r)), min(image.height, int(b)))
            for l, t, r, b in boxes if r-l >= 3 and b-t >= 3
        ]
        if len(boxes) > 400:
            raise ValueError("Too many detected text blocks in one tile.")
        return boxes

    def _detection_chinese_samples(self, image, boxes, language):
        samples = []
        for box in boxes:
            with image.crop(box).convert("L") as crop:
                if crop.height <= crop.width * 1.4:
                    samples.extend((text, confidence) for _, text, _, confidence in
                                   self._chinese_samples(crop, [(0, 0, crop.width, crop.height)], language))
                    continue
                # Reflow vertical columns into upright horizontal lines for EasyOCR.
                # A detector box can contain several columns read right-to-left.
                columns = self._ink_runs(np.asarray(crop), axis=0, gap=2)
                for left, right in reversed(columns):
                    if right - left < 5:
                        continue
                    with crop.crop((max(0, left - 1), 0, min(crop.width, right + 2), crop.height)) as column:
                        rows = self._ink_runs(np.asarray(column), axis=1, gap=max(1, int(column.width * 0.08)))
                        glyphs = []
                        for top, bottom in rows:
                            height = bottom - top + 1
                            parts = max(1, round(height / column.width)) if height > column.width * 1.6 else 1
                            for part in range(parts):
                                glyphs.append(column.crop((0, max(0, top + height * part // parts - 1),
                                                           column.width, min(column.height, top + height * (part + 1) // parts + 1))))
                        if not glyphs:
                            continue
                        with Image.new("L", (sum(g.width + 3 for g in glyphs) + 10, max(g.height for g in glyphs) + 8), 255) as line:
                            x = 5
                            for glyph in glyphs:
                                line.paste(glyph, (x, 4))
                                x += glyph.width + 3
                                glyph.close()
                            samples.extend((text, confidence) for _, text, _, confidence in
                                           self._chinese_samples(line, [(0, 0, line.width, line.height)], language))
        return samples

    @staticmethod
    def _ink_runs(pixels, *, axis, gap):
        positions = np.flatnonzero((pixels < 160).any(axis=axis))
        runs = []
        for position in positions:
            if not runs or position - runs[-1][1] > gap:
                runs.append([int(position), int(position)])
            else:
                runs[-1][1] = int(position)
        return runs

    def detect_language(self, image):
        boxes = self._detect_boxes(image)
        # Dialogue is a better language sample than large untranslated sound effects.
        pixels = np.asarray(image.convert("L"))
        dialogue_boxes = [
            box for box in boxes
            if (pixels[box[1]:box[3], box[0]:box[2]] > 210).mean() >= 0.6
        ]
        # Dark or textured pages may have no white bubble; keep the original
        # detections rather than turning a readable page into an empty sample.
        boxes = dialogue_boxes or boxes
        boxes = merge_overlapping_boxes(boxes)
        boxes = sorted(boxes, key=lambda box: (box[2] - box[0]) * (box[3] - box[1]), reverse=True)[:8]
        if not boxes:
            return None, 0.0
        japanese = [self._japanese_sample(image, box, with_confidence=True) for box in boxes]
        chinese = {
            language: self._detection_chinese_samples(image, boxes, language)
            for language in CHINESE_MODELS
        }
        return choose_language(japanese, chinese)

    def ocr(self, image: Image.Image, quality_reason=None, source_language="ja") -> list[dict]:
        pixels = np.asarray(image)
        boxes = self._detect_boxes(image)
        areas = group_balloons(
            pixels, boxes,
            conservative=quality_reason == "source_mask_failure",
            restrict_placements=quality_reason == "placement_overlap",
        )
        if len(areas) > 80:
            raise ValueError("Too many text regions in one tile.")
        recognition_boxes = sorted({box for area in areas for box in area.members})
        fragments = self._chinese_fragments(image, recognition_boxes, source_language) if source_language in CHINESE_MODELS else []
        regions = []
        for area in areas:
            if source_language == "ja":
                source, _ = self._japanese_sample(image, area.box)
            else:
                members = [(box, text, vertical) for box, text, vertical in fragments if box in area.members]
                if members and sum(item[2] for item in members) > len(members) / 2:
                    members.sort(key=lambda item: (-item[0][2], item[0][1]))
                else:
                    members.sort(key=lambda item: (item[0][1], item[0][0]))
                source = "".join(text for _, text, _ in members)
            source = unicodedata.normalize("NFKC", re.sub(r"\s+", "", source))
            script = JAPANESE_TEXT if source_language == "ja" else CHINESE_TEXT
            if not script.search(source):
                continue
            if len(source) > 1000:
                raise ValueError("OCR text exceeds region size limit.")
            regions.append({
                "box_2d": normalized_box(area.box, image.width, image.height),
                "placement_box_2d": normalized_box(area.placement, image.width, image.height),
                "source_text": source, "source_language": source_language, "region_type": area.kind,
            })
        return regions

    def _chunks(self, text: str) -> list[str]:
        # Split overlong input at sentence boundaries, then by characters.
        # Never silently truncate a sentence to the token limit.
        if len(self.tokenizer.encode(text)) <= 480:
            return [text]
        chunks = []
        current = ""
        for char in text:
            candidate = current + char
            if len(self.tokenizer.encode(candidate)) > 480:
                chunks.append(current)
                current = char
            else:
                current = candidate
            if char in "\u3002\uff01\uff1f!?" and len(current) >= 80:
                chunks.append(current)
                current = ""
        if current:
            chunks.append(current)
        return chunks

    def translate(self, texts: list[str], source_language="ja") -> list[str]:
        self.tokenizer.src_lang = NLLB_LANGUAGES[source_language]
        translations = []
        for text in texts:
            pieces = []
            for chunk in self._chunks(text):
                tokens = self.tokenizer.convert_ids_to_tokens(self.tokenizer.encode(chunk))
                result = self.translator.translate_batch(
                    [tokens], target_prefix=[["ind_Latn"]], beam_size=3,
                    max_decoding_length=512, max_input_length=512,
                )[0].hypotheses[0]
                if len(result) >= 512:
                    raise ValueError("Translation exceeds generation limit.")
                if result and result[0] == "ind_Latn":
                    result = result[1:]
                decoded = self.tokenizer.decode(
                    self.tokenizer.convert_tokens_to_ids(result), skip_special_tokens=True,
                ).strip()
                if not decoded:
                    raise ValueError("Model returned an empty translation.")
                pieces.append(decoded)
            translated = " ".join(pieces)
            if len(translated) > 1000:
                raise ValueError("Translation exceeds region size limit.")
            translations.append(translated)
        return translations
