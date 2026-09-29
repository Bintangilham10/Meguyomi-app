from typing import Literal


SourceLanguage = Literal["ja", "zh-Hans", "zh-Hant"]
JobSourceLanguage = Literal["auto", "ja", "zh-Hans", "zh-Hant"]
MODEL_VERSIONS = {
    "ja": "manga-ocr-nllb600m-int8-v1",
    "zh-Hans": "easyocr-zh-hans-nllb600m-int8-v1",
    "zh-Hant": "easyocr-zh-hant-nllb600m-int8-v1",
}
