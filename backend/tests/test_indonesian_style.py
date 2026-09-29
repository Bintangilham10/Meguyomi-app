import pytest

from app.services.indonesian_style import naturalize_indonesian


def test_dialogue_uses_conversational_indonesian() -> None:
    assert naturalize_indonesian(
        "Saya tidak mengerti. Apakah Anda sudah selesai? Terima kasih."
    ) == "Aku nggak ngerti. Apa kamu udah selesai? Makasih."


def test_intensifier_moves_after_adjective() -> None:
    assert naturalize_indonesian("Itu sangat bagus dan benar-benar indah.") == (
        "Itu bagus banget dan bener-bener indah."
    )


def test_common_formal_verbs_are_relaxed_in_dialogue() -> None:
    assert naturalize_indonesian(
        "Saya akan datang kemudian. Saya sedang menunggu dan dapat membantu."
    ) == "Aku bakal datang nanti. Aku lagi menunggu dan bisa membantu."


def test_titles_and_sound_effects_are_preserved() -> None:
    text = "SANGAT BISING!"
    assert naturalize_indonesian(text, region_type="title") == text
    assert naturalize_indonesian(text, region_type="sfx") == text


def test_caption_keeps_a_clear_register() -> None:
    assert naturalize_indonesian(
        "Saya sedang menunggu. Apakah dia sudah datang?",
        region_type="caption",
    ) == "Saya sedang menunggu. Apakah dia sudah datang?"


def test_because_clause_is_not_changed_into_an_unrelated_connector() -> None:
    assert naturalize_indonesian("Aku pergi karena itu bagus.") == (
        "Aku pergi karena itu bagus."
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Hadiah yang aku dapat berukuran sedang.", "Hadiah yang aku dapat berukuran sedang."),
        ("Aku yakin akan kemampuan Rin.", "Aku yakin akan kemampuan Rin."),
        ("Begitu dia tiba, aku pergi.", "Begitu dia tiba, aku pergi."),
        ("Aku sangat tidak nyaman.", "Aku sangat nggak nyaman."),
        ("Dia sangat ingin pergi.", "Dia sangat mau pergi."),
        ("Sangat bagus, Rin!", "Bagus banget, Rin!"),
        ("SAYA TIDAK MENGERTI!", "AKU NGGAK NGERTI!"),
        ('"Saya tidak tahu."', '"Aku nggak tahu."'),
        ("Rin dan Saya pergi ke Osaka pukul 10.30.", "Rin dan aku pergi ke Osaka pukul 10.30."),
    ],
)
def test_dialogue_preserves_meaning_case_names_and_numbers(source, expected) -> None:
    assert naturalize_indonesian(source) == expected
    assert naturalize_indonesian(expected) == expected
