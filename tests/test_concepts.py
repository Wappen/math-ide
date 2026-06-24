"""Tests for concept seeding + structural relations (issue #8)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from math_ide.ingest import build_math_document
from math_ide.ontology import seed_ontology
from math_ide.ontology.concepts import (
    _sibling_relations,
    seed_concepts_and_relations,
    stub_key,
)
from math_ide.ontology.occurrences import extract_occurrences, iter_blocks
from math_ide.schema import (
    Concept,
    Formula,
    MathDocument,
)

FIXTURE = Path(__file__).parent / "fixtures" / "example_docling.json"


@pytest.fixture()
def doc() -> MathDocument:
    docling = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return seed_ontology(build_math_document(docling))


def _concept(doc: MathDocument, concept_id: str) -> Concept:
    return next(c for c in doc.concepts if c.id == concept_id)


# ---------------------------------------------------------------------------
# Formal-block concepts
# ---------------------------------------------------------------------------


def test_concept_per_definition_with_formal_meaning(doc: MathDocument) -> None:
    """Acceptance: ontology has concepts for all three definitions, each with a
    formal meaning lifted from the block body."""
    by_name = {c.name: c for c in doc.concepts if c.formal_meaning}
    assert set(by_name) == {"Menge", "Injektivitaet", "Konvergenz"}
    for name in ("Menge", "Injektivitaet", "Konvergenz"):
        c = by_name[name]
        assert c.formal_meaning  # non-empty
        assert c.resolution_status == "resolved"
        assert c.seeded_by_block_id is not None
        assert c.defining_occurrence_id is not None


def test_formal_concept_id_scheme(doc: MathDocument) -> None:
    """Formal concept ids are mint_id(document_id, "concept", defined_name)."""
    ids = {c.id for c in doc.concepts if c.formal_meaning}
    assert f"{doc.document_id}#concept/menge" in ids
    assert f"{doc.document_id}#concept/injektivitaet" in ids
    assert f"{doc.document_id}#concept/konvergenz" in ids


def test_defining_occurrence_is_the_defined_name_occurrence(doc: MathDocument) -> None:
    occ_by_id = {o.id: o for o in doc.occurrences}
    for c in doc.concepts:
        if not c.formal_meaning:
            continue
        occ = occ_by_id[c.defining_occurrence_id]
        assert occ.kind == "defined_name"
        assert occ.block_id == c.seeded_by_block_id
        assert occ.concept_id == c.id  # back-link set


def test_formal_meaning_matches_block_body(doc: MathDocument) -> None:
    block_by_id = {b.id: b for b in iter_blocks(doc.blocks)}
    for c in doc.concepts:
        if c.formal_meaning is None:
            continue
        block = block_by_id[c.seeded_by_block_id]
        assert c.formal_meaning == block.body


# ---------------------------------------------------------------------------
# Stub symbol concepts
# ---------------------------------------------------------------------------


def test_stub_concept_per_distinct_symbol_token(doc: MathDocument) -> None:
    """One stub per distinct token; visually-colliding tokens stay distinct."""
    stubs = [c for c in doc.concepts if c.formal_meaning is None]
    names = sorted(c.name for c in stubs)
    # injectivity tokens + convergence tokens (note distinct X vs x₁ vs x₂; N vs n)
    assert names == sorted(["x₁", "x₂", "X", "f", "ε", "N", "ℝ", "n", "a_n", "L"])
    # ids are unique despite slug collisions
    assert len({c.id for c in stubs}) == len(stubs)
    for c in stubs:
        assert c.resolution_status == "pending"
        assert c.formal_meaning is None
        assert c.defining_occurrence_id is None


def test_stub_ids_collision_free() -> None:
    colliding = ["X", "x₁", "x₂", "ε", "ℝ", "N", "n"]
    keys = {stub_key(t) for t in colliding}
    assert len(keys) == len(colliding)


def test_formula_symbol_occurrences_link_to_their_stub(doc: MathDocument) -> None:
    """Every formula_symbol occurrence resolves to the stub for its token."""
    formulas = {b.id: b for b in iter_blocks(doc.blocks) if isinstance(b, Formula)}
    stub_by_id = {c.id: c for c in doc.concepts if c.formal_meaning is None}
    for occ in doc.occurrences:
        if occ.kind != "formula_symbol":
            continue
        assert occ.concept_id in stub_by_id
        token = formulas[occ.block_id].canonical_content[occ.span[0] : occ.span[1]]
        assert stub_by_id[occ.concept_id].name == token


def test_counts_formal_vs_stub(doc: MathDocument) -> None:
    formal = [c for c in doc.concepts if c.formal_meaning]
    stub = [c for c in doc.concepts if c.formal_meaning is None]
    assert len(formal) == 3
    assert len(stub) == 10


# ---------------------------------------------------------------------------
# Citation occurrence -> seeded concept
# ---------------------------------------------------------------------------


def test_citation_occurrence_links_to_seeded_concept(doc: MathDocument) -> None:
    """Acceptance: citation occurrences link to the cited block's concept."""
    cite = next(o for o in doc.occurrences if o.kind == "citation")
    menge = _concept(doc, f"{doc.document_id}#concept/menge")
    assert cite.concept_id == menge.id


