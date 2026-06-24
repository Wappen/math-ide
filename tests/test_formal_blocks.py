"""Tests for formal-block detection + preamble split (issue #4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from math_ide.ingest import build_math_document
from math_ide.ingest.formal_blocks import (
    blocks_from_text_node,
    match_formal_label,
)
from math_ide.schema import (
    Corollary,
    Definition,
    Example,
    Lemma,
    Paragraph,
    Proof,
    Remark,
    Theorem,
)

FIXTURE = Path(__file__).parent / "fixtures" / "example_docling.json"


def _node(text: str, *, charspan=None, page_no=1):
    span = charspan or [0, len(text)]
    return {
        "label": "text",
        "text": text,
        "orig": text,
        "prov": [
            {
                "page_no": page_no,
                "bbox": {"l": 72.0, "t": 720.0, "r": 522.0, "b": 700.0,
                         "coord_origin": "BOTTOMLEFT"},
                "charspan": span,
            }
        ],
    }


def _one_block(text: str):
    blocks = blocks_from_text_node("doc", _node(text), 0)
    assert len(blocks) == 1
    return blocks[0]


# ---------------------------------------------------------------------------
# Label matching grammar
# ---------------------------------------------------------------------------


def test_match_clean_definition():
    m = match_formal_label("Definition 1.1 (Menge): Eine Menge ist ...")
    assert m is not None
    assert m.block_class is Definition
    assert m.number == "1.1"
    assert m.defined_name == "Menge"
    assert m.label_start == 0


def test_citation_in_prose_is_not_a_label():
    # "Nach Definition 1.1 ist ..." has a number but no body separator and is
    # not at the node start -> treated as a citation, not a block header.
    assert match_formal_label("Nach Definition 1.1 ist eine Menge bestimmt.") is None


def test_preamble_then_label():
    text = (
        "Ein wichtiges Konzept der Analysis ist die Injektivitaet. "
        "Definition 1.2 (Injektivitaet): Eine Abbildung f: X -> Y ..."
    )
    m = match_formal_label(text)
    assert m is not None
    assert m.defined_name == "Injektivitaet"
    assert m.number == "1.2"
    assert text[: m.label_start].strip() == (
        "Ein wichtiges Konzept der Analysis ist die Injektivitaet."
    )


# ---------------------------------------------------------------------------
# False-positive guards (issue #4): keyword as a word PREFIX or inside a
# hyphenated compound must NOT be detected as a formal block header.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # Keyword is a prefix of a longer word -> trailing boundary rejects it.
        "Definitionen sind in der Mathematik wichtig.",
        "Beweise folgen meist aus den Axiomen.",
        "Satzbau ist in formalen Texten entscheidend.",
        "Lemmata werden oft als Hilfssaetze genutzt.",
        # Keyword opens a hyphenated compound -> bare '-' is not a separator.
        "Das Lemma-Verfahren ist sehr nuetzlich.",
        "Der Definitions-Bereich einer Funktion ist X.",
    ],
)
def test_keyword_prefix_or_compound_is_not_a_label(text):
    assert match_formal_label(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "Definitionen sind in der Mathematik wichtig.",
        "Beweise folgen meist aus den Axiomen.",
        "Das Lemma-Verfahren ist sehr nuetzlich.",
    ],
)
def test_keyword_prefix_or_compound_becomes_paragraph(text):
    block = _one_block(text)
    assert type(block) is Paragraph
    assert block.text == text


# ---------------------------------------------------------------------------
# Legitimate headers still detect after the boundary tightening.
# ---------------------------------------------------------------------------


def test_legit_headers_still_detected():
    # Defined name + number + colon.
    m = match_formal_label("Definition 1.1 (Menge): Eine Menge ist ...")
    assert m is not None and m.block_class is Definition
    assert m.number == "1.1" and m.defined_name == "Menge"

    # Keyword at node start with a number but no separator (at_start header).
    m = match_formal_label("Satz 2.3 Jede Cauchy-Folge konvergiert.")
    assert m is not None and m.block_class is Theorem
    assert m.number == "2.3"

    # Colon separator with no defined name.
    m = match_formal_label("Theorem 2.1:")
    assert m is not None and m.block_class is Theorem
    assert m.number == "2.1"

    # '--' separator still introduces a body (bare '-' does not).
    m = match_formal_label("Lemma 3.2 -- Hilfsaussage.")
    assert m is not None and m.block_class is Lemma
    block = _one_block("Lemma 3.2 -- Hilfsaussage.")
    assert type(block) is Lemma
    assert block.body == "Hilfsaussage."


# ---------------------------------------------------------------------------
# Distinct classes (German + English) -- inline tests, not in the fixture
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, cls",
    [
        ("Theorem 2.1: Aussage.", Theorem),
        ("Satz 2.1 (Zwischenwertsatz): Sei f stetig.", Theorem),
        ("Lemma 3.2: Hilfsaussage.", Lemma),
        ("Corollary 3.3: Folgt direkt.", Corollary),
        ("Folgerung 3.3: Folgt direkt.", Corollary),
        ("Proof: Sei x gegeben.", Proof),
        ("Beweis. Sei x gegeben.", Proof),
        ("Beispiel 4.1: Betrachte N.", Example),
        ("Remark: Beachte dies.", Remark),
        ("Bemerkung 5.1: Beachte dies.", Remark),
    ],
)
def test_keyword_maps_to_distinct_class(text, cls):
    block = _one_block(text)
    assert type(block) is cls  # distinct class, not a shared FormalBlock enum


def test_satz_maps_to_theorem_with_name_and_number():
    block = _one_block("Satz 2.3 (Vollstaendigkeit): Jede Cauchy-Folge konvergiert.")
    assert type(block) is Theorem
    assert block.number == "2.3"
    assert block.defined_name == "Vollstaendigkeit"
    assert block.body == "Jede Cauchy-Folge konvergiert."
    assert block.preamble is None


# ---------------------------------------------------------------------------
# Block construction / splitting
# ---------------------------------------------------------------------------


def test_clean_definition_no_preamble():
    block = _one_block("Definition 1.1 (Menge): Eine Menge ist eine Zusammenfassung.")
    assert type(block) is Definition
    assert block.number == "1.1"
    assert block.defined_name == "Menge"
    assert block.preamble is None
    assert block.body == "Eine Menge ist eine Zusammenfassung."


def test_preamble_split_into_preamble_field_and_body():
    text = (
        "Ein wichtiges Konzept der Analysis ist die Injektivitaet. "
        "Definition 1.2 (Injektivitaet): Eine Abbildung f: X -> Y heisst injektiv."
    )
    block = _one_block(text)
    assert type(block) is Definition
    assert block.defined_name == "Injektivitaet"
    assert block.preamble == (
        "Ein wichtiges Konzept der Analysis ist die Injektivitaet."
    )
    assert block.body == "Eine Abbildung f: X -> Y heisst injektiv."


def test_no_match_text_becomes_paragraph():
    block = _one_block("Nach Definition 1.1 ist eine Menge durch Elemente bestimmt.")
    assert type(block) is Paragraph
    assert block.text.startswith("Nach Definition 1.1")


def test_preamble_bbox_is_left_of_block_bbox():
    text = (
        "Ein wichtiges Konzept der Analysis ist die Injektivitaet. "
        "Definition 1.2 (Injektivitaet): Eine Abbildung."
    )
    node = _node(text)
    block = blocks_from_text_node("doc", node, 0)[0]
    full = node["prov"][0]["bbox"]
    # block starts partway through the line -> its left edge is right of the node
    # left edge (the preamble occupies the left part).
    assert block.source_bbox.l > full["l"]
    assert block.source_bbox.r == pytest.approx(full["r"])


# ---------------------------------------------------------------------------
# Fixture acceptance
# ---------------------------------------------------------------------------


def test_fixture_acceptance_points():
    docling = json.loads(FIXTURE.read_text(encoding="utf-8"))
    doc = build_math_document(docling)
    sec1 = doc.blocks[0]

    menge = sec1.children[0]
    assert type(menge) is Definition
    assert menge.defined_name == "Menge"
    assert menge.number == "1.1"
    assert menge.preamble is None

    citation_para = sec1.children[1]
    assert type(citation_para) is Paragraph

    inj = sec1.children[2]
    assert type(inj) is Definition
    assert inj.defined_name == "Injektivitaet"
    assert inj.number == "1.2"
    assert inj.preamble == (
        "Ein wichtiges Konzept der Analysis ist die Injektivitaet."
    )
    assert inj.body.startswith("Eine Abbildung f: X -> Y")
