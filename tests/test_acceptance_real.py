r"""Offline full-loop acceptance over the *real* Docling export (issue #24).

The fast offline acceptance suite (``test_acceptance_e2e.py``) runs against the
hand-authored *synthetic* fixture (``fixtures/example_docling.json``), whose
idealized input encodes a ``Definition 1.1`` citation, the ASCII spelling
``Injektivitaet``, the unicode ``ε``/``a_n`` tokens and an ℝ convergence domain.
None of those match what a live Docling 2.107.0 conversion of ``example.pdf``
actually produces. This module closes that coverage gap **offline**: it runs the
same public pipeline (``ingest_structure`` -> ``MockResolver`` via ``run_full``)
over the committed *real* Docling export (``fixtures/example_docling_real.json``),
asserting REAL behaviour in one end-to-end pass.

The per-symptom real-fixture suites already cover the loop in depth:

* ``test_structure_real.py`` (#22) — title/footer/section structure;
* ``test_resolution_real.py`` (#21) — divergent-spelling symbol resolution;
* ``test_inline_occurrences.py`` (#23) — inline-prose ``inline_symbol`` occurrences.

So this file stays deliberately small and orthogonal: a single
structure -> occurrences -> resolution -> navigation -> render pass that ties the
stages together, plus the **citation-absence** assertion that is the heart of
#24 — the real ``example.pdf`` contains no numbered cross-reference, so the live
pipeline yields ZERO citation occurrences (the synthetic fixture's
"Nach Definition 1.1 …" citation is idealized input the real PDF does not have).

The gated ``test_acceptance_e2e_live.py`` re-runs the *live* Docling conversion
of ``example.pdf`` and asserts the same real behaviour end-to-end.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from math_ide.ontology import MockResolver
from math_ide.ontology.occurrences import iter_blocks
from math_ide.pipeline import ingest_structure, run_full
from math_ide.renderer.navigation import build_ide_payload, concept_card, definition_target
from math_ide.renderer.render import render_document
from math_ide.schema import Definition, Formula, MathDocument, Section

REAL_FIXTURE = Path(__file__).parent / "fixtures" / "example_docling_real.json"


# ---------------------------------------------------------------------------
# Fixtures over the committed real Docling export
# ---------------------------------------------------------------------------


@pytest.fixture()
def real_structure_ready() -> MathDocument:
    """The real export ingested to ``structure_ready`` (no resolver yet)."""
    raw = json.loads(REAL_FIXTURE.read_text(encoding="utf-8"))
    return ingest_structure(raw)


@pytest.fixture()
def real_resolved() -> MathDocument:
    """The real export ingested + resolved by the deterministic MockResolver."""
    raw = json.loads(REAL_FIXTURE.read_text(encoding="utf-8"))
    doc = ingest_structure(raw)
    run_full(doc, resolver=MockResolver(), wait=True)
    return doc


# ---------------------------------------------------------------------------
# Lookups over the real document
# ---------------------------------------------------------------------------


def _def_block(doc: MathDocument, name: str) -> str:
    return next(
        b.id
        for b in iter_blocks(doc.blocks)
        if getattr(b, "defined_name", None) == name
    )


def _occ_token(doc: MathDocument, occ) -> str:
    formula = next(
        b
        for b in iter_blocks(doc.blocks)
        if isinstance(b, Formula) and b.id == occ.block_id
    )
    return formula.canonical_content[occ.span[0] : occ.span[1]]


def _symbol_occs(doc: MathDocument, token: str) -> list:
    return [
        o
        for o in doc.occurrences
        if o.kind == "formula_symbol"
        and o.span is not None
        and _occ_token(doc, o) == token
    ]


# ===========================================================================
# One end-to-end pass: structure -> occurrences -> resolution -> nav -> render
# ===========================================================================


def test_real_full_loop_structure_occurrences_resolution_navigation_render(
    real_resolved: MathDocument,
) -> None:
    """#24: the whole offline loop over the REAL Docling export agrees with the
    live artifacts — real section titles, real defined names, real latex tokens,
    deterministic go-to-definition, and a fully renderable ``ready`` page."""
    doc = real_resolved

    # -- STRUCTURE: the two real numbered headers are the only top-level Sections.
    top_sections = [b.title for b in doc.blocks if isinstance(b, Section)]
    assert top_sections == [
        "1 Grundbegriffe der Mengenlehre",
        "2 Folgen und Grenzwerte",
    ]
    # The document title is metadata (umlaut-repaired), not a Section peer.
    assert doc.title == "Testskript: Einführung in die Analysis"

    # -- STRUCTURE: exactly the three real definitions (umlaut name Injektivität).
    definitions = [
        b.defined_name for b in iter_blocks(doc.blocks) if isinstance(b, Definition)
    ]
    assert definitions == ["Menge", "Injektivität", "Konvergenz"]

    # -- OCCURRENCES: real latex tokens (spaced subscripts, ℕ set, \epsilon).
    conv = next(
        b
        for b in iter_blocks(doc.blocks)
        if isinstance(b, Formula) and "epsilon" in b.canonical_content
    )
    inj = next(
        b
        for b in iter_blocks(doc.blocks)
        if isinstance(b, Formula) and "forall x" in b.canonical_content
    )
    assert r"\epsilon" in conv.canonical_content  # not unicode ε
    assert r"\mathbb { N }" in conv.canonical_content  # ℕ domain, not ℝ
    assert "a _ { n }" in conv.canonical_content  # spaced subscript, not a_n
    assert "x _ { 1 }" in inj.canonical_content  # spaced subscript, not x₁

    # -- RESOLUTION + NAVIGATION: the threshold N / limit L / a_n / \epsilon link
    #    to the Konvergenz block; f / X link to the Injektivität block.
    konv_block = _def_block(doc, "Konvergenz")
    inj_block = _def_block(doc, "Injektivität")
    for token in (r"\epsilon", "N", "L", "a _ { n }"):
        occs = _symbol_occs(doc, token)
        assert occs, f"convergence formula must carry a {token!r} symbol"
        assert all(definition_target(doc, o) == konv_block for o in occs), token
    for token in ("f", "X"):
        occs = _symbol_occs(doc, token)
        assert occs, f"injectivity formula must carry a {token!r} symbol"
        assert all(definition_target(doc, o) == inj_block for o in occs), token

    # -- NAVIGATION: the set ℕ and the bound vars stay pending (no target).
    for token in (r"\mathbb { N }", "n", "x _ { 1 }"):
        occs = _symbol_occs(doc, token)
        assert occs, f"formula must carry a {token!r} symbol"
        assert all(definition_target(doc, o) is None for o in occs), token

    # -- CONCEPT CARD: Konvergenz exposes its formal meaning + semantic edges.
    konv = next(c for c in doc.concepts if c.name == "Konvergenz")
    card = concept_card(doc, konv.id)
    assert card["name"] == "Konvergenz"
    assert card["resolution_status"] == "resolved"
    assert card["formal_meaning"]
    assert card["neighbourhood"]["structural"]
    assert card["neighbourhood"]["semantic"]
    # The precomputed payload carries the same card the side panel renders.
    assert build_ide_payload(doc)["cards"][konv.id] == card

    # -- RENDER: the real document renders a ready page with the real heading.
    html = render_document(doc)
    assert 'data-ingestion-state="ready"' in html
    assert '<h2 class="section-title">1 Grundbegriffe der Mengenlehre</h2>' in html
    assert "math-ide-data" in html  # embedded navigation payload


# ===========================================================================
# Citation divergence — the heart of #24
# ===========================================================================


def test_real_export_has_zero_citation_occurrences(
    real_structure_ready: MathDocument,
    real_resolved: MathDocument,
) -> None:
    """#24 CITATION DIVERGENCE: ``example.pdf`` contains NO numbered
    cross-reference, so the real pipeline yields ZERO ``citation`` occurrences —
    at ``structure_ready`` and after resolution alike.

    The synthetic fixture's "Nach Definition 1.1 …" paragraph is idealized input
    that exercises the citation code path the real PDF does not contain. There is
    also no ``Definition 1.1`` cross-reference text anywhere in the real blocks."""
    for doc in (real_structure_ready, real_resolved):
        assert [o for o in doc.occurrences if o.kind == "citation"] == []

    # No block carries the fabricated "Nach Definition 1.1" cross-reference prose.
    def _block_text(b) -> str:
        return (
            getattr(b, "title", None)
            or getattr(b, "text", None)
            or getattr(b, "body", None)
            or ""
        )

    assert all(
        "Definition 1.1" not in _block_text(b)
        for b in iter_blocks(real_structure_ready.blocks)
    )


def test_real_occurrence_kinds_match_live_artifacts(
    real_structure_ready: MathDocument,
) -> None:
    """#24: the real ``by kind`` summary has three defined names, many formula
    symbols, inline-prose symbols (#23) and — crucially — no citation.

    Counts are asserted as ``>= 1`` / presence rather than brittle exact totals
    so the offline real fixture and a live re-conversion can both satisfy them
    (the live formula model can vary its exact symbol vocabulary)."""
    counts = Counter(o.kind for o in real_structure_ready.occurrences)
    assert counts["defined_name"] == 3  # Menge / Injektivität / Konvergenz
    assert counts["formula_symbol"] > 0
    assert counts["inline_symbol"] > 0  # #23 inline prose notation
    assert counts["citation"] == 0  # #24: the real PDF has no cross-reference
