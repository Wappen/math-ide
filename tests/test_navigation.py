"""Tests for precomputed IDE navigation (issues #12, #13).

Exercise :mod:`math_ide.renderer.navigation` against the *resolved* canonical
fixture: ingest -> seed_ontology -> MockResolver.resolve. All pure Python; no
browser involved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from math_ide.ingest import build_math_document
from math_ide.ontology import MockResolver, seed_ontology
from math_ide.renderer.navigation import (
    build_ide_payload,
    concept_card,
    definition_target,
)
from math_ide.schema import MathDocument

FIXTURE = Path(__file__).parent / "fixtures" / "example_docling.json"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def seeded_doc() -> MathDocument:
    """Structure-ready document (occurrences + concepts, no resolution)."""
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    doc = build_math_document(raw)
    seed_ontology(doc)
    return doc


@pytest.fixture()
def resolved_doc() -> MathDocument:
    """Fully resolved document (after MockResolver)."""
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    doc = build_math_document(raw)
    seed_ontology(doc)
    MockResolver().resolve(doc)
    return doc


# --------------------------------------------------------------------------- #
# Lookup helpers over the parallel indices
# --------------------------------------------------------------------------- #


def _occ(doc: MathDocument, *, kind: str, concept_name: str | None = None):
    """First occurrence of ``kind`` (optionally whose concept has a name)."""
    name_to_id = {c.name: c.id for c in doc.concepts}
    want = name_to_id.get(concept_name) if concept_name else None
    for occ in doc.occurrences:
        if occ.kind != kind:
            continue
        if want is not None and occ.concept_id != want:
            continue
        return occ
    raise AssertionError(f"no {kind} occurrence for concept {concept_name!r}")


def _concept_id(doc: MathDocument, name: str) -> str:
    for c in doc.concepts:
        if c.name == name:
            return c.id
    raise AssertionError(f"no concept named {name!r}")


def _block_id(doc: MathDocument, *, type_: str, defined_name: str) -> str:
    from math_ide.ontology.occurrences import iter_blocks

    for b in iter_blocks(doc.blocks):
        if b.type == type_ and getattr(b, "defined_name", None) == defined_name:
            return b.id
    raise AssertionError(f"no {type_} block named {defined_name!r}")


# --------------------------------------------------------------------------- #
# #12 — go to definition
# --------------------------------------------------------------------------- #


def test_citation_target_is_the_cited_menge_block(resolved_doc):
    """Left-click 'Definition 1.1' citation -> Menge definition block."""
    cite = _occ(resolved_doc, kind="citation")
    menge_block = _block_id(resolved_doc, type_="Definition", defined_name="Menge")
    assert definition_target(resolved_doc, cite) == menge_block
    # accept the id form too
    assert definition_target(resolved_doc, cite.id) == menge_block


def test_citation_target_works_before_resolution(seeded_doc):
    """Citations resolve deterministically at structure_ready, no LLM needed."""
    cite = _occ(seeded_doc, kind="citation")
    menge_block = _block_id(seeded_doc, type_="Definition", defined_name="Menge")
    assert definition_target(seeded_doc, cite) == menge_block


def test_defined_name_target_is_its_own_formal_block(resolved_doc):
    """The Konvergenz defined-name occurrence targets the Konvergenz block."""
    name_occ = _occ(resolved_doc, kind="defined_name", concept_name="Konvergenz")
    konv_block = _block_id(
        resolved_doc, type_="Definition", defined_name="Konvergenz"
    )
    assert definition_target(resolved_doc, name_occ) == konv_block


def test_epsilon_after_resolution_targets_konvergenz_block(resolved_doc):
    """After resolution, the convergence epsilon navigates to Definition 2.1."""
    konv_id = _concept_id(resolved_doc, "Konvergenz")
    konv_block = _block_id(
        resolved_doc, type_="Definition", defined_name="Konvergenz"
    )
    # every formula symbol re-pointed to Konvergenz must target its block
    eps = next(
        o
        for o in resolved_doc.occurrences
        if o.kind == "formula_symbol" and o.concept_id == konv_id
    )
    assert definition_target(resolved_doc, eps) == konv_block


def test_unresolved_symbol_has_no_target(resolved_doc):
    """A stub symbol with no formal block / defining occurrence yields None."""
    # Pick a formula symbol whose concept is still pending (e.g. ℝ, x1, x2, n).
    pending = next(
        o
        for o in resolved_doc.occurrences
        if o.kind == "formula_symbol"
        and o.concept_id is not None
        and _concept_status(resolved_doc, o.concept_id) == "pending"
    )
    assert definition_target(resolved_doc, pending) is None


def test_symbol_unresolved_before_resolution_has_no_target(seeded_doc):
    """Before resolution every formula symbol points at a stub -> None target."""
    sym = next(o for o in seeded_doc.occurrences if o.kind == "formula_symbol")
    assert definition_target(seeded_doc, sym) is None


def test_unknown_occurrence_id_is_none(resolved_doc):
    assert definition_target(resolved_doc, "does-not-exist") is None


def _concept_status(doc: MathDocument, concept_id: str) -> str:
    for c in doc.concepts:
        if c.id == concept_id:
            return c.resolution_status
    raise AssertionError(concept_id)


# --------------------------------------------------------------------------- #
# #12 — go to definition: isolated tier-3 / tier-4 minimal documents
#
# definition_target's priority is citation -> seeded_by_block -> defined_name
# occurrence's block -> defining_occurrence's block. These two tests construct
# the smallest MathDocuments in which exactly ONE of the lower tiers can win,
# so each branch is exercised in isolation (offline, no fixture).
# --------------------------------------------------------------------------- #


def _min_doc(*, blocks, occurrences, concepts):
    from math_ide.schema import (
        Concept,
        Definition,
        Formula,
        Occurrence,
    )

    return MathDocument(
        document_id="tiers",
        blocks=list(blocks),
        occurrences=list(occurrences),
        concepts=list(concepts),
    )


def test_definition_target_tier3_defined_name_block():
    """Tier 3 wins alone: concept has NO seeded_by_block but DOES have a
    defined_name occurrence -> that occurrence's block id."""
    from math_ide.schema import Concept, Definition, Formula, Occurrence

    label_block = Definition(id="tiers#block/def", number="1", defined_name="Foo")
    formula_block = Formula(
        id="tiers#block/f", latex="x", orig_fallback="x", enrichment_status="ready"
    )
    concept = Concept(
        id="tiers#concept/foo",
        name="Foo",
        seeded_by_block_id=None,  # tier 2 cannot fire
        defining_occurrence_id=None,  # tier 4 cannot fire
    )
    # The defined-name occurrence in the label block (tier 3's source).
    name_occ = Occurrence(
        id="tiers#occ/name",
        kind="defined_name",
        block_id=label_block.id,
        concept_id=concept.id,
    )
    # The occurrence we query: a symbol linked to the same concept.
    sym_occ = Occurrence(
        id="tiers#occ/sym",
        kind="formula_symbol",
        block_id=formula_block.id,
        concept_id=concept.id,
    )
    doc = _min_doc(
        blocks=[label_block, formula_block],
        occurrences=[name_occ, sym_occ],
        concepts=[concept],
    )
    # Tier 3: defined_name occurrence's block, NOT the symbol's own block.
    assert definition_target(doc, sym_occ) == label_block.id


