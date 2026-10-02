"""Install pinned OCR models and convert NLLB to int8 once, while online."""
import json
import os
from shutil import rmtree

os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["TRANSFORMERS_OFFLINE"] = "0"

from ctranslate2.converters import TransformersConverter
from huggingface_hub import snapshot_download
from transformers import AutoTokenizer
import easyocr

from model_config import CHINESE_MODELS, MANIFEST, MODEL_ROOT, MODEL_VERSIONS, NLLB_REPO, NLLB_REVISION, OCR_REPO, OCR_REVISION, models_present, translation_models_present


def main() -> None:
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    if all(models_present(source_language=language) for language in MODEL_VERSIONS):
        print("All local models are already installed.", flush=True)
        return
    print("Installing manga OCR and CRAFT detector...", flush=True)
    snapshot_download(
        OCR_REPO, revision=OCR_REVISION, local_dir=MODEL_ROOT / "manga-ocr",
        allow_patterns=["*.json", "*.txt", "pytorch_model.bin"],
    )
    easyocr.Reader(
        ["ja", "en"], gpu=False, recognizer=False,
        model_storage_directory=str(MODEL_ROOT / "easyocr"),
        user_network_directory=str(MODEL_ROOT / "easyocr-user"),
        download_enabled=True,
    )
    for language, (code, _) in CHINESE_MODELS.items():
        print(f"Installing {language} OCR...", flush=True)
        easyocr.Reader(
            [code, "en"], gpu=False, detector=False,
            model_storage_directory=str(MODEL_ROOT / "easyocr"),
            user_network_directory=str(MODEL_ROOT / "easyocr-user"),
            download_enabled=True, verbose=False,
        )
    # Keep partial downloads across interrupted setup runs.
    source = MODEL_ROOT / "nllb-source"
    if not translation_models_present():
        print("Downloading NLLB source weights...", flush=True)
        snapshot_download(
            NLLB_REPO, revision=NLLB_REVISION, local_dir=source,
            allow_patterns=["*.json", "*.model", "pytorch_model.bin"],
        )
        tokenizer = AutoTokenizer.from_pretrained(source, local_files_only=True)
        tokenizer.save_pretrained(MODEL_ROOT / "tokenizer")
        print("Converting NLLB to int8...", flush=True)
        TransformersConverter(str(source)).convert(
            str(MODEL_ROOT / "nllb"), quantization="int8", force=True,
        )
    else:
        print("Reusing installed NLLB translation model.", flush=True)
    temporary_manifest = MODEL_ROOT / "manifest.json.part"
    temporary_manifest.write_text(json.dumps(MANIFEST, indent=2), encoding="utf-8")
    temporary_manifest.replace(MODEL_ROOT / "manifest.json")
    if not all(models_present(source_language=language) for language in MODEL_VERSIONS):
        raise RuntimeError("Model setup did not produce all required files.")
    if source.exists():
        rmtree(source)
    print("Models ready for offline OCR and translation.", flush=True)


if __name__ == "__main__":
    main()
