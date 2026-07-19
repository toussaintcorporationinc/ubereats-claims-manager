from app.services.autopilot_identity_repair_service import extract_customer_name_deep, extract_restaurant_name
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


def test_starred_gmail_identity_matches_legacy_name_to_active_restaurant() -> None:
    restaurant_name = extract_restaurant_name(
        "Commande 3D22E pour Crousty Best, client Antoine N.",
        ["Asian Passion", "Frit Dodo"],
    )

    assert restaurant_name == "Asian Passion"


def test_starred_gmail_identity_reads_elided_french_customer_name() -> None:
    customer_name = extract_customer_name_deep(
        "Je conteste l'annulation de la commande d'Antoine N numero de commande 3D22E."
    )

    assert customer_name == "Antoine N"


def test_starred_gmail_identity_tolerates_punctuation_after_de() -> None:
    customer_name = extract_customer_name_deep(
        "Bonsoir je veux contester l'annulation de commande de. BIJADHUR K "
        "numero de commande 41D7C."
    )

    assert customer_name == "BIJADHUR K"
