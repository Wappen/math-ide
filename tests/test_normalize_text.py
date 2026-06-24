"""Tests for the decomposed-diaeresis repair (issue #18).

Live Docling sometimes emits a *decomposed* diaeresis: a standalone diaeresis
mark — the spacing diaeresis ``"¨"`` (U+00A8) or the combining diaeresis
(U+0308) — optionally followed by a single space, sitting before the vowel it
belongs on, e.g. ``"f¨ ur"`` instead of ``"für"``. Issue #17 attempts an
upstream fix; this module is the deterministic, offline fallback (#18) that
re-attaches the mark to the following ``a``/``o``/``u`` so the rest of the
ingestion pipeline (formal-block detection, concept naming) sees corrected
text.

These tests are fully offline: ``normalize_text`` is a pure string function and
the end-to-end check builds a small synthetic Docling dict in-test rather than
relying on any installed SDK or PDF fixture.
"""

from __future__ import annotations

import pytest

from math_ide.ingest import build_math_document
from math_ide.ingest.docling_adapter import normalize_text
from math_ide.schema import Definition, Section


# ---------------------------------------------------------------------------
# Unit: normalize_text repairs the decomposed diaeresis
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "corrupt, expected",
    [
        # spacing diaeresis U+00A8 + space + vowel
        ("f¨ ur", "für"),
        ("Injektivit¨ at", "Injektivität"),
        ("ann¨ ahern", "annähern"),
        # no-space variants
        ("f¨ur", "für"),
        ("Injektivit¨at", "Injektivität"),
        # uppercase vowels -> uppercase umlauts
        ("¨ Aquivalenz", "Äquivalenz"),
        ("¨Aquivalenz", "Äquivalenz"),
        ("¨ Offnung", "Öffnung"),
        ("¨ Uberdeckung", "Überdeckung"),
        # combining diaeresis U+0308 sitting *before* the vowel
        ("f̈ ur", "für"),
        ("f̈ur", "für"),
    ],
)
def test_repairs_decomposed_diaeresis(corrupt, expected):
    assert normalize_text(corrupt) == expected


@pytest.mark.parametrize(
    "clean",
    [
        # ASCII transliteration must NOT be touched (no "ae" -> "ä").
        "Injektivitaet",
        # plain words with no diaeresis at all
        "Konvergenz",
        "Eine Abbildung",
        # already-correct precomposed umlauts stay precomposed (identity).
        "für",
        "Injektivität",
        "annähern",
        "Äquivalenz",
        # empty string
        "",
    ],
)
def test_identity_on_clean_text(clean):
    assert normalize_text(clean) == clean


def test_does_not_do_mojibake_repair():
    # Latin-1/UTF-8 mojibake is explicitly out of scope: "Ã¼" stays as-is.
    assert normalize_text("fÃ¼r") == "fÃ¼r"


def test_repairs_multiple_occurrences_in_one_string():
    corrupt = "f¨ ur die Injektivit¨ at muss man sich ann¨ ahern"
    assert normalize_text(corrupt) == "für die Injektivität muss man sich annähern"


# ---------------------------------------------------------------------------
# End-to-end: the adapter applies the repair before formal-block detection
# ---------------------------------------------------------------------------


def _corrupt_docling() -> dict:
    """A small Docling dict mirroring the example fixture's shape.

    The single ``text`` node carries a corrupted formal label (defined name
    ``"Injektivit¨ at"``) plus corrupted prose so we can prove the repair runs
    before both label parsing and concept naming.
    """
    return {
        "name": "corrupt_skript",
        "origin": {
            "mimetype": "application/pdf",
            "binary_hash": "deadbeef",
            "filename": "corrupt_skript.pdf",
        },
        "body": {
            "self_ref": "#/body",
            "children": [
                {"$ref": "#/texts/0"},
                {"$ref": "#/texts/1"},
            ],
        },
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "section_header",
                "level": 1,
                "text": "1 Mengen und Abbildungen",
                "orig": "1 Mengen und Abbildungen",
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": 72.0,
                            "t": 760.0,
                            "r": 320.0,
                            "b": 742.0,
                            "coord_origin": "BOTTOMLEFT",
                        },
                        "charspan": [0, 24],
                    }
                ],
            },
            {
                "self_ref": "#/texts/1",
                "label": "text",
                "text": (
                    "Definition 1.2 (Injektivit¨ at): Eine Abbildung f¨ ur "
                    "verschiedene Argumente, die sich nie ann¨ ahern."
                ),
                "orig": (
                    "Definition 1.2 (Injektivit¨ at): Eine Abbildung f¨ ur "
                    "verschiedene Argumente, die sich nie ann¨ ahern."
                ),
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": 72.0,
                            "t": 720.0,
                            "r": 523.0,
                            "b": 686.0,
                            "coord_origin": "BOTTOMLEFT",
                        },
                        "charspan": [0, 100],
                    }
                ],
            },
        ],
    }


def test_adapter_repairs_defined_name_and_prose():
    doc = build_math_document(_corrupt_docling())

    section = doc.blocks[0]
    assert isinstance(section, Section)

    definition = section.children[0]
    assert isinstance(definition, Definition)

    # The defined name (used downstream for concept naming) is the corrected
    # umlaut form, NOT the raw "Injektivit¨ at".
    assert definition.defined_name == "Injektivität"
    assert "¨" not in (definition.defined_name or "")

    # The body prose is corrected too: both "f¨ ur" and "ann¨ ahern" repaired.
    assert "für" in definition.body
    assert "annähern" in definition.body
    assert "¨" not in definition.body