def test_definition_target_tier4_defining_occurrence_block():
    """Tier 4 wins alone: concept has NO seeded_by_block and NO defined_name
    occurrence, only a defining_occurrence -> that occurrence's block id."""
    from math_ide.schema import Concept, Formula, Occurrence

    home_block = Formula(
        id="tiers#block/home", latex="x", orig_fallback="x", enrichment_status="ready"
    )
    query_block = Formula(
        id="tiers#block/q", latex="x", orig_fallback="x", enrichment_status="ready"
    )
    # The defining occurrence lives in home_block (tier 4's source).
    defining_occ = Occurrence(
        id="tiers#occ/defining",
        kind="formula_symbol",
        block_id=home_block.id,
        concept_id="tiers#concept/bar",
    )
    concept = Concept(
        id="tiers#concept/bar",
        name="Bar",
        seeded_by_block_id=None,  # tier 2 cannot fire
        defining_occurrence_id=defining_occ.id,  # tier 4's pointer
    )
    # The occurrence we query: a different symbol in a different block. There is
    # NO defined_name occurrence anywhere, so tier 3 cannot fire.
    query_occ = Occurrence(
        id="tiers#occ/q",
        kind="formula_symbol",
        block_id=query_block.id,
        concept_id=concept.id,
    )
    doc = _min_doc(
        blocks=[home_block, query_block],
        occurrences=[defining_occ, query_occ],
        concepts=[concept],
    )
    # Tier 4: the defining occurrence's block, NOT the query occurrence's block.
    assert definition_target(doc, query_occ) == home_block.id


# --------------------------------------------------------------------------- #
# #13 — concept card
# --------------------------------------------------------------------------- #


def test_konvergenz_card_has_formal_meaning_refs_and_both_neighbourhoods(
    resolved_doc,
):
    konv_id = _concept_id(resolved_doc, "Konvergenz")
    card = concept_card(resolved_doc, konv_id)

    assert card["id"] == konv_id
    assert card["name"] == "Konvergenz"
    assert card["resolution_status"] == "resolved"
    # Authoritative formal meaning is present and never None for Konvergenz.
    assert card["formal_meaning"]
    # Defining occurrence is the defined-name label.
    assert card["defining_occurrence"] is not None
    assert card["defining_occurrence"]["block_id"].endswith("konvergenz")
    # References = the convergence-formula symbols re-pointed at Konvergenz.
    assert len(card["references"]) >= 1
    assert all(r["occurrence_id"] for r in card["references"])
    # The defining occurrence is NOT listed among references.
    assert all(
        r["occurrence_id"] != card["defining_occurrence"]["id"]
        for r in card["references"]
    )
    # Neighbourhood has both structural (seeded_by block) and semantic edges.
    nb = card["neighbourhood"]
    assert nb["structural"], "expected structural neighbourhood (seeded_by)"
    assert nb["semantic"], "expected semantic neighbourhood (defines/uses)"
    # seeded_by structural edge points at a block, not a concept.
    seeded = [e for e in nb["structural"] if e["kind"] == "seeded_by"]
    assert seeded and seeded[0]["block_id"] is not None
    assert seeded[0]["concept_id"] is None
    # semantic edges name concepts and are tagged origin=semantic.
    assert all(e["origin"] == "semantic" for e in nb["semantic"])
    assert any(e["kind"] == "defines" for e in nb["semantic"])


