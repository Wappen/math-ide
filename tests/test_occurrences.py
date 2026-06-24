"""Tests for occurrence extraction + dual bboxes (issue #7)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from math_ide.ingest import build_math_document
from math_ide.ontology.occurrences import (
    CITATION_RE,
    extract_occurrences,
    iter_blocks,
    reconstruct_label,
)
from math_ide.schema import (
    BBox,
    Definition,
    Formula,
    FormalBlock,
    MathDocument,
    Occurrence,
    Paragraph,
    SymbolSpan,
)

FIXTURE = Path(__file__).parent / "fixtures" / "example_docling.json"


@pytest.fixture()
def doc() -> MathDocument:
    docling = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return extract_occurrences(build_math_document(docling))


def _by_kind(doc: MathDocument, kind: str) -> list[Occurrence]:
    return [o for o in doc.occurrences if o.kind == kind]


# ---------------------------------------------------------------------------
# Defined-name occurrences
# ---------------------------------------------------------------------------


def test_defined_name_occurrences_for_each_definition(doc: MathDocument) -> None:
    """Menge, Injektivitaet, Konvergenz each get one defined_name occurrence."""
    defined = _by_kind(doc, "defined_name")
    # map block_id -> defined_name via the tree
    name_by_block = {
        b.id: b.defined_name
        for b in iter_blocks(doc.blocks)
        if isinstance(b, FormalBlock) and b.defined_name
    }
    names = {name_by_block[o.block_id] for o in defined}
    assert names == {"Menge", "Injektivitaet", "Konvergenz"}
    assert len(defined) == 3


def test_defined_name_span_locates_the_name(doc: MathDocument) -> None:
    """span indexes the defined name inside the block's reconstructed label."""
    block_by_id = {b.id: b for b in iter_blocks(doc.blocks)}
    for occ in _by_kind(doc, "defined_name"):
        block = block_by_id[occ.block_id]
        label = reconstruct_label(block)
        s, e = occ.span
        assert label[s:e] == block.defined_name


def test_defined_name_has_source_bbox_and_no_render_bbox(doc: MathDocument) -> None:
    for occ in _by_kind(doc, "defined_name"):
        assert occ.source_bbox is not None
        assert occ.render_bbox is None


# ---------------------------------------------------------------------------
# Formula-symbol occurrences
# ---------------------------------------------------------------------------


def test_formula_symbol_occurrences_cover_acceptance_tokens(doc: MathDocument) -> None:
    """Injectivity contributes f/x_1/x_2/X; convergence ε/a_n/L/N."""
    formulas = {b.id: b for b in iter_blocks(doc.blocks) if isinstance(b, Formula)}
    tokens: set[str] = set()
    for occ in _by_kind(doc, "formula_symbol"):
        formula = formulas[occ.block_id]
        s, e = occ.span
        tokens.add(formula.canonical_content[s:e])
    # injectivity (unicode subscripts) + convergence symbols
    assert {"f", "x₁", "x₂", "X"} <= tokens
    assert {"ε", "a_n", "L", "N"} <= tokens


def test_formula_symbol_occurrence_per_symbol_index_entry(doc: MathDocument) -> None:
    formula_symbol = _by_kind(doc, "formula_symbol")
    n_index = sum(
        len(b.symbol_index)
        for b in iter_blocks(doc.blocks)
        if isinstance(b, Formula)
    )
    assert len(formula_symbol) == n_index
    assert n_index > 0


def test_formula_symbol_bboxes_nonnull_render_null(doc: MathDocument) -> None:
    """Acceptance: source_bbox set, render_bbox null until layout (#11)."""
    formula_symbol = _by_kind(doc, "formula_symbol")
    assert formula_symbol  # not empty
    for occ in formula_symbol:
        assert occ.source_bbox is not None
        assert occ.render_bbox is None


def test_formula_symbol_subdivided_bbox_inside_formula_bbox(doc: MathDocument) -> None:
    """A symbol's source bbox is a horizontal slice of its formula's bbox."""
    formulas = {b.id: b for b in iter_blocks(doc.blocks) if isinstance(b, Formula)}
    for occ in _by_kind(doc, "formula_symbol"):
        fb = formulas[occ.block_id].source_bbox
        sb = occ.source_bbox
        assert fb is not None and sb is not None
        assert fb.l <= sb.l <= sb.r <= fb.r
        assert sb.t == fb.t and sb.b == fb.b
        assert sb.page_no == fb.page_no


