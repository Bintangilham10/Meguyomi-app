"""Conservative language selection from independent OCR readings of one page."""

import re
import unicodedata


KANA = re.compile(r"[\u3041-\u3096\u30a1-\u30fa]")
HAN = re.compile(r"[\u3400-\u9fff\U00020000-\U0002fa1f]")
TRADITIONAL = frozenset(
    "\u5011\u9019\u500b\u4f86\u70ba\u8aaa\u8a71\u8b1d\u55ce\u6c92\u9084\u6642\u6703\u5b78\u570b\u611b"
    "\u8b93\u5c0d\u9580\u958b\u95dc\u807d\u8eca\u96fb\u982d\u9ebc\u9ebd\u8072\u9ad4\u5f9e\u8cb7\u8ce3"
    "\u5beb\u8b80\u89ba\u89aa\u89c0\u898b\u8a8d\u8b58\u5c07\u904e\u9032\u9019\u908a\u9577\u66f8\u8207"
    "\u5be6\u8655\u4e82\u865f\u842c\u8209\u6a23\u6a5f\u7d93\u7d66\u7d50\u7e3d\u7e8c\u7dda\u8f49"
)


def _score(samples):
    count = 0
    weighted = 0.0
    accepted = []
    for text, confidence in samples:
        text = unicodedata.normalize("NFKC", text)
        characters = len(HAN.findall(text))
        if characters and confidence >= 0.35:
            count += characters
            weighted += characters * confidence
            accepted.append(text)
    return weighted / count if count >= 4 else 0.0, "".join(accepted)


def choose_language(japanese, chinese):
    scores = {language: _score(samples) for language, samples in chinese.items()}
    best_chinese = max((score for score, _ in scores.values()), default=0.0)
    kana_count = 0
    kana_regions = 0
    kana_weight = 0.0
    for text, confidence in japanese:
        text = unicodedata.normalize("NFKC", text)
        kana = len(KANA.findall(text))
        total = kana + len(HAN.findall(text))
        # Kanji alone is also Chinese. Require several actual kana, not punctuation.
        if kana >= 2 and kana / max(1, total) >= 0.2 and confidence >= 0.65:
            kana_regions += 1
            kana_count += kana
            kana_weight += kana * confidence
    japanese_score = kana_weight / kana_count if kana_count else 0.0
    if kana_count >= 4 and (kana_regions >= 2 or kana_count >= 6):
        # Manga OCR can hallucinate Japanese on Chinese: compare independent readers.
        if best_chinese < 0.6 or japanese_score >= best_chinese + 0.12:
            return "ja", japanese_score
    if best_chinese < 0.6:
        return None, 0.0
    if kana_count >= 4 and japanese_score >= best_chinese - 0.05:
        return None, 0.0

    simplified_score, _ = scores.get("zh-Hans", (0.0, ""))
    traditional_score, traditional_text = scores.get("zh-Hant", (0.0, ""))
    traditional_markers = len(set(traditional_text) & TRADITIONAL)
    # The traditional recognizer can substitute traditional glyphs on simplified
    # input too. Markers need a clear recognition advantage to change the script.
    if traditional_markers and traditional_score >= max(0.6, simplified_score + 0.15):
        return "zh-Hant", traditional_score
    # Shared Han characters do not distinguish the two Chinese writing systems.
    return ("zh-Hans", simplified_score) if simplified_score >= 0.6 else (None, 0.0)
