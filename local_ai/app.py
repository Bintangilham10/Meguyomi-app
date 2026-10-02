import base64
import logging
from contextlib import asynccontextmanager, contextmanager
from io import BytesIO
from threading import Lock
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from PIL import Image

from engine import LocalEngine
from model_config import MODEL_VERSION, MODEL_VERSIONS, models_present

MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
engine = LocalEngine()
inference_lock = Lock()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app):
    try:
        engine.load()
    except Exception:
        logger.exception("Local models could not be loaded; run model-setup and restart local-ai.")
    yield


app = FastAPI(title="Meguyomi Local AI", version="1.0.0", lifespan=lifespan)
Text = Annotated[str, Field(min_length=1, max_length=1000)]
SourceLanguage = Literal["ja", "zh-Hans", "zh-Hant"]


class ImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_base64: str = Field(min_length=1, max_length=(MAX_IMAGE_BYTES + 2) // 3 * 4)


class OCRRequest(ImageRequest):
    source_language: SourceLanguage = "ja"
    quality_reason: Literal["placement_overlap", "source_mask_failure", "text_does_not_fit", "unsafe_layout"] | None = None


class TranslateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    texts: list[Text] = Field(min_length=1, max_length=16)
    source_language: SourceLanguage = "ja"
    target_language: Literal["id"] = "id"


def decode_image(encoded):
    try:
        raw = base64.b64decode(encoded, validate=True)
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("Image size limit exceeded.")
        with Image.open(BytesIO(raw)) as image:
            if image.format != "PNG" or image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError("Invalid PNG dimensions.")
            return image.convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise HTTPException(422, detail={"code": "INVALID_IMAGE"}) from error


@contextmanager
def inference(source_language="ja", *, failure_code="AI_TRANSLATION_FAILED"):
    required_languages = set(MODEL_VERSIONS) if source_language == "auto" else {source_language}
    if not engine.ready or not required_languages.issubset(engine.ready_languages):
        raise HTTPException(503, detail={"code": "AI_MODEL_NOT_READY"})
    if not inference_lock.acquire(blocking=False):
        raise HTTPException(429, detail={"code": "AI_BUSY"}, headers={"Retry-After": "30"})
    try:
        yield
    except (ValueError, RuntimeError) as error:
        logger.exception("Local inference failed")
        raise HTTPException(422, detail={"code": failure_code}) from error
    finally:
        inference_lock.release()


@app.get("/health")
def health():
    languages = {language: {"ready": engine.ready and language in engine.ready_languages,
                            "installed": models_present(source_language=language)} for language in MODEL_VERSIONS}
    return {"status": "ok", "ready": engine.ready, "modelsInstalled": models_present(),
            "modelVersion": MODEL_VERSION, "languages": languages}


@app.get("/ready")
def ready():
    if not engine.ready:
        raise HTTPException(503, detail={"code": "AI_MODEL_NOT_READY"})
    return health()


@app.post("/ocr")
def ocr(request: OCRRequest):
    with inference(request.source_language):
        with decode_image(request.image_base64) as image:
            return {"regions": engine.ocr(image, request.quality_reason, request.source_language),
                    "model_version": MODEL_VERSIONS[request.source_language]}


@app.post("/detect-language")
def detect_language(request: ImageRequest):
    with inference("auto", failure_code="AI_LANGUAGE_DETECTION_FAILED"):
        with decode_image(request.image_base64) as image:
            language, confidence = engine.detect_language(image)
            return {"source_language": language, "confidence": confidence,
                    "model_version": MODEL_VERSIONS.get(language)}


@app.post("/translate")
def translate(request: TranslateRequest):
    if any(not text.strip() for text in request.texts):
        raise HTTPException(422, detail={"code": "EMPTY_TEXT"})
    with inference(request.source_language):
        return {"translations": engine.translate(request.texts, request.source_language),
                "model_version": MODEL_VERSIONS[request.source_language]}
