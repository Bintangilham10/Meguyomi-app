"""Small, deterministic edits that make machine output sound like dialogue."""

import re


DIALOGUE_STYLE_VERSION = "id-dialogue-v3"

_DIALOGUE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bterima\s+kasih\b", "makasih"),
    (r"\btidak\s+apa(?:-|\s)apa\b", "nggak apa-apa"),
    (r"\bmari\s+kita\b", "ayo kita"),
    (r"\bapakah\b", "apa"),
    (r"\bmengapa\b", "kenapa"),
    (r"\bbagaimana\b", "gimana"),
    (r"\bbenar-benar\b", "bener-bener"),
    (r"\bsebaiknya\b", "mending"),
    (r"\btelah\b", "udah"),
    (r"\bsudah\b", "udah"),
    (r"\bhanya\b", "cuma"),
    (r"\bsaja\b", "aja"),
    (r"\bseperti\s+itu\b", "kayak gitu"),
    (r"\bseperti\s+ini\b", "kayak gini"),
    (r"\bseperti\b", "kayak"),
    (r"\bkemudian\b", "nanti"),
    (r"\bnamun\b", "tapi"),
    (r"\btetapi\b", "tapi"),
    (r"\bingin\b", "mau"),
    (r"\btidak\b", "nggak"),
    (r"\bmengerti\b", "ngerti"),
    (r"\bsaya\b", "aku"),
    (r"\banda\b", "kamu"),
)
_COMMON_VERBS = (
    "pergi|datang|pulang|makan|minum|tidur|menunggu|membantu|melihat|"
    "mendengar|berjalan|berlari|berbicara|membaca|menulis|bertemu|belajar|bekerja"
)
_CONTEXTUAL_REPLACEMENTS = (
    (rf"\bakan\b(?=\s+(?:{_COMMON_VERBS})\b)", "bakal"),
    (rf"\bsedang\b(?=\s+(?:{_COMMON_VERBS})\b)", "lagi"),
    (rf"\bdapat\b(?=\s+(?:{_COMMON_VERBS})\b)", "bisa"),
)
_INTENSIFIER = re.compile(
    r"\bsangat\s+(bagus|baik|buruk|indah|kuat|lemah|cepat|lambat|panas|dingin|"
    r"sulit|mudah|dekat|jauh|penting|lucu|senang|sedih|lelah|lapar|haus|mahal|murah)"
    r"\b(?!-)",
    re.IGNORECASE,
)


def _match_case(match: re.Match[str], replacement: str) -> str:
    original = match.group(0)
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper():
        prefix = match.string[:match.start()].rstrip(" \t\r\n\"'([{\u201c\u2018")
        if not prefix or prefix[-1] in ".!?:":
            return replacement[:1].upper() + replacement[1:]
    return replacement


def naturalize_indonesian(text: str, *, region_type: str = "dialogue") -> str:
    """Apply bounded conversational edits to machine-translated dialogue."""
    if region_type != "dialogue":
        return text.strip()

    result = text.strip()
    for pattern, replacement in (*_DIALOGUE_REPLACEMENTS, *_CONTEXTUAL_REPLACEMENTS):
        result = re.sub(
            pattern,
            lambda match, value=replacement: _match_case(match, value),
            result,
            flags=re.IGNORECASE,
        )
    # A bounded adjective list avoids mangling negation or multiword phrases.
    result = _INTENSIFIER.sub(
        lambda match: _match_case(match, f"{match.group(1).lower()} banget"),
        result,
    )
    return result