def test_epsilon_card_has_inferred_meaning_and_semantic_uses(resolved_doc):
    eps_id = _concept_id(resolved_doc, "ε")
    card = concept_card(resolved_doc, eps_id)
    assert card["resolution_status"] == "resolved"
    # A stub symbol gets inferred meaning, never formal meaning.
    assert card["formal_meaning"] is None
    assert card["inferred_meaning"]
    # Structural co_occurring siblings + a semantic 'uses' -> Konvergenz.
    nb = card["neighbourhood"]
    assert any(e["kind"] == "co_occurring" for e in nb["structural"])
    assert any(e["kind"] == "uses" for e in nb["semantic"])


def test_pending_symbol_card_has_partial_structural_data(seeded_doc):
    """Right-click on an unresolved symbol shows status + structural edges."""
    # 'X' is a co-occurring symbol; before resolution it is a pending stub.
    x_id = _concept_id(seeded_doc, "X")
    card = concept_card(seeded_doc, x_id)
    assert card["resolution_status"] == "pending"
    assert card["formal_meaning"] is None
    assert card["inferred_meaning"] is None
    # Structural neighbourhood present even before the LLM stage.
    assert card["neighbourhood"]["structural"]
    # No semantic edges yet.
    assert card["neighbourhood"]["semantic"] == []


def test_concept_card_unknown_id_raises(resolved_doc):
    with pytest.raises(KeyError):
        concept_card(resolved_doc, "analysis-skript#concept/nope")


# --------------------------------------------------------------------------- #
# build_ide_payload shape
# --------------------------------------------------------------------------- #


def test_payload_shape_and_definition_targets(resolved_doc):
    payload = build_ide_payload(resolved_doc)

    assert payload["document_id"] == resolved_doc.document_id
    assert payload["ingestion_state"] == "ready"
    assert set(payload) == {
        "document_id",
        "ingestion_state",
        "occurrences",
        "concepts",
        "relations",
        "cards",
    }

    # Every occurrence is keyed by id and carries the navigation fields.
    assert len(payload["occurrences"]) == len(resolved_doc.occurrences)
    for occ in resolved_doc.occurrences:
        entry = payload["occurrences"][occ.id]
        assert set(entry) == {
            "block_id",
            "concept_id",
            "kind",
            "target_block_id",
            "definition_target",
            "render_bbox",
        }
        # definition_target matches the standalone function.
        assert entry["definition_target"] == definition_target(resolved_doc, occ)
        # render_bbox is a client-side post-layout slot; null in the payload.
        assert entry["render_bbox"] is None

    # Citation occurrence has a concrete definition target.
    cite = _occ(resolved_doc, kind="citation")
    assert payload["occurrences"][cite.id]["definition_target"] is not None

    # At least one occurrence is in the resolving (None target) state.
    assert any(
        e["definition_target"] is None for e in payload["occurrences"].values()
    )

    # Concepts keyed by id; cards present for every concept.
    assert set(payload["concepts"]) == {c.id for c in resolved_doc.concepts}
    assert set(payload["cards"]) == {c.id for c in resolved_doc.concepts}

    # Relations are a compact list with the expected keys.
    assert payload["relations"]
    sample = payload["relations"][0]
    assert set(sample) == {"source", "target", "kind", "origin", "target_is_block"}


def test_payload_is_json_serialisable(resolved_doc):
    payload = build_ide_payload(resolved_doc)
    # Round-trips through JSON without error and stays equal.
    assert json.loads(json.dumps(payload)) == payload


def test_payload_reflects_resolution_progress(seeded_doc):
    """The payload regenerates after resolution: more concrete targets appear."""
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    doc = build_math_document(raw)
    seed_ontology(doc)

    before = build_ide_payload(doc)
    before_targets = sum(
        1
        for e in before["occurrences"].values()
        if e["definition_target"] is not None
    )

    MockResolver().resolve(doc)
    after = build_ide_payload(doc)
    after_targets = sum(
        1
        for e in after["occurrences"].values()
        if e["definition_target"] is not None
    )

    # Resolution links symbols to formal concepts -> strictly more targets.
    assert after_targets > before_targets
    assert after["ingestion_state"] == "ready"