# ---------------------------------------------------------------------------
# Citation occurrences
# ---------------------------------------------------------------------------


def test_citation_links_definition_1_1_to_menge_block(doc: MathDocument) -> None:
    """Acceptance: "Definition 1.1" in the prose resolves to the Menge block."""
    menge_block = next(
        b.id
        for b in iter_blocks(doc.blocks)
        if isinstance(b, Definition) and b.defined_name == "Menge"
    )
    citations = _by_kind(doc, "citation")
    assert len(citations) == 1
    cite = citations[0]
    assert cite.target_block_id == menge_block
    # span locates the exact surface text in the host paragraph
    para = next(
        b for b in iter_blocks(doc.blocks) if b.id == cite.block_id
    )
    assert isinstance(para, Paragraph)
    s, e = cite.span
    assert para.text[s:e] == "Definition 1.1"
    assert cite.source_bbox is not None
    assert cite.render_bbox is None


def test_citation_regex_matches_keyword_plus_number() -> None:
    matches = [
        (m.group("keyword"), m.group("number"))
        for m in CITATION_RE.finditer(
            "siehe Satz 2.3 sowie Definition 1.1 und Lemma 4"
        )
    ]
    assert matches == [("Satz", "2.3"), ("Definition", "1.1"), ("Lemma", "4")]


def test_citation_regex_ignores_bare_keyword() -> None:
    """A keyword without a number is not a resolvable citation."""
    assert CITATION_RE.search("Diese Definition ist wichtig") is None


def test_citation_in_formal_block_body_resolves() -> None:
    """Citations inside a formal block's body/preamble are also detected."""
    doc = MathDocument(document_id="d1")
    target = Definition(
        id="d1#block/def-target",
        number="3.4",
        defined_name="Ziel",
        body="Trivial.",
    )
    citing = Definition(
        id="d1#block/def-citing",
        number="3.5",
        defined_name="Quelle",
        body="Folgt direkt aus Definition 3.4 wie oben.",
        source_bbox=BBox(l=0.0, t=10.0, r=100.0, b=0.0, page_no=1),
    )
    doc.blocks.extend([target, citing])
    extract_occurrences(doc)
    cites = [o for o in doc.occurrences if o.kind == "citation"]
    assert len(cites) == 1
    assert cites[0].block_id == citing.id
    assert cites[0].target_block_id == target.id


def test_occurrence_counts_by_kind(doc: MathDocument) -> None:
    counts = Counter(o.kind for o in doc.occurrences)
    assert counts["defined_name"] == 3
    assert counts["citation"] == 1
    assert counts["formula_symbol"] == 17  # 9 (injectivity) + 8 (convergence)
    # inline_symbol (#23): Def 1.2 body "f: X -> Y" -> f, X, Y; Def 2.1 body
    # "Folge a_n ... Grenzwert L" -> a_n, L.
    assert counts["inline_symbol"] == 5


def test_occurrence_ids_are_document_namespaced(doc: MathDocument) -> None:
    for occ in doc.occurrences:
        assert occ.id.startswith(f"{doc.document_id}#occ/")


def test_formula_symbol_subdivides_distinct_offsets() -> None:
    """Two symbols at different spans get different (non-degenerate) bboxes."""
    doc = MathDocument(document_id="d1")
    formula = Formula(
        id="d1#block/f",
        orig_fallback="a + b",
        source_bbox=BBox(l=0.0, t=10.0, r=100.0, b=0.0, page_no=1),
        symbol_index=[
            SymbolSpan(token="a", start=0, end=1, kind="variable"),
            SymbolSpan(token="b", start=4, end=5, kind="variable"),
        ],
    )
    doc.blocks.append(formula)
    extract_occurrences(doc)
    a, b = [o for o in doc.occurrences if o.kind == "formula_symbol"]
    assert a.source_bbox.l < b.source_bbox.l
