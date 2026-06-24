r"""End-to-end acceptance tests for the full Math IDE loop (issue #15).

These tests exercise the *whole* offline loop — structure -> occurrences ->
resolution -> navigation -> concept card -> dual bboxes — through the **public**
pipeline / navigation API, against the canonical synthetic Docling-JSON fixture
(``tests/fixtures/example_docling.json``).

Why the synthetic fixture stands in for the example PDF
-------------------------------------------------------
Ingestion consumes a Docling-style ``export_to_dict()`` mapping (the heavy
``docling`` PDF->JSON model is isolated behind a lazy import and never runs in
tests). A hand-authored JSON dict therefore drives the *exact* code path a live
conversion would, with zero GPU/network dependency, and is deterministic — ideal
for CI acceptance. The browser-time half of the loop (render-bbox measurement,
click navigation) is covered by ``tests/test_ide_browser.py`` (gated on
Playwright); the live-LLM half by ``tests/test_acceptance_llm.py`` (gated on
``RUN_LLM_TESTS`` + ``ANTHROPIC_API_KEY``). See ``tests/README.md``.

Scenario -> issue-#15 acceptance-bullet map
-------------------------------------------
1. STRUCTURE       -> "three Definition blocks; Definition 1.2 has preamble"
2. OCCURRENCES     -> "defined names, formula symbols, at least one citation"
3. CITATIONS       -> "deterministic resolution without LLM"
4. RESOLUTION      -> "after LLM (mock), epsilon links to Konvergenz"
5. NAVIGATION      -> "left click citation -> Definition; left click symbol ->
                       definition after resolution"
6. CONCEPT CARD    -> "right click shows references + neighbourhood"
7. DUAL BBOXES     -> "source_bbox + render_bbox (render_bbox is layout-time)"
plus STAGED        -> "Mock LLM option for CI / usable at structure_ready"
and  FORMULA-UPGRADE (re-entrant enrichment without full re-ingest, #5/#14 hook).
"""

from __future__ import annotations

import json
from html import escape

import pytest

from math_ide.ontology import MockResolver
from math_ide.ontology.occurrences import iter_blocks
from math_ide.pipeline import (
    Pipeline,
    apply_formula_upgrade,
    ingest_structure,
    run_full,
)
from math_ide.renderer.navigation import (
    build_ide_payload,
    concept_card,
    definition_target,
)
from math_ide.renderer.render import render_document
from math_ide.schema import (
    Definition,
    Formula,
    FormalBlock,
    MathDocument,
    Paragraph,
    Section,
)

# A LaTeX upgrade for the convergence formula. Tokens deliberately overlap the
# originals (``a_n`` / ``N`` / ``L`` stay literal) so the FORMULA-UPGRADE test
# can prove a resolved stub survives the reflow.
CONVERGENCE_LATEX = (
    r"\forall \varepsilon > 0 \exists N \in R \forall m \geq N : |a_n - L| < \varepsilon"
)


# ---------------------------------------------------------------------------
# Tiny lookup helpers over the parallel indices (kept local to the test file)
# ---------------------------------------------------------------------------


def _formulas(doc: MathDocument) -> list[Formula]:
    return [b for b in iter_blocks(doc.blocks) if isinstance(b, Formula)]


def _convergence_formula(doc: MathDocument) -> Formula:
    return next(f for f in _formulas(doc) if "ε" in f.orig_fallback)


def _injectivity_formula(doc: MathDocument) -> Formula:
    return next(f for f in _formulas(doc) if "f(" in f.orig_fallback)


def _formula_tokens(formula: Formula) -> set[str]:
    """Distinct surface tokens in a formula's symbol index."""
    return {s.token for s in formula.symbol_index}


def _concept(doc: MathDocument, name: str):
    return next(c for c in doc.concepts if c.name == name)


def _concept_status(doc: MathDocument, concept_id: str) -> str:
    return next(c for c in doc.concepts if c.id == concept_id).resolution_status


