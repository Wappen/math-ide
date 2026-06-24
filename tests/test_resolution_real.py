r"""Meaning-resolution acceptance against the *real* Docling export (issue #21).

The synthetic fixture (``example_docling.json``) carries the ASCII/unicode
spellings the :class:`~math_ide.ontology.MockResolver` table was authored against
(``Injektivitaet`` / ``ε`` / ``a_n``), so it cannot catch the regression #21
fixes: on the *real* Docling export the same symbols arrive spelled differently
and the offline mock used to no-op on every one of them. Specifically the live
export (after the #18 umlaut repair and the #20 symbol-index fix) produces:

* the umlaut-repaired definition name ``Injektivität`` (not ``Injektivitaet``);
* the convergence error bound as the LaTeX control word ``\epsilon`` (not ``ε``);
* *spaced* LaTeX subscripts ``a _ { n }`` / ``x _ { 1 }`` (not ``a_n`` / ``x_1``);
* a distinct set token ``\mathbb { N }`` alongside the bare threshold ``N``.

These assertions exercise the real code path through the public
``ingest_structure`` -> ``MockResolver().resolve`` -> ``definition_target`` API,
proving the normalisation-aware resolver links the real tokens.

Deliberately left PENDING (no link), and asserted as such below:

* ``\mathbb { N }`` — the convergence SET token. #20 gives it a concept distinct
  from the index threshold ``N``; the mock links the threshold but not the set,
  so they are *not* conflated (per #21's scope, the ℕ/N split itself is #20).
* ``n`` — the convergence bound index (the running summation/quantifier variable),
  not an object any definition introduces.
* ``x _ { 1 }`` / ``x _ { 2 }`` — the injectivity formula's bound domain elements.
  Re-pointing them at ``Injektivität`` would collapse every injectivity symbol
  onto one concept and erase the per-stub co_occurring structure, so the mock
  leaves them pending; finer-grained coreference is a live-LLM job.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from math_ide.ontology import MockResolver
from math_ide.ontology.occurrences import iter_blocks
from math_ide.pipeline import ingest_structure
from math_ide.renderer.navigation import definition_target
from math_ide.schema import Formula, MathDocument

REAL_FIXTURE = Path(__file__).parent / "fixtures" / "example_docling_real.json"


@pytest.fixture()
def real_resolved() -> MathDocument:
    """The real Docling export, ingested and resolved by the offline mock."""
    docling = json.loads(REAL_FIXTURE.read_text(encoding="utf-8"))
    doc = ingest_structure(docling)
    return MockResolver().resolve(doc)


# ---------------------------------------------------------------------------
# Small lookups over the real document
# ---------------------------------------------------------------------------


def _definition_block(doc: MathDocument, defined_name: str) -> str:
    for block in iter_blocks(doc.blocks):
        if getattr(block, "defined_name", None) == defined_name:
            return block.id
    raise AssertionError(f"no definition block named {defined_name!r}")


def _occ_token(doc: MathDocument, occ) -> str:
    formula = next(
        b
        for b in iter_blocks(doc.blocks)
        if isinstance(b, Formula) and b.id == occ.block_id
    )
    return formula.canonical_content[occ.span[0] : occ.span[1]]


def _symbol_occs(doc: MathDocument, token: str) -> list:
    """Every formula-symbol occurrence whose *exact* surface token is ``token``."""
    return [
        o
        for o in doc.occurrences
        if o.kind == "formula_symbol"
        and o.span is not None
        and _occ_token(doc, o) == token
    ]


def _concept(doc: MathDocument, name: str):
    return next(c for c in doc.concepts if c.name == name)


# ---------------------------------------------------------------------------
# The real fixture really does carry the divergent spellings (#18/#20)
# ---------------------------------------------------------------------------


def test_real_fixture_uses_divergent_spellings(real_resolved: MathDocument) -> None:
    """Guard the corpus shape these assertions depend on: the real export uses
    the LaTeX ``\\epsilon``, the spaced subscript ``a _ { n }``, the umlaut name
    ``Injektivität`` and a distinct ``\\mathbb { N }`` set token."""
    names = {c.name for c in real_resolved.concepts}
    assert "Injektivität" in names  # #18 umlaut repair, not "Injektivitaet"
    assert r"\epsilon" in names  # LaTeX control word, not "ε"
    assert "a _ { n }" in names  # spaced subscript, not "a_n"
    assert r"\mathbb { N }" in names  # #20: set token distinct from threshold N
    assert "N" in names  # the bare index threshold


# ---------------------------------------------------------------------------
# Acceptance: convergence symbols link to the Konvergenz definition
# ---------------------------------------------------------------------------


def test_real_epsilon_resolves_to_konvergenz(real_resolved: MathDocument) -> None:
    """Both ``\\epsilon`` occurrences link to the Konvergenz block and the
    ``\\epsilon`` concept is resolved (#21 acceptance bullet 1)."""
    doc = real_resolved
    konv_block = _definition_block(doc, "Konvergenz")

    eps_occs = _symbol_occs(doc, r"\epsilon")
    assert len(eps_occs) == 2, "the convergence formula has two \\epsilon symbols"
    for occ in eps_occs:
        assert definition_target(doc, occ) == konv_block

    eps_concept = _concept(doc, r"\epsilon")
    assert eps_concept.resolution_status == "resolved"


def test_real_convergence_symbols_resolve_to_konvergenz(
    real_resolved: MathDocument,
) -> None:
    """``a _ { n }``, ``L`` and the index threshold ``N`` link to Konvergenz."""
    doc = real_resolved
    konv_block = _definition_block(doc, "Konvergenz")

    for token in ("a _ { n }", "L", "N"):
        occs = _symbol_occs(doc, token)
        assert occs, f"the convergence formula has a {token!r} symbol"
        for occ in occs:
            assert definition_target(doc, occ) == konv_block, token


# ---------------------------------------------------------------------------
# Acceptance: injectivity f / X link to the (umlaut) Injektivität definition
# ---------------------------------------------------------------------------


def test_real_injectivity_symbols_resolve_to_injektivitaet(
    real_resolved: MathDocument,
) -> None:
    """The injectivity ``f`` and ``X`` occurrences link to the umlaut-named
    ``Injektivität`` definition (#21 acceptance bullet 2)."""
    doc = real_resolved
    inj_block = _definition_block(doc, "Injektivität")

    for token in ("f", "X"):
        occs = _symbol_occs(doc, token)
        assert occs, f"the injectivity formula has a {token!r} symbol"
        for occ in occs:
            assert definition_target(doc, occ) == inj_block, token


# ---------------------------------------------------------------------------
# The deliberately-pending symbols: set ℕ, bound index n, bound vars x_1/x_2
# ---------------------------------------------------------------------------


def test_real_set_token_not_conflated_with_threshold(
    real_resolved: MathDocument,
) -> None:
    """The SET ``\\mathbb { N }`` stays pending — it is NOT dragged onto
    Konvergenz with the bare threshold ``N`` (the ℕ/N split is #20)."""
    doc = real_resolved
    set_occs = _symbol_occs(doc, r"\mathbb { N }")
    assert set_occs, "the convergence formula has a \\mathbb { N } set token"
    for occ in set_occs:
        assert definition_target(doc, occ) is None
    assert _concept(doc, r"\mathbb { N }").resolution_status == "pending"


def test_real_bound_variables_left_pending(real_resolved: MathDocument) -> None:
    """Bound variables the mock deliberately does not corefer stay pending: the
    convergence index ``n`` and the injectivity domain elements ``x _ { 1 }`` /
    ``x _ { 2 }`` (a live LLM does this finer-grained coreference)."""
    doc = real_resolved
    for token in ("n", "x _ { 1 }", "x _ { 2 }"):
        occs = _symbol_occs(doc, token)
        assert occs, f"the formula has a {token!r} symbol"
        for occ in occs:
            assert definition_target(doc, occ) is None, token


# ---------------------------------------------------------------------------
# formal_meaning stays authoritative on the real fixture too
# ---------------------------------------------------------------------------


def test_real_formal_meaning_unchanged(real_resolved: MathDocument) -> None:
    """Resolution never invents or rewrites a formal meaning on the real export."""
    doc = real_resolved
    for concept in doc.concepts:
        if concept.formal_meaning is not None:
            assert concept.inferred_meaning is None
    assert doc.ingestion_state == "ready"