# ---------------------------------------------------------------------------
# Structural relations
# ---------------------------------------------------------------------------


def test_seeded_by_relations_point_concept_to_block(doc: MathDocument) -> None:
    seeded = [r for r in doc.relations if r.kind == "seeded_by"]
    assert len(seeded) == 3
    block_ids = {b.id for b in iter_blocks(doc.blocks)}
    for r in seeded:
        assert r.origin == "structural"
        assert r.target_is_block is True
        assert r.target_concept_id in block_ids  # target is a block id
        # source is the concept seeded by that block
        c = _concept(doc, r.source_concept_id)
        assert c.seeded_by_block_id == r.target_concept_id


def test_co_occurring_edges_for_injectivity_and_convergence(doc: MathDocument) -> None:
    """Acceptance: f/X co-occur (injectivity); ε/L co-occur (convergence)."""
    co = {
        (r.source_concept_id, r.target_concept_id)
        for r in doc.relations
        if r.kind == "co_occurring"
    }
    id_by_name = {c.name: c.id for c in doc.concepts if c.formal_meaning is None}
    f, X = id_by_name["f"], id_by_name["X"]
    eps, L = id_by_name["ε"], id_by_name["L"]
    assert (f, X) in co and (X, f) in co  # symmetric
    assert (eps, L) in co and (L, eps) in co
    # cross-formula tokens never co-occur
    assert (f, eps) not in co


def test_co_occurring_origin_is_structural(doc: MathDocument) -> None:
    for r in doc.relations:
        assert r.origin == "structural"  # no LLM at this stage
        assert r.kind in {"seeded_by", "sibling", "co_occurring"}


def test_relations_deduped(doc: MathDocument) -> None:
    keys = [
        (r.source_concept_id, r.target_concept_id, r.kind) for r in doc.relations
    ]
    assert len(keys) == len(set(keys))


def test_sibling_relations_among_concepts_of_same_block() -> None:
    """sibling edges connect concepts that share a seeded_by_block_id."""
    concepts = [
        Concept(id="d1#concept/a", name="a", seeded_by_block_id="d1#block/x"),
        Concept(id="d1#concept/b", name="b", seeded_by_block_id="d1#block/x"),
        Concept(id="d1#concept/c", name="c", seeded_by_block_id="d1#block/y"),
    ]
    rels = _sibling_relations(concepts, set())
    pairs = {(r.source_concept_id, r.target_concept_id) for r in rels}
    assert ("d1#concept/a", "d1#concept/b") in pairs
    assert ("d1#concept/b", "d1#concept/a") in pairs
    # c is in a different block -> no sibling edge to it
    assert all("d1#concept/c" not in p for p in pairs)
    for r in rels:
        assert r.kind == "sibling"
        assert r.origin == "structural"


def test_relation_counts_by_kind(doc: MathDocument) -> None:
    counts = Counter(r.kind for r in doc.relations)
    assert counts["seeded_by"] == 3
    # injectivity: 4 distinct concepts -> 4*3 = 12 directed edges
    # convergence: 6 distinct concepts -> 6*5 = 30 directed edges
    assert counts["co_occurring"] == 42
    assert counts.get("sibling", 0) == 0  # each block seeds exactly one concept


# ---------------------------------------------------------------------------
# Stage completion + ordering contract
# ---------------------------------------------------------------------------


def test_seeding_sets_structure_ready(doc: MathDocument) -> None:
    assert doc.ingestion_state == "structure_ready"


def test_seed_requires_occurrences_first() -> None:
    """seed_concepts_and_relations consumes occurrences produced by #7."""
    docling = json.loads(FIXTURE.read_text(encoding="utf-8"))
    md = build_math_document(docling)
    extract_occurrences(md)
    seed_concepts_and_relations(md)
    assert any(c.formal_meaning for c in md.concepts)
    assert any(r.kind == "co_occurring" for r in md.relations)


def test_round_trip_after_seeding(doc: MathDocument) -> None:
    restored = MathDocument.model_validate_json(doc.model_dump_json())
    assert restored == doc
