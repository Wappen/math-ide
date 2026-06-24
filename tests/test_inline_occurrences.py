"""Tests for inline-math occurrences in prose (issue #23, Phase 1).

The bulk of a real document's notation lives *inline in prose* (``f : X → Y``,
``L ∈ R``, ``lim n →∞ a n = L``, ``als R``), not in formula nodes. Before #23
that prose was dead text. The inline scanner now surfaces standalone identifiers
and named sets from ``Paragraph.text`` and ``FormalBlock.body``/``preamble`` as
``inline_symbol`` occurrences, links them to the same concept as the matching
formula symbol, and makes them clickable in the renderer.

These tests assert that behaviour against the committed real Docling fixture
``tests/fixtures/example_docling_real.json`` (which, unlike the synthetic one,
carries the real inline notation), plus a focused unit test proving German prose
words never mint spurious single-letter occurrences.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from math_ide.ingest import build_math_document
from math_ide.ontology import MockResolver, seed_ontology
from math_ide.ontology.concepts import _inline_occurrence_token
from math_ide.ontology.occurrences import (
    extract_occurrences,
    iter_blocks,
    scan_inline_symbols,
)
from math_ide.renderer.navigation import definition_target
from math_ide.renderer.render import render_document
from math_ide.schema import Formula, MathDocument

REAL_FIXTURE = Path(__file__).parent / "fixtures" / "example_docling_real.json"


# --------------------------------------------------------------------------- #
# Fixtures over the real Docling output
# --------------------------------------------------------------------------- #


@pytest.fixture()
def real_doc() -> MathDocument:
    """Occurrences-only document from the real fixture (no concepts/resolver)."""
    raw = json.loads(REAL_FIXTURE.read_text(encoding="utf-8"))
    return extract_occurrences(build_math_document(raw))


@pytest.fixture()
def seeded_real_doc() -> MathDocument:
    """Structure-ready document (occurrences + concepts) from the real fixture."""
    raw = json.loads(REAL_FIXTURE.read_text(encoding="utf-8"))
    return seed_ontology(build_math_document(raw))


# --------------------------------------------------------------------------- #
# Lookup helpers
# --------------------------------------------------------------------------- #


def _block_by_id(doc: MathDocument, block_id: str):
    return next(b for b in iter_blocks(doc.blocks) if b.id == block_id)


def _inline_occs(doc: MathDocument):
    return [o for o in doc.occurrences if o.kind == "inline_symbol"]


def _inline_occs_with_token(doc: MathDocument, token: str):
    out = []
    for o in _inline_occs(doc):
        block = _block_by_id(doc, o.block_id)
        if _inline_occurrence_token(block, o) == token:
            out.append(o)
    return out


def _formula_symbol_occ(doc: MathDocument, formula: Formula, token: str):
    return next(
        o
        for o in doc.occurrences
        if o.kind == "formula_symbol"
        and o.block_id == formula.id
        and formula.canonical_content[o.span[0] : o.span[1]] == token
    )


def _block_id_for_name(doc: MathDocument, defined_name: str) -> str:
    return next(
        b.id
        for b in iter_blocks(doc.blocks)
        if getattr(b, "defined_name", None) == defined_name
    )


def _para_id_containing(doc: MathDocument, snippet: str) -> str:
    from math_ide.schema import Paragraph

    return next(
        b.id
        for b in iter_blocks(doc.blocks)
        if isinstance(b, Paragraph) and snippet in b.text
    )


# --------------------------------------------------------------------------- #
# Acceptance: inline occurrences are emitted from real prose
# --------------------------------------------------------------------------- #


def test_real_fixture_now_has_inline_occurrences(real_doc: MathDocument) -> None:
    """The 'by kind' summary is no longer only defined_name + formula_symbol."""
    counts = Counter(o.kind for o in real_doc.occurrences)
    # The real fixture used to mint only defined_name + formula_symbol (and 0
    # citation, 0 inline). Now inline prose notation contributes occurrences.
    assert counts["inline_symbol"] > 0
    assert counts["defined_name"] == 3
    assert counts["formula_symbol"] > 0


def test_inline_L_from_para13_gets_an_occurrence(real_doc: MathDocument) -> None:
    """node[13]-equivalent prose '... lim n →∞ a n = L .' surfaces an inline L."""
    para_id = _para_id_containing(real_doc, "lim n")
    l_occs = [
        o
        for o in _inline_occs(real_doc)
        if o.block_id == para_id
        and _inline_occurrence_token(_block_by_id(real_doc, o.block_id), o) == "L"
    ]
    assert l_occs, "expected an inline 'L' occurrence in the lim-prose paragraph"
    for occ in l_occs:
        assert occ.source_bbox is not None
        assert occ.render_bbox is None
        s, e = occ.span
        assert _block_by_id(real_doc, occ.block_id).text[s:e] == "L"


def test_inline_R_from_definition5_body_gets_an_occurrence(
    real_doc: MathDocument,
) -> None:
    """node[5]-equivalent body '... schreiben wir als R .' surfaces an inline R."""
    menge_id = _block_id_for_name(real_doc, "Menge")
    r_occs = [
        o
        for o in _inline_occs(real_doc)
        if o.block_id == menge_id
        and _inline_occurrence_token(_block_by_id(real_doc, o.block_id), o) == "R"
    ]
    assert r_occs, "expected an inline 'R' occurrence in the Menge body"
    for occ in r_occs:
        assert occ.source_bbox is not None
        s, e = occ.span
        assert _block_by_id(real_doc, occ.block_id).body[s:e] == "R"


# --------------------------------------------------------------------------- #
# Acceptance: inline occurrences share the matching formula symbol's concept
# --------------------------------------------------------------------------- #


def test_inline_L_shares_the_formula_L_concept(
    seeded_real_doc: MathDocument,
) -> None:
    """A prose L links to the SAME stub concept as the formula L (coreference)."""
    doc = seeded_real_doc
    conv = next(
        f
        for f in iter_blocks(doc.blocks)
        if isinstance(f, Formula) and "epsilon" in f.canonical_content
    )
    formula_L = _formula_symbol_occ(doc, conv, "L")
    inline_L = _inline_occs_with_token(doc, "L")
    assert inline_L
    assert all(o.concept_id == formula_L.concept_id for o in inline_L)


def test_inline_f_shares_the_formula_f_concept(
    seeded_real_doc: MathDocument,
) -> None:
    doc = seeded_real_doc
    inj = next(
        f
        for f in iter_blocks(doc.blocks)
        if isinstance(f, Formula) and "forall x" in f.canonical_content
    )
    formula_f = _formula_symbol_occ(doc, inj, "f")
    inline_f = _inline_occs_with_token(doc, "f")
    assert inline_f
    assert all(o.concept_id == formula_f.concept_id for o in inline_f)


def test_inline_L_resolves_to_konvergenz_block_after_mock(
    seeded_real_doc: MathDocument,
) -> None:
    """After MockResolver, the prose L's go-to-definition reaches Def 2.1."""
    doc = seeded_real_doc
    inline_L = _inline_occs_with_token(doc, "L")
    assert inline_L
    # Before resolution the shared stub is pending -> no target.
    assert all(definition_target(doc, o) is None for o in inline_L)

    MockResolver().resolve(doc)

    konv_block = _block_id_for_name(doc, "Konvergenz")
    assert all(definition_target(doc, o) == konv_block for o in inline_L)