def _block(doc: MathDocument, *, type_: str, defined_name: str) -> str:
    for b in iter_blocks(doc.blocks):
        if b.type == type_ and getattr(b, "defined_name", None) == defined_name:
            return b.id
    raise AssertionError(f"no {type_} block named {defined_name!r}")


def _occ_token(formula: Formula, occ) -> str:
    start, end = occ.span
    return formula.canonical_content[start:end]


def _symbol_occs(doc: MathDocument, formula: Formula, token: str) -> list:
    return [
        o
        for o in doc.occurrences
        if o.kind == "formula_symbol"
        and o.block_id == formula.id
        and o.span is not None
        and _occ_token(formula, o) == token
    ]


def _the_citation(doc: MathDocument):
    cites = [o for o in doc.occurrences if o.kind == "citation"]
    assert cites, "fixture has a 'Definition 1.1' citation"
    return cites[0]


# ===========================================================================
# Scenario 1 — STRUCTURE
# ===========================================================================


def test_structure_three_definitions_two_sections_and_a_paragraph(
    structure_ready_doc: MathDocument,
) -> None:
    """#15.1 STRUCTURE: exactly three Definition blocks (Menge, Injektivitaet,
    Konvergenz), two Sections, and the "Nach Definition 1.1" prose is a
    Paragraph (not a formal block)."""
    doc = structure_ready_doc

    definitions = [b for b in iter_blocks(doc.blocks) if isinstance(b, Definition)]
    assert [d.defined_name for d in definitions] == [
        "Menge",
        "Injektivitaet",
        "Konvergenz",
    ]
    # Each is genuinely a Definition (not a generic FormalBlock with a kind).
    assert all(type(d) is Definition for d in definitions)

    sections = [b for b in iter_blocks(doc.blocks) if isinstance(b, Section)]
    assert [s.title for s in sections] == [
        "1 Mengen und Abbildungen",
        "2 Folgen und Konvergenz",
    ]

    paragraphs = [b for b in iter_blocks(doc.blocks) if isinstance(b, Paragraph)]
    assert len(paragraphs) == 1
    nach = paragraphs[0]
    assert type(nach) is Paragraph  # NOT a formal block
    assert nach.text.startswith("Nach Definition 1.1")
    # The prose that precedes a definition must not have been swallowed into a
    # formal block: no FormalBlock body starts with the prose sentence.
    assert not any(
        isinstance(b, FormalBlock) and b.body.startswith("Nach Definition 1.1")
        for b in iter_blocks(doc.blocks)
    )


def test_structure_injektivitaet_has_preamble_and_separate_body(
    structure_ready_doc: MathDocument,
) -> None:
    """#15.1 STRUCTURE: Definition 1.2 (Injektivitaet) splits a single Docling
    node into a non-empty preamble + a separate body; the other two
    definitions carry no preamble."""
    doc = structure_ready_doc
    defs = {
        b.defined_name: b
        for b in iter_blocks(doc.blocks)
        if isinstance(b, Definition)
    }

    inj = defs["Injektivitaet"]
    assert inj.preamble, "Definition 1.2 must carry a preamble"
    assert inj.preamble.strip()  # non-empty
    assert inj.body, "Definition 1.2 must carry a body"
    # Preamble and body are distinct strings (the split actually happened).
    assert inj.preamble != inj.body
    assert inj.preamble not in inj.body
    # The leading prose lives in the preamble, the formal statement in the body.
    assert "wichtiges Konzept" in inj.preamble
    assert "Abbildung f" in inj.body

    # The clean definitions have no preamble.
    assert defs["Menge"].preamble is None
    assert defs["Konvergenz"].preamble is None
    assert defs["Menge"].number == "1.1"
    assert inj.number == "1.2"
    assert defs["Konvergenz"].number == "2.1"


# ===========================================================================
# Scenario 2 — OCCURRENCES
# ===========================================================================


