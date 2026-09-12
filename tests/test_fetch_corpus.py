from __future__ import annotations

import pytest

from scripts.ml.fetch_corpus import (
    ALPHABET,
    MAX_SENTENCE,
    MIN_SENTENCE,
    normalise,
    sentences,
    strip_boilerplate,
)


def test_accents_fold_onto_their_base_letter() -> None:
    assert normalise("perché città più") == "PERCHE CITTA PIU"
    assert normalise("Èva è così") == "EVA E COSI"


def test_apostrophes_and_quotes_become_the_word_break_they_stand_for() -> None:
    assert normalise("L'ultima") == "L ULTIMA"
    assert normalise("l’altro") == "L ALTRO"  # noqa: RUF001 - the typographic one
    assert normalise("«dell'acqua»") == " DELL ACQUA "


def test_punctuation_maps_onto_the_two_marks_the_alphabet_has() -> None:
    assert normalise("bene; poi: via") == "BENE, POI, VIA"
    assert normalise("davvero?! si") == "DAVVERO.. SI"


def test_a_sentence_survives_only_if_every_character_is_spellable() -> None:
    kept = sentences("NEL 1881 ANDAI VIA DA CASA MIA PER SEMPRE. IL CANE DORMIVA SUL DIVANO ROSSO.")
    assert kept == ["IL CANE DORMIVA SUL DIVANO ROSSO."]
    for sentence in kept:
        assert set(sentence) <= ALPHABET


def test_removing_a_quote_does_not_leave_a_space_before_the_punctuation() -> None:
    kept = sentences('E ALVARO, «L UOMO DI FUOCO» . POI TACQUE PER UN LUNGO MOMENTO.')

    assert kept[0] == "E ALVARO, L UOMO DI FUOCO."
    for sentence in kept:
        assert " ." not in sentence
        assert " ," not in sentence


@pytest.mark.parametrize(
    "text",
    [
        "TROPPO CORTA.",
        "PAROLA UNA DUE.",
        "UNA FRASE SENZA PUNTO FINALE CHE NON FINISCE MAI",
    ],
)
def test_fragments_that_are_not_sentences_are_dropped(text: str) -> None:
    assert sentences(text) == []


def test_length_bounds_are_applied_to_the_normalised_sentence() -> None:
    short = "UNO DUE TRE QUA."
    long = ("PAROLA " * 40) + "FINE."
    assert len(short) < MIN_SENTENCE
    assert len(long) > MAX_SENTENCE
    assert sentences(short + " " + long) == []


def test_only_the_work_between_the_markers_is_kept() -> None:
    text = (
        "The Project Gutenberg eBook of Qualcosa\nlicence noise\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK QUALCOSA ***\n"
        "Il vero testo.\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK QUALCOSA ***\n"
        "trademark footer\n"
    )
    kept = strip_boilerplate(text)

    assert "Il vero testo." in kept
    assert "licence noise" not in kept
    assert "trademark footer" not in kept


def test_text_without_markers_is_passed_through_rather_than_emptied() -> None:
    assert strip_boilerplate("Solo il testo.") == "Solo il testo."
