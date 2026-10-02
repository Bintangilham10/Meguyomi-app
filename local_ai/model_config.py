import json
import os
from pathlib import Path

MODEL_ROOT = Path(os.environ.get("MODEL_ROOT", "/models"))
NLLB_REPO = "facebook/nllb-200-distilled-600M"
NLLB_REVISION = "f8d333a098d19b4fd9a8b18f94170487ad3f821d"
OCR_REPO = "kha-white/manga-ocr-base"
OCR_REVISION = "aa6573bd10b0d446cbf622e29c3e084914df9741"
MODEL_VERSION = "manga-ocr-nllb600m-int8-v1"
MODEL_VERSIONS = {
    "ja": MODEL_VERSION,
    "zh-Hans": "easyocr-zh-hans-nllb600m-int8-v1",
    "zh-Hant": "easyocr-zh-hant-nllb600m-int8-v1",
}
NLLB_LANGUAGES = {"ja": "jpn_Jpan", "zh-Hans": "zho_Hans", "zh-Hant": "zho_Hant"}
CHINESE_MODELS = {
    "zh-Hans": ("ch_sim", "zh_sim_g2.pth"),
    "zh-Hant": ("ch_tra", "chinese.pth"),
}
MANIFEST = {
    "version": MODEL_VERSION,
    "translation": NLLB_REVISION,
    "ocr": OCR_REVISION,
    "detector": "easyocr-craft-1.7.2",
    "chinese_ocr": "easyocr-1.7.2-zh-sim-g2-zh-tra-g1",
}


def translation_models_present(root: Path = MODEL_ROOT) -> bool:
    try:
        manifest = json.loads((root / "manifest.json").read_text())
        return manifest.get("translation") == NLLB_REVISION and _files_present(root, (
            "nllb/model.bin", "nllb/config.json", "nllb/shared_vocabulary.json",
            "tokenizer/tokenizer_config.json", "tokenizer/tokenizer.json",
        ))
    except (OSError, ValueError, AttributeError):
        return False


def _files_present(root: Path, names) -> bool:
    return all((root / name).is_file() and (root / name).stat().st_size > 0 for name in names)


def models_present(root: Path = MODEL_ROOT, source_language: str = "ja") -> bool:
    required = (
        "nllb/model.bin", "nllb/config.json", "nllb/shared_vocabulary.json",
        "tokenizer/tokenizer_config.json", "tokenizer/tokenizer.json",
        "easyocr/craft_mlt_25k.pth",
    )
    try:
        manifest = json.loads((root / "manifest.json").read_text())
        if manifest.get("translation") != NLLB_REVISION or manifest.get("detector") != MANIFEST["detector"]:
            return False
        if source_language == "ja":
            if manifest.get("ocr") != OCR_REVISION or manifest.get("version") != MODEL_VERSION:
                return False
            required += ("manga-ocr/config.json", "manga-ocr/pytorch_model.bin",
                         "manga-ocr/vocab.txt", "manga-ocr/preprocessor_config.json")
        elif source_language in CHINESE_MODELS:
            if manifest.get("chinese_ocr") != MANIFEST["chinese_ocr"]:
                return False
            required += ("easyocr/" + CHINESE_MODELS[source_language][1],)
        else:
            return False
        return _files_present(root, required)
    except (OSError, ValueError, AttributeError):
        return False