def test_occurrences_defined_names_for_all_three_definitions(
    structure_ready_doc: MathDocument,
) -> None:
    """#15.2 OCCURRENCES: a defined-name occurrence exists for each definition."""
    doc = structure_ready_doc
    defined = [o for o in doc.occurrences if o.kind == "defined_name"]
    named_blocks = {o.block_id for o in defined}
    for name in ("Menge", "Injektivitaet", "Konvergenz"):
        block_id = _block(doc, type_="Definition", defined_name=name)
        assert block_id in named_blocks, f"missing defined_name occ for {name}"
    assert len(defined) == 3


def test_occurrences_formula_symbols_cover_expected_token_sets(
    structure_ready_doc: MathDocument,
) -> None:
    """#15.2 OCCURRENCES: formula-symbol occurrences cover {f, x_1, x_2, X} for
    injectivity and {epsilon, a_n, L, N} for convergence.

    (The fixture renders the subscripted x as the unicode ``x₁``/``x₂``; the
    distinct-token set is asserted as a superset of the required symbols.)"""
    doc = structure_ready_doc
    inj = _injectivity_formula(doc)
    conv = _convergence_formula(doc)

    # Every distinct token must have at least one formula_symbol occurrence.
    inj_occ_tokens = {
        _occ_token(inj, o)
        for o in doc.occurrences
        if o.kind == "formula_symbol" and o.block_id == inj.id
    }
    conv_occ_tokens = {
        _occ_token(conv, o)
        for o in doc.occurrences
        if o.kind == "formula_symbol" and o.block_id == conv.id
    }

    assert {"f", "x₁", "x₂", "X"} <= inj_occ_tokens
    assert {"ε", "a_n", "L", "N"} <= conv_occ_tokens
    # symbol_index and occurrences agree.
    assert inj_occ_tokens == _formula_tokens(inj)
    assert conv_occ_tokens == _formula_tokens(conv)


def test_occurrences_citation_definition_1_1_exists(
    structure_ready_doc: MathDocument,
) -> None:
    """#15.2 OCCURRENCES: the "Definition 1.1" citation occurrence exists."""
    doc = structure_ready_doc
    cite = _the_citation(doc)
    assert cite.kind == "citation"
    # It is anchored in the "Nach Definition 1.1" paragraph.
    host = next(b for b in iter_blocks(doc.blocks) if b.id == cite.block_id)
    assert isinstance(host, Paragraph)
    start, end = cite.span
    assert host.text[start:end] == "Definition 1.1"


# ===========================================================================
# Scenario 3 — CITATIONS (deterministic, pre-resolution)
# ===========================================================================


def test_citation_resolves_to_menge_block_at_structure_ready_without_resolver(
    structure_ready_doc: MathDocument,
) -> None:
    """#15.3 CITATIONS: the citation resolves deterministically (via
    definition_target) to the Menge block at structure_ready — no resolver
    has run."""
    doc = structure_ready_doc
    assert doc.ingestion_state == "structure_ready"
    # No LLM stage has touched anything: nothing semantic, all stubs pending.
    assert not any(r.origin == "semantic" for r in doc.relations)

    cite = _the_citation(doc)
    menge_block = _block(doc, type_="Definition", defined_name="Menge")
    assert cite.target_block_id == menge_block
    # definition_target follows the citation straight to the cited block.
    assert definition_target(doc, cite) == menge_block
    # And accepts the id form too.
    assert definition_target(doc, cite.id) == menge_block


# ===========================================================================
# Scenario 4 — RESOLUTION (after MockResolver via run_full)
# ===========================================================================


