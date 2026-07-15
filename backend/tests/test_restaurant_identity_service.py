from app.services.restaurant_identity_service import (
    canonical_restaurant_display_name,
    canonical_restaurant_lookup_key,
    canonicalize_restaurant_names_in_text,
    text_contains_legacy_restaurant_name,
)


def test_crousty_best_is_an_asian_passion_alias() -> None:
    assert canonical_restaurant_display_name("Crousty Best") == "Asian Passion"
    assert canonical_restaurant_display_name("Asian passion (ex Crousty Best)") == "Asian Passion"
    assert canonical_restaurant_lookup_key("Crousty Best") == canonical_restaurant_lookup_key("Asian Passion")


def test_legacy_restaurant_names_are_replaced_in_email_text() -> None:
    value = "Re: dossier Crousty Best - signature Maître Krousty"

    canonicalized = canonicalize_restaurant_names_in_text(value)

    assert canonicalized == "Re: dossier Asian Passion - signature Krousty Master"
    assert text_contains_legacy_restaurant_name(value) is True
    assert text_contains_legacy_restaurant_name(canonicalized) is False
