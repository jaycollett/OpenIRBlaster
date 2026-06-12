"""Tests for translation file consistency."""

from __future__ import annotations

import json
from pathlib import Path

COMPONENT_DIR = (
    Path(__file__).parent.parent / "custom_components" / "openirblaster"
)


def test_en_translation_matches_strings_json() -> None:
    """translations/en.json must be an exact copy of strings.json.

    For custom integrations only translations/*.json is read at runtime, so
    any drift in strings.json silently never reaches users. CI enforces this
    too; this test locks the contract in locally.
    """
    strings = json.loads((COMPONENT_DIR / "strings.json").read_text())
    en = json.loads(
        (COMPONENT_DIR / "translations" / "en.json").read_text()
    )

    assert strings == en, (
        "strings.json and translations/en.json have drifted; copy "
        "strings.json over translations/en.json"
    )


def test_exception_translations_cover_service_validation_keys() -> None:
    """Every translation_key raised in services.py has an exceptions entry."""
    strings = json.loads((COMPONENT_DIR / "strings.json").read_text())
    exceptions = strings.get("exceptions", {})

    for key in ("config_entry_not_found", "code_not_found", "no_pending_code"):
        assert key in exceptions, f"Missing exceptions entry for {key}"
        assert exceptions[key].get("message"), f"Empty message for {key}"