def test_resolution_links_epsilon_and_injectivity_symbols_and_preserves_formal(
    structure_ready_doc: MathDocument,
) -> None:
    """#15.4 RESOLUTION: after MockResolver (run_full wait=True): convergence
    epsilon -> Konvergenz; injectivity f/X consistent with Injektivitaet; all
    formal_meanings byte-identical to pre-resolution; semantic relations
    exist with origin == 'semantic'."""
    doc = structure_ready_doc

    # Snapshot every formal meaning BEFORE resolution.
    formal_before = {
        c.id: c.formal_meaning
        for c in doc.concepts
        if c.formal_meaning is not None
    }
    assert formal_before, "definitions must carry formal meaning"

    result = run_full(doc, resolver=MockResolver(), wait=True)
    assert result is doc
    assert doc.ingestion_state == "ready"

    konv = _concept(doc, "Konvergenz")
    inj_c = _concept(doc, "Injektivitaet")
    conv = _convergence_formula(doc)
    inj = _injectivity_formula(doc)

    # epsilon in the convergence formula now links to the Konvergenz concept.
    eps_occs = _symbol_occs(doc, conv, "ε")
    assert eps_occs
    assert all(o.concept_id == konv.id for o in eps_occs)

    # f / X are consistent with the Injektivitaet concept.
    f_occs = _symbol_occs(doc, inj, "f")
    x_occs = _symbol_occs(doc, inj, "X")
    assert f_occs and x_occs
    assert all(o.concept_id == inj_c.id for o in f_occs)
    assert all(o.concept_id == inj_c.id for o in x_occs)

    # formal_meanings are byte-identical to their pre-resolution values.
    formal_after = {
        c.id: c.formal_meaning
        for c in doc.concepts
        if c.id in formal_before
    }
    assert formal_after == formal_before

    # Semantic relations exist and are tagged origin == 'semantic'.
    semantic = [r for r in doc.relations if r.origin == "semantic"]
    assert semantic
    assert all(r.origin == "semantic" for r in semantic)
    # ... and they touch the Konvergenz concept (defines/uses).
    assert any(
        konv.id in (r.source_concept_id, r.target_concept_id) for r in semantic
    )


def test_resolution_flips_touched_concepts_to_resolved(
    resolved_doc: MathDocument,
) -> None:
    """#15.4 RESOLUTION: touched stub concepts flip pending -> resolved with an
    inferred meaning, never a formal meaning."""
    eps = _concept(resolved_doc, "ε")
    assert eps.resolution_status == "resolved"
    assert eps.inferred_meaning  # inferred, not formal
    assert eps.formal_meaning is None


# ===========================================================================
# Scenario 5 — NAVIGATION (go to definition)
# ===========================================================================


def test_navigation_left_click_citation_goes_to_menge(
    resolved_doc: MathDocument,
) -> None:
    """#15.5 NAVIGATION: left-click on the citation -> Menge Definition block."""
    cite = _the_citation(resolved_doc)
    menge_block = _block(resolved_doc, type_="Definition", defined_name="Menge")
    assert definition_target(resolved_doc, cite) == menge_block


def test_navigation_left_click_epsilon_goes_to_konvergenz_after_resolution(
    structure_ready_doc: MathDocument,
) -> None:
    """#15.5 NAVIGATION: a convergence epsilon occurrence targets the
    Konvergenz block ONLY after resolution (None before)."""
    doc = structure_ready_doc
    conv = _convergence_formula(doc)
    eps = _symbol_occs(doc, conv, "ε")[0]

    # Before resolution the symbol points at a pending stub -> no target.
    assert definition_target(doc, eps) is None

    run_full(doc, resolver=MockResolver(), wait=True)

    konv_block = _block(doc, type_="Definition", defined_name="Konvergenz")
    # Re-fetch the (same) occurrence after the in-place resolution.
    eps_after = _symbol_occs(doc, conv, "ε")[0]
    assert definition_target(doc, eps_after) == konv_block


def test_navigation_unresolved_symbol_has_no_target(
    resolved_doc: MathDocument,
) -> None:
    """#15.5 NAVIGATION: a symbol whose concept stays pending (e.g. ℝ / x₁ / n)
    yields None — the disabled "resolving…" state — even post-resolution."""
    pending = next(
        o
        for o in resolved_doc.occurrences
        if o.kind == "formula_symbol"
        and o.concept_id is not None
        and _concept_status(resolved_doc, o.concept_id) == "pending"
    )
    assert definition_target(resolved_doc, pending) is None


# ===========================================================================
# Scenario 6 — CONCEPT CARD
# ===========================================================================


