from __future__ import annotations

import re
import unicodedata


RESTAURANT_DISPLAY_NAME_OVERRIDES = {
    "maitre krousty": "Krousty Master",
    "crousty best": "Asian Passion",
    "asian passion ex crousty best": "Asian Passion",
}

LEGACY_RESTAURANT_NAME_PATTERNS = (
    (re.compile(r"\bma[iî]tre\s+krousty\b", flags=re.IGNORECASE), "Krousty Master"),
    (
        re.compile(
            r"\basian\s+passion\s*\(\s*ex\s+crousty\s+best\s*\)",
            flags=re.IGNORECASE,
        ),
        "Asian Passion",
    ),
    (re.compile(r"\bcrousty\s+best\b", flags=re.IGNORECASE), "Asian Passion"),
)


def normalize_restaurant_identity(value: object) -> str:
    raw_value = str(value or "").strip()
    normalized = unicodedata.normalize("NFKD", raw_value)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized.casefold())
    return " ".join(normalized.split())


def canonical_restaurant_display_name(value: object) -> str:
    raw_value = str(value or "").strip()
    override = RESTAURANT_DISPLAY_NAME_OVERRIDES.get(normalize_restaurant_identity(raw_value))
    return override or raw_value


def canonical_restaurant_lookup_key(value: object) -> str:
    canonical_name = canonical_restaurant_display_name(value)
    return normalize_restaurant_identity(canonical_name).replace(" ", "")


def canonicalize_restaurant_names_in_text(value: str | None) -> str:
    canonicalized = value or ""
    for pattern, replacement in LEGACY_RESTAURANT_NAME_PATTERNS:
        canonicalized = pattern.sub(replacement, canonicalized)
    return canonicalized


def text_contains_legacy_restaurant_name(value: str | None) -> bool:
    text = value or ""
    return any(pattern.search(text) is not None for pattern, _replacement in LEGACY_RESTAURANT_NAME_PATTERNS)
