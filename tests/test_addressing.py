from datetime import date

import pytest

from fi_rag_eval.addressing import AddressError, ChunkAddress, slugify


def test_round_trips_a_clause_address() -> None:
    address = ChunkAddress("lounais-suomi", date(2024, 8, 1), 26)
    assert str(address) == "lounais-suomi@2024-08-01#26"
    assert ChunkAddress.parse(str(address)) == address


def test_round_trips_a_sub_clause_address() -> None:
    address = ChunkAddress("lounais-suomi", date(2024, 8, 1), 2, "biojatteella")
    assert str(address) == "lounais-suomi@2024-08-01#2.biojatteella"
    assert ChunkAddress.parse(str(address)) == address


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "lounais-suomi#26",
        "lounais-suomi@2024-08-01",
        "lounais-suomi@2024-8-1#26",
        "lounais-suomi@2024-08-01#0",
        "lounais-suomi@2024-08-01#26.",
        "lounais-suomi@2024-02-31#26",
        "Lounais-Suomi@2024-08-01#26",
        "lounais-suomi@2024-08-01#26 § tyhjennysvalit",
    ],
)
def test_rejects_malformed_addresses(raw: str) -> None:
    with pytest.raises(AddressError):
        ChunkAddress.parse(raw)


def test_rejects_a_non_positive_clause_on_construction() -> None:
    with pytest.raises(AddressError):
        ChunkAddress("lounais-suomi", date(2024, 8, 1), 0)


def test_sorts_by_authority_then_date_then_clause() -> None:
    unsorted = [
        ChunkAddress("lounais-suomi", date(2024, 8, 1), 26),
        ChunkAddress("lounais-suomi", date(2024, 8, 1), 2, "biojatteella"),
        ChunkAddress("lounais-suomi", date(2023, 7, 1), 26),
    ]
    assert [str(a) for a in sorted(unsorted)] == [
        "lounais-suomi@2023-07-01#26",
        "lounais-suomi@2024-08-01#2.biojatteella",
        "lounais-suomi@2024-08-01#26",
    ]


def test_slugify_folds_finnish_vowels_without_lemmatising() -> None:
    assert slugify("Biojätteellä") == "biojatteella"
    assert slugify("Saostussäiliöllä") == "saostussailiolla"
    assert slugify("Aluekeräysalueella") == "aluekerays-alueella".replace("-", "")


def test_slugify_rejects_a_word_with_no_usable_characters() -> None:
    with pytest.raises(AddressError):
        slugify("•—")