def test_concept_card_konvergenz_has_meaning_references_and_both_neighbourhoods(
    resolved_doc: MathDocument,
) -> None:
    """#15.6 CONCEPT CARD: concept_card for Konvergenz exposes formal meaning, a
    references list (non-defining occurrences), and a neighbourhood with BOTH
    structural and semantic entries."""
    konv = _concept(resolved_doc, "Konvergenz")
    card = concept_card(resolved_doc, konv.id)

    assert card["name"] == "Konvergenz"
    assert card["resolution_status"] == "resolved"
    assert card["formal_meaning"]  # authoritative meaning present

    # References = non-defining occurrences linked to the concept.
    assert card["defining_occurrence"] is not None
    assert card["references"], "expected non-defining references"
    defining_id = card["defining_occurrence"]["id"]
    assert all(r["occurrence_id"] != defining_id for r in card["references"])

    nb = card["neighbourhood"]
    assert nb["structural"], "structural neighbourhood (seeded_by) expected"
    assert nb["semantic"], "semantic neighbourhood (defines/uses) expected"
    assert all(e["origin"] == "semantic" for e in nb["semantic"])
    # The structural seeded_by edge points at a block, not a concept.
    seeded = [e for e in nb["structural"] if e["kind"] == "seeded_by"]
    assert seeded and seeded[0]["block_id"] is not None
    assert seeded[0]["concept_id"] is None


def test_concept_card_structural_neighbourhood_present_at_structure_ready(
    structure_ready_doc: MathDocument,
) -> None:
    """#15.6 CONCEPT CARD: structural neighbourhood entries are present already at
    structure_ready (before any resolver), with no semantic entries yet."""
    doc = structure_ready_doc
    konv = _concept(doc, "Konvergenz")
    card = concept_card(doc, konv.id)
    assert card["neighbourhood"]["structural"], "structural edges at stage 1"
    assert card["neighbourhood"]["semantic"] == []  # LLM has not run


def test_concept_card_via_build_ide_payload_for_konvergenz(
    resolved_doc: MathDocument,
) -> None:
    """#15.6 CONCEPT CARD: build_ide_payload carries the same precomputed
    Konvergenz card the side panel renders."""
    payload = build_ide_payload(resolved_doc)
    konv = _concept(resolved_doc, "Konvergenz")
    assert konv.id in payload["cards"]
    card = payload["cards"][konv.id]
    assert card == concept_card(resolved_doc, konv.id)
    assert card["formal_meaning"]
    assert card["references"]
    assert card["neighbourhood"]["structural"]
    assert card["neighbourhood"]["semantic"]


# ===========================================================================
# Scenario 7 — DUAL BBOXES
# ===========================================================================


def test_dual_bboxes_source_set_render_none_after_ingestion(
    structure_ready_doc: MathDocument,
) -> None:
    """#15.7 DUAL BBOXES: every import-time occurrence has a non-null
    source_bbox after ingestion; render_bbox is None pre-layout."""
    doc = structure_ready_doc
    assert doc.occurrences
    for occ in doc.occurrences:
        assert occ.source_bbox is not None, f"{occ.id} missing source_bbox"
        assert occ.render_bbox is None, f"{occ.id} render_bbox set pre-layout"


def test_dual_bboxes_source_unchanged_render_stays_none_after_resolution(
    structure_ready_doc: MathDocument,
) -> None:
    """#15.7 DUAL BBOXES: source_bbox is unchanged by resolution; render_bbox
    stays None offline (population is browser/layout-time — see the gated
    browser test ``tests/test_ide_browser.py``::
    test_render_bboxes_and_symbol_smaller_than_formula)."""
    doc = structure_ready_doc
    source_before = {
        o.id: o.source_bbox.model_dump() for o in doc.occurrences
    }

    run_full(doc, resolver=MockResolver(), wait=True)

    source_after = {
        o.id: (o.source_bbox.model_dump() if o.source_bbox else None)
        for o in doc.occurrences
    }
    # Resolution re-points concepts but never touches geometry.
    assert source_after == source_before
    # render_bbox population is layout/browser-time; offline it stays None.
    assert all(o.render_bbox is None for o in doc.occurrences)


