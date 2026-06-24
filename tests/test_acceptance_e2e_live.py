r"""Gated *live* Docling acceptance over ``example.pdf`` (issue #24).

Every other acceptance lane feeds the pipeline a pre-converted Docling JSON dict:
the synthetic fixture (``test_acceptance_e2e.py``) or the committed real export
(``test_acceptance_real.py`` and the per-symptom ``*_real.py`` suites). None of
them actually run the heavy ``docling`` PDF->JSON model. This module closes that
last gap: it re-runs the **live** conversion of ``example.pdf`` and asserts the
real behaviour end-to-end, so a drift between the committed
``fixtures/example_docling_real.json`` and what Docling actually emits is caught.

Gating (all must hold, else the whole module is skipped)
--------------------------------------------------------
* ``RUN_DOCLING_TESTS=1`` in the environment — an explicit opt-in so the slow
  (model-downloading, ~30-90 s) conversion never runs in the default lane; absent
  in CI. Mirrors ``test_acceptance_llm.py``'s ``RUN_LLM_TESTS`` opt-in.
* the ``docling`` package importable — via :func:`pytest.importorskip`, exactly
  as ``test_ide_browser.py`` gates on ``playwright``.
* ``example.pdf`` present at the repo root — skipped otherwise.

Run locally with::

    RUN_DOCLING_TESTS=1 .venv/bin/python -m pytest -q tests/test_acceptance_e2e_live.py

Because the Docling formula model is not perfectly deterministic, the assertions
are deliberately *presence/contains* rather than brittle exact counts wherever
the model could vary the symbol vocabulary. The structural invariants the issue
fixes (section titles, defined names, no page-footer block, ZERO citations) ARE
asserted exactly.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import pytest

# --- module-level gating ---------------------------------------------------

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DOCLING_TESTS") != "1",
    reason="Live Docling tests are opt-in: set RUN_DOCLING_TESTS=1 to run them.",
)

# Skip cleanly if the heavy optional dependency is not installed.
pytest.importorskip("docling", reason="docling not installed")

from math_ide.ingest.docling_runner import run_docling  # noqa: E402
from math_ide.ontology import MockResolver  # noqa: E402
from math_ide.ontology.occurrences import iter_blocks  # noqa: E402
from math_ide.pipeline import ingest_structure, run_full  # noqa: E402
from math_ide.renderer.navigation import definition_target  # noqa: E402
from math_ide.renderer.render import render_document  # noqa: E402
from math_ide.schema import (  # noqa: E402
    Definition,
    Formula,
    MathDocument,
    Section,
)

EXAMPLE_PDF = Path(__file__).resolve().parents[1] / "example.pdf"

# Skip if the source PDF is absent (it lives at the repo root).
if not EXAMPLE_PDF.is_file():
    pytest.skip(
        f"example.pdf not found at {EXAMPLE_PDF}", allow_module_level=True
    )


# ---------------------------------------------------------------------------
# One live conversion, shared across the module's assertions
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_resolved() -> MathDocument:
    """Convert ``example.pdf`` live (formula enrichment on), ingest, resolve.

    Module-scoped so the slow conversion runs exactly once. Goes through the same
    public path the CLI / IDE use: ``run_docling`` -> ``ingest_structure`` ->
    ``MockResolver`` (deterministic, offline resolution)."""
    docling = run_docling(str(EXAMPLE_PDF), formula=True)
    doc = ingest_structure(docling)
    run_full(doc, resolver=MockResolver(), wait=True)
    return doc


# ---------------------------------------------------------------------------
# Lookups over the live document
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


def _block_text(b) -> str:
    return (
        getattr(b, "title", None)
        or getattr(b, "text", None)
        or getattr(b, "body", None)
        or ""
    )


# ===========================================================================
# Live structure — the two numbered sections + three definitions
# ===========================================================================


def test_live_top_level_sections_are_the_two_numbered_headers(
    live_resolved: MathDocument,
) -> None:
    """#24: the live conversion's only top-level Sections are the real numbered
    headers; the document title becomes metadata, not a Section peer."""
    top_sections = [b.title for b in live_resolved.blocks if isinstance(b, Section)]
    assert top_sections == [
        "1 Grundbegriffe der Mengenlehre",
        "2 Folgen und Grenzwerte",
    ]
    assert live_resolved.title == "Testskript: Einführung in die Analysis"


def test_live_defined_names_are_the_three_real_definitions(
    live_resolved: MathDocument,
) -> None:
    """#24: the live conversion defines exactly Menge / Injektivität (umlaut
    repaired) / Konvergenz."""
    definitions = [
        b.defined_name
        for b in iter_blocks(live_resolved.blocks)
        if isinstance(b, Definition)
    ]
    assert definitions == ["Menge", "Injektivität", "Konvergenz"]


def test_live_page_footer_is_not_a_block(live_resolved: MathDocument) -> None:
    """#24: the page-footer page number ``"1"`` (furniture) is dropped — it
    never becomes a content block."""
    assert all(_block_text(b) != "1" for b in iter_blocks(live_resolved.blocks))


# ===========================================================================
# Live occurrences — defined names, formula symbols, ZERO citations
# ===========================================================================


def test_live_has_zero_citation_occurrences(live_resolved: MathDocument) -> None:
    """#24 CITATION DIVERGENCE: ``example.pdf`` has no numbered cross-reference,
    so the live pipeline emits ZERO citation occurrences (the synthetic
    fixture's "Nach Definition 1.1 …" citation is idealized input)."""
    assert [o for o in live_resolved.occurrences if o.kind == "citation"] == []


def test_live_occurrence_kinds_present(live_resolved: MathDocument) -> None:
    """#24: three defined names, formula symbols and inline-prose symbols are all
    present; no citation. Counts are presence-based (the formula model can vary
    its exact symbol vocabulary across runs)."""
    counts = Counter(o.kind for o in live_resolved.occurrences)
    assert counts["defined_name"] == 3
    assert counts["formula_symbol"] > 0
    assert counts["inline_symbol"] > 0
    assert counts["citation"] == 0


# ===========================================================================
# Live navigation — real tokens resolve to the real definition blocks
# ===========================================================================


def test_live_convergence_symbols_navigate_to_konvergenz(
    live_resolved: MathDocument,
) -> None:
    """#24: real convergence tokens (\\epsilon / N / L) link to the Konvergenz
    block after MockResolver. Asserted by *presence* of at least one such symbol
    that navigates, so a small model variance does not fail the run."""
    doc = live_resolved
    konv_block = _def_block(doc, "Konvergenz")

    linked = [
        o
        for token in (r"\epsilon", "N", "L")
        for o in _symbol_occs(doc, token)
        if definition_target(doc, o) == konv_block
    ]
    assert linked, "expected convergence symbols to navigate to Konvergenz"


def test_live_injectivity_symbols_navigate_to_injektivitaet(
    live_resolved: MathDocument,
) -> None:
    """#24: the injectivity formula carries the spaced subscript ``x _ { 1 }``
    (not unicode ``x₁``), and f / X navigate to the Injektivität block."""
    doc = live_resolved
    inj_block = _def_block(doc, "Injektivität")

    inj_formula = next(
        b
        for b in iter_blocks(doc.blocks)
        if isinstance(b, Formula) and "forall x" in b.canonical_content
    )
    assert "x _ { 1 }" in inj_formula.canonical_content  # spaced, not x₁

    linked = [
        o
        for token in ("f", "X")
        for o in _symbol_occs(doc, token)
        if definition_target(doc, o) == inj_block
    ]
    assert linked, "expected injectivity symbols to navigate to Injektivität"


def test_live_renders_a_ready_page(live_resolved: MathDocument) -> None:
    """#24: the live document renders a ready IDE page with the real heading."""
    html = render_document(live_resolved)
    assert 'data-ingestion-state="ready"' in html
    assert '<h2 class="section-title">1 Grundbegriffe der Mengenlehre</h2>' in html
    assert "math-ide-data" in html