def test_inline_f_resolves_to_injektivitaet_block_after_mock(
    seeded_real_doc: MathDocument,
) -> None:
    """After MockResolver, the prose f's go-to-definition reaches Def 1.2."""
    doc = seeded_real_doc
    inline_f = _inline_occs_with_token(doc, "f")
    assert inline_f

    MockResolver().resolve(doc)

    inj_block = _block_id_for_name(doc, "Injektivität")
    assert all(definition_target(doc, o) == inj_block for o in inline_f)


# --------------------------------------------------------------------------- #
# Acceptance: the renderer anchors inline notation as .occ hit targets
# --------------------------------------------------------------------------- #


def test_inline_symbols_render_as_occ_anchors(
    seeded_real_doc: MathDocument,
) -> None:
    """The prose L (para-13) and R (Def 1.1 body) become clickable .occ spans."""
    doc = seeded_real_doc
    MockResolver().resolve(doc)
    html = render_document(doc)
    # There is at least one inline_symbol anchor for each surfaced inline token.
    assert html.count('data-kind="inline_symbol"') == len(_inline_occs(doc))
    # The lim-prose L and the Menge-body R are both anchored.
    assert ">L</span>" in html
    assert ">R</span>" in html


# --------------------------------------------------------------------------- #
# Conservative matching: German prose words mint NO spurious occurrences
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "word",
    ["Eine", "in", "der", "Menge", "Abbildung", "konvergiert", "und", "ist"],
)
def test_german_word_yields_no_inline_symbols(word: str) -> None:
    """A bare German word must never produce a single-letter inline match."""
    assert scan_inline_symbols(word) == []


def test_german_sentence_yields_no_spurious_single_letters() -> None:
    """A full German clause with no standalone math letters matches nothing."""
    sentence = (
        "In der Mathematik nutzen wir Quantoren, um Aussagen präzise zu "
        "formulieren, während mindestens ein Element existiert."
    )
    assert scan_inline_symbols(sentence) == []


def test_standalone_letters_match_but_word_internal_letters_do_not() -> None:
    """A standalone f / X / R matches; the same letters inside words do not."""
    text = "Die Abbildung f bildet X auf R ab; Reelle Zahlen, formal."
    tokens = [tok for _s, _e, tok in scan_inline_symbols(text)]
    # Standalone identifiers / set are surfaced ...
    assert tokens == ["f", "X", "R"]
    # ... and none of the word-internal letters (the f in 'formal', the R in
    # 'Reelle', the X-less words) leaked in.
    assert tokens.count("f") == 1
    assert tokens.count("R") == 1


def test_tight_subscript_is_absorbed_but_spaced_words_are_not() -> None:
    """``a_n`` is one token; a letter followed by a word is never a subscript."""
    assert [t for _s, _e, t in scan_inline_symbols("Folge a_n konvergiert")] == [
        "a_n"
    ]
    # 'Y höchstens': Y is standalone, 'höchstens' must NOT be folded as a sub.
    assert [t for _s, _e, t in scan_inline_symbols("Zielbereichs Y höchstens")] == [
        "Y"
    ]