# ===========================================================================
# STAGED — the IDE-relevant data is usable at structure_ready BEFORE resolution
# ===========================================================================


def test_staged_ide_data_usable_at_structure_ready_before_resolution(
    docling_dict: dict,
) -> None:
    """STAGED: citations, formal-block navigation and the structural
    neighbourhood are all usable at structure_ready — before stage 2 runs.

    Goes through the Pipeline so we observe the actual state machine: the
    renderer can open the document at structure_ready and these affordances
    already work."""
    doc = ingest_structure(docling_dict)
    pipeline = Pipeline(doc, resolver=MockResolver())
    assert pipeline.state == "structure_ready"
    assert pipeline.version == 0

    # 1. citation navigation works now (deterministic, no LLM).
    cite = _the_citation(doc)
    menge_block = _block(doc, type_="Definition", defined_name="Menge")
    assert definition_target(doc, cite) == menge_block

    # 2. formal-block navigation works now: the defined-name occurrence of each
    #    definition targets its own block.
    for name in ("Menge", "Injektivitaet", "Konvergenz"):
        block_id = _block(doc, type_="Definition", defined_name=name)
        name_occ = next(
            o
            for o in doc.occurrences
            if o.kind == "defined_name" and o.block_id == block_id
        )
        assert definition_target(doc, name_occ) == block_id

    # 3. the structural neighbourhood is queryable now.
    konv = _concept(doc, "Konvergenz")
    card = concept_card(doc, konv.id)
    assert card["neighbourhood"]["structural"]
    assert card["neighbourhood"]["semantic"] == []

    # 4. a fully renderable page can be produced at structure_ready.
    html = render_document(doc)
    assert 'data-ingestion-state="structure_ready"' in html
    assert "math-ide-data" in html  # embedded navigation payload

    # Only NOW advance stage 2; the version bumps and semantic data appears.
    pipeline.run_full(wait=True)
    assert pipeline.state == "ready"
    assert pipeline.version > 0
    assert concept_card(doc, konv.id)["neighbourhood"]["semantic"]


# ===========================================================================
# FORMULA-UPGRADE — re-entrant enrichment without full re-ingest
# ===========================================================================


def test_formula_upgrade_refreshes_render_without_full_reingest(
    resolved_doc: MathDocument,
) -> None:
    """FORMULA-UPGRADE: apply_formula_upgrade promotes a pending formula
    (pending -> ready), refreshes its symbol occurrences against the new LaTeX,
    leaves unrelated blocks untouched, and the page re-renders from the enriched
    LaTeX — all without re-ingesting the document."""
    doc = resolved_doc
    conv = _convergence_formula(doc)
    inj = _injectivity_formula(doc)
    assert conv.enrichment_status == "pending"

    # Snapshot the unrelated (injectivity) formula and its occurrences.
    inj_occ_before = [
        (o.id, o.span, o.concept_id)
        for o in doc.occurrences
        if o.block_id == inj.id
    ]
    inj_fields_before = (inj.latex, inj.enrichment_status)

    apply_formula_upgrade(doc, conv.id, CONVERGENCE_LATEX)

    # The upgraded formula is now ready and indexes the LaTeX.
    assert conv.enrichment_status == "ready"
    assert conv.latex == CONVERGENCE_LATEX
    assert conv.canonical_content == CONVERGENCE_LATEX

    # Its symbol occurrences are refreshed against the new index and re-measure.
    conv_occ_after = [o for o in doc.occurrences if o.block_id == conv.id]
    assert conv_occ_after
    assert len(conv_occ_after) == len(conv.symbol_index)
    for occ in conv_occ_after:
        start, end = occ.span
        assert conv.canonical_content[start:end]  # offsets index the LaTeX
        assert occ.render_bbox is None  # renderer re-measures (#11)
        assert occ.source_bbox is not None
        assert occ.concept_id is not None

    # Unrelated formula + its occurrences are byte-for-byte unchanged.
    inj_occ_after = [
        (o.id, o.span, o.concept_id)
        for o in doc.occurrences
        if o.block_id == inj.id
    ]
    assert inj_occ_after == inj_occ_before
    assert (inj.latex, inj.enrichment_status) == inj_fields_before

    # The page now renders the enriched formula as a KaTeX target carrying the
    # upgraded LaTeX (HTML-escaped, since it contains '<'/'>').
    html = render_document(doc)
    assert 'data-enrichment="ready"' in html
    assert f'data-latex="{escape(CONVERGENCE_LATEX, quote=True)}"' in html


def test_formula_upgrade_preserves_resolved_symbol_link(
    resolved_doc: MathDocument,
) -> None:
    """FORMULA-UPGRADE: a symbol the resolver coreferenced to a formal concept
    KEEPS that link across the upgrade — it is not regressed back to its bare
    per-token stub — and go-to-definition still works (#14 coreference path).

    Exercised for two surviving symbols:

    * ``a_n`` — token is byte-identical in the LaTeX upgrade;
    * ``ε`` -> ``\\varepsilon`` — token *changes spelling*, surviving only via
      the upgrade's LaTeX<->unicode token normalisation.

    For both, after the upgrade the freshly-derived occurrence must still link to
    the Konvergenz concept and ``definition_target`` must still resolve to the
    Konvergenz definition block."""
    doc = resolved_doc
    conv = _convergence_formula(doc)
    konv = _concept(doc, "Konvergenz")
    konv_block = _block(doc, type_="Definition", defined_name="Konvergenz")

    # Both symbols are resolved (coreferenced to Konvergenz) before the upgrade,
    # and their stub concepts carry an inferred meaning.
    a_n = _concept(doc, "a_n")
    eps = _concept(doc, "ε")
    assert a_n.resolution_status == "resolved" and a_n.inferred_meaning
    assert eps.resolution_status == "resolved" and eps.inferred_meaning
    eps_occ_before = _symbol_occs(doc, conv, "ε")
    a_n_occ_before = _symbol_occs(doc, conv, "a_n")
    assert eps_occ_before and a_n_occ_before
    assert all(o.concept_id == konv.id for o in eps_occ_before + a_n_occ_before)
    # Go-to-definition reaches Konvergenz before the upgrade.
    assert definition_target(doc, eps_occ_before[0]) == konv_block
    assert definition_target(doc, a_n_occ_before[0]) == konv_block

    apply_formula_upgrade(doc, conv.id, CONVERGENCE_LATEX)

    # The stub concepts survive the reflow with their inferred meanings intact.
    for stub in (a_n, eps):
        survivor = next((c for c in doc.concepts if c.id == stub.id), None)
        assert survivor is not None, f"{stub.name} stub must survive the reflow"
        assert survivor.resolution_status == "resolved"
        assert survivor.inferred_meaning == stub.inferred_meaning

    # ``a_n`` is byte-identical; ``ε`` is now spelled ``\varepsilon`` — both
    # surviving occurrences STILL link to Konvergenz (not their bare stubs).
    a_n_after = _symbol_occs(doc, conv, "a_n")
    eps_after = _symbol_occs(doc, conv, r"\varepsilon")
    assert a_n_after and eps_after
    for occ in a_n_after + eps_after:
        assert occ.concept_id == konv.id
        # ... and go-to-definition still reaches the Konvergenz block.
        assert definition_target(doc, occ) == konv_block


def test_formula_upgrade_via_pipeline_bumps_version_and_round_trips(
    docling_dict: dict,
) -> None:
    """FORMULA-UPGRADE: the Pipeline upgrade hook bumps the version (renderer
    refresh cue) and the mutated document still validates against the schema."""
    doc = ingest_structure(docling_dict)
    pipeline = Pipeline(doc, resolver=MockResolver())
    pipeline.run_full(wait=True)
    conv = _convergence_formula(doc)
    version_before = pipeline.version

    pipeline.apply_formula_upgrade(conv.id, CONVERGENCE_LATEX)

    assert pipeline.version == version_before + 1
    assert conv.enrichment_status == "ready"
    # Round-trips through the schema after mutation.
    MathDocument.model_validate(json.loads(doc.model_dump_json()))
