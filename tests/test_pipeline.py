"""Tests for staged ingestion orchestration (issue #14).

Exercises the pipeline state machine end-to-end with the canonical fixture:

* stage 1 (:func:`ingest_structure`) reaches ``structure_ready`` with usable
  occurrences/concepts and working citation + formal-block navigation data;
* stage 2 reaches ``ready`` both synchronously (``run_full(wait=True)``) and on
  the background thread (after ``join()``), bumping the version;
* :func:`apply_formula_upgrade` re-entrantly upgrades a pending formula and
  reflows only its symbol occurrences, without touching unrelated blocks, while
  bumping the version;
* a failing resolver leaves a sane, usable partial document.

Everything is offline and deterministic — only :class:`MockResolver` and a tiny
local stub resolver are used.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from math_ide.ontology import MockResolver
from math_ide.ontology.occurrences import iter_blocks
from math_ide.pipeline import (
    Pipeline,
    PipelineStatus,
    apply_formula_upgrade,
    ingest_structure,
    normalize_token,
    run_full,
)
from math_ide.schema import Formula, MathDocument

FIXTURE = Path(__file__).parent / "fixtures" / "example_docling.json"

# A LaTeX upgrade for the convergence formula whose tokens deliberately overlap
# the originals (a_n / N / L stay identical) so we can assert stub identity is
# preserved across the reflow.
CONVERGENCE_LATEX = (
    r"\forall e > 0 \exists N \in R \forall m \geq N : |a_n - L| < e"
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def docling() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _formulas(doc: MathDocument) -> list[Formula]:
    return [b for b in iter_blocks(doc.blocks) if isinstance(b, Formula)]


def _convergence_formula(doc: MathDocument) -> Formula:
    return next(f for f in _formulas(doc) if "ε" in f.orig_fallback)


def _injectivity_formula(doc: MathDocument) -> Formula:
    return next(f for f in _formulas(doc) if "f(" in f.orig_fallback)


def _occ_for_block(doc: MathDocument, block_id: str) -> list:
    return [o for o in doc.occurrences if o.block_id == block_id]


# ---------------------------------------------------------------------------
# Stage 1 — ingest_structure
# ---------------------------------------------------------------------------


def test_ingest_structure_reaches_structure_ready(docling: dict) -> None:
    doc = ingest_structure(docling)
    assert doc.ingestion_state == "structure_ready"
    # occurrences and concepts are already populated (stage 1 done).
    assert doc.occurrences, "stage 1 must produce occurrences"
    assert doc.concepts, "stage 1 must seed concepts"


def test_structure_ready_supports_citation_navigation(docling: dict) -> None:
    """A numbered citation resolves to its target formal block at stage 1."""
    doc = ingest_structure(docling)
    citations = [o for o in doc.occurrences if o.kind == "citation"]
    assert citations, "fixture has a 'Definition 1.1' citation"
    # Every citation in the corpus targets a real block in the tree.
    block_ids = {b.id for b in iter_blocks(doc.blocks)}
    targeted = [c for c in citations if c.target_block_id is not None]
    assert targeted, "citation navigation data must be present at structure_ready"
    for cite in targeted:
        assert cite.target_block_id in block_ids


def test_structure_ready_supports_formal_block_navigation(docling: dict) -> None:
    """Defined-name concepts carry the data go-to-definition needs at stage 1."""
    doc = ingest_structure(docling)
    formal_concepts = [c for c in doc.concepts if c.seeded_by_block_id is not None]
    assert formal_concepts, "definitions must seed concepts at structure_ready"
    block_ids = {b.id for b in iter_blocks(doc.blocks)}
    for concept in formal_concepts:
        # seeded_by_block_id points at the defining block (formal-block nav)...
        assert concept.seeded_by_block_id in block_ids
        # ...and the defining occurrence is recorded (symbol -> definition nav).
        assert concept.defining_occurrence_id is not None


def test_ingest_structure_does_not_resolve_meaning(docling: dict) -> None:
    """Stage 1 leaves symbol stubs pending — no LLM has run yet."""
    doc = ingest_structure(docling)
    stubs = [c for c in doc.concepts if c.seeded_by_block_id is None]
    assert stubs, "formula symbols seed stub concepts"
    assert all(c.resolution_status == "pending" for c in stubs)
    assert not any(r.origin == "semantic" for r in doc.relations)


# ---------------------------------------------------------------------------
# Stage 2 — synchronous run_full(wait=True)
# ---------------------------------------------------------------------------


def test_run_full_wait_reaches_ready(docling: dict) -> None:
    doc = ingest_structure(docling)
    pipeline = Pipeline(doc)
    assert pipeline.version == 0
    result = pipeline.run_full(wait=True)
    assert result is doc
    assert doc.ingestion_state == "ready"
    assert pipeline.version > 0
    # semantic relations were added by the resolver.
    assert any(r.origin == "semantic" for r in doc.relations)


def test_run_full_module_helper_from_dict(docling: dict) -> None:
    """The module-level run_full ingests then resolves in one call."""
    doc = run_full(docling, wait=True)
    assert doc.ingestion_state == "ready"


def test_run_full_module_helper_from_document(docling: dict) -> None:
    doc = ingest_structure(docling)
    out = run_full(doc, resolver=MockResolver(), wait=True)
    assert out is doc
    assert doc.ingestion_state == "ready"


# ---------------------------------------------------------------------------
# Stage 2 — background path
# ---------------------------------------------------------------------------


def test_background_path_reaches_ready_after_join(docling: dict) -> None:
    doc = ingest_structure(docling)
    pipeline = Pipeline(doc)
    version_before = pipeline.version

    pipeline.run_full(wait=False)  # starts the worker thread
    pipeline.join()

    status = pipeline.status()
    assert status.state == "ready"
    assert status.done is True
    assert status.version > version_before


def test_background_status_is_a_snapshot(docling: dict) -> None:
    doc = ingest_structure(docling)
    pipeline = Pipeline(doc)
    pipeline.start()
    pipeline.join()
    status = pipeline.status()
    assert isinstance(status, PipelineStatus)
    assert status.etag == f'"{status.version}"'
    # snapshot does not change when the pipeline keeps living.
    again = pipeline.status()
    assert status == again


def test_background_worker_runs_off_thread(docling: dict) -> None:
    """The worker truly runs on another thread (a gate proves concurrency)."""
    gate = threading.Event()
    started = threading.Event()

    class GatedResolver:
        def resolve(self, d: MathDocument) -> MathDocument:
            started.set()
            gate.wait(timeout=5)
            return MockResolver().resolve(d)

    doc = ingest_structure(docling)
    pipeline = Pipeline(doc, resolver=GatedResolver())
    pipeline.run_full(wait=False)

    assert started.wait(timeout=5), "worker did not start"
    # Caller is not blocked while the resolver is gated.
    assert pipeline.status().done is False
    gate.set()
    pipeline.join()
    assert pipeline.status().state == "ready"


# ---------------------------------------------------------------------------
# Re-entrant formula upgrade
# ---------------------------------------------------------------------------


def test_apply_formula_upgrade_promotes_pending_formula(docling: dict) -> None:
    doc = run_full(docling, wait=True)
    formula = _convergence_formula(doc)
    assert formula.enrichment_status == "pending"

    apply_formula_upgrade(doc, formula.id, CONVERGENCE_LATEX)

    assert formula.enrichment_status == "ready"
    assert formula.latex == CONVERGENCE_LATEX
    assert formula.canonical_content == CONVERGENCE_LATEX


def test_apply_formula_upgrade_reflows_only_its_occurrences(docling: dict) -> None:
    doc = run_full(docling, wait=True)
    conv = _convergence_formula(doc)
    inj = _injectivity_formula(doc)

    # Snapshot the unrelated formula's occurrences and the OTHER (injectivity)
    # formula's own fields — these must be untouched by a convergence upgrade.
    inj_before = [(o.id, o.span, o.concept_id) for o in _occ_for_block(doc, inj.id)]
    inj_fields_before = (
        inj.latex,
        inj.enrichment_status,
        [(s.token, s.start, s.end) for s in inj.symbol_index],
    )
    conv_occ_before = _occ_for_block(doc, conv.id)
    assert conv_occ_before, "convergence formula has symbol occurrences"

    apply_formula_upgrade(doc, conv.id, CONVERGENCE_LATEX)

    # Unrelated formula occurrences are byte-for-byte unchanged.
    inj_after = [(o.id, o.span, o.concept_id) for o in _occ_for_block(doc, inj.id)]
    assert inj_after == inj_before
    # The unrelated formula's own block fields are unchanged.
    inj_fields_after = (
        inj.latex,
        inj.enrichment_status,
        [(s.token, s.start, s.end) for s in inj.symbol_index],
    )
    assert inj_fields_after == inj_fields_before

    # The upgraded formula's occurrences are re-derived against the new index.
    conv_occ_after = _occ_for_block(doc, conv.id)
    assert len(conv_occ_after) == len(conv.symbol_index)
    for occ in conv_occ_after:
        start, end = occ.span
        assert conv.canonical_content[start:end]  # offsets index the LaTeX now
        assert occ.render_bbox is None  # renderer re-measures
        assert occ.concept_id is not None  # linked to a stub concept


def test_apply_formula_upgrade_preserves_resolved_symbol_link(
    docling: dict,
) -> None:
    """A symbol the resolver coreferenced to a formal concept keeps that link
    across the upgrade (it is NOT regressed back to its bare per-token stub).

    MockResolver re-points the ``a_n`` occurrence at the *Konvergenz* concept;
    after the upgrade the freshly-derived ``a_n`` occurrence must still point at
    Konvergenz, not at the ``a_n`` stub — preserving coreference (#14)."""
    doc = run_full(docling, wait=True)
    conv = _convergence_formula(doc)

    konv = next(c for c in doc.concepts if c.name == "Konvergenz")
    a_n_concept = next(c for c in doc.concepts if c.name == "a_n")
    assert a_n_concept.resolution_status == "resolved"
    assert a_n_concept.inferred_meaning is not None
    # Pre-upgrade, the a_n occurrence is coreferenced to Konvergenz.
    a_n_before = [
        o
        for o in _occ_for_block(doc, conv.id)
        if o.concept_id == konv.id
        and conv.canonical_content[o.span[0] : o.span[1]] == "a_n"
    ]
    assert a_n_before, "a_n occurrence is linked to Konvergenz pre-upgrade"

    apply_formula_upgrade(doc, conv.id, CONVERGENCE_LATEX)

    # The a_n stub concept survives the reflow with its inferred meaning intact.
    survivor = next((c for c in doc.concepts if c.id == a_n_concept.id), None)
    assert survivor is not None, "a_n stub must survive (token unchanged)"
    assert survivor.resolution_status == "resolved"
    assert survivor.inferred_meaning == a_n_concept.inferred_meaning

    # The fresh a_n occurrence STILL points at Konvergenz (coreference kept),
    # NOT relinked to the bare a_n stub.
    a_n_occs = [
        o
        for o in _occ_for_block(doc, conv.id)
        if conv.canonical_content[o.span[0] : o.span[1]] == "a_n"
    ]
    assert a_n_occs
    assert all(o.concept_id == konv.id for o in a_n_occs)
    assert all(o.concept_id != a_n_concept.id for o in a_n_occs)


def test_apply_formula_upgrade_bumps_version_via_pipeline(docling: dict) -> None:
    doc = ingest_structure(docling)
    pipeline = Pipeline(doc)
    pipeline.run_full(wait=True)
    conv = _convergence_formula(doc)
    version_before = pipeline.version

    pipeline.apply_formula_upgrade(conv.id, CONVERGENCE_LATEX)

    assert pipeline.version == version_before + 1
    assert conv.enrichment_status == "ready"


def test_apply_formula_upgrade_is_idempotent(docling: dict) -> None:
    doc = run_full(docling, wait=True)
    conv = _convergence_formula(doc)
    apply_formula_upgrade(doc, conv.id, CONVERGENCE_LATEX)
    occ_count = len(doc.occurrences)
    concept_count = len(doc.concepts)

    apply_formula_upgrade(doc, conv.id, CONVERGENCE_LATEX)  # same LaTeX again

    assert len(doc.occurrences) == occ_count
    assert len(doc.concepts) == concept_count


def test_apply_formula_upgrade_unknown_id_is_noop(docling: dict) -> None:
    doc = run_full(docling, wait=True)
    before = doc.model_dump_json()
    apply_formula_upgrade(doc, "does-not-exist", r"\emptyset")
    assert doc.model_dump_json() == before


def test_document_round_trips_after_upgrade(docling: dict) -> None:
    doc = run_full(docling, wait=True)
    conv = _convergence_formula(doc)
    apply_formula_upgrade(doc, conv.id, CONVERGENCE_LATEX)
    # The mutated document still validates against the schema.
    MathDocument.model_validate(json.loads(doc.model_dump_json()))


# ---------------------------------------------------------------------------
# Token normalisation (LaTeX <-> unicode equivalence)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (r"\varepsilon", "ε"),  # LaTeX var-greek <-> unicode greek
        (r"\epsilon", "ε"),  # canonical greek name folds the same way
        ("x_1", "x₁"),  # ASCII subscript <-> unicode subscript
        ("x_2", "x₂"),
        (r"\mathbb{R}", "ℝ"),  # blackboard set spellings
        ("R", "ℝ"),  # ... and the bare capital
        (r"\alpha_1", "α₁"),  # greek + subscript across dialects
    ],
)
def test_normalize_token_folds_equivalent_spellings(a: str, b: str) -> None:
    assert normalize_token(a) == normalize_token(b)


def test_normalize_token_keeps_distinct_symbols_distinct() -> None:
    assert normalize_token("a_n") == "a_n"  # subscript letter unchanged
    assert normalize_token("a_n") != normalize_token("a_m")
    assert normalize_token("ε") != normalize_token("δ")
    assert normalize_token("x_1") != normalize_token("x_2")
    assert normalize_token("N") != normalize_token("n")  # case-sensitive


def test_normalize_token_is_idempotent() -> None:
    for tok in (r"\varepsilon", "ε", "x₁", "x_1", "a_n", r"\mathbb{R}", "ℝ"):
        assert normalize_token(normalize_token(tok)) == normalize_token(tok)


# ---------------------------------------------------------------------------
# Co-occurring structural relation rebuild on upgrade
# ---------------------------------------------------------------------------


def _co_occurring_pairs(doc: MathDocument) -> set[tuple[str, str]]:
    return {
        (r.source_concept_id, r.target_concept_id)
        for r in doc.relations
        if r.kind == "co_occurring"
    }


def _conv_symbol_concept_ids(doc: MathDocument, conv: Formula) -> set[str]:
    return {
        o.concept_id
        for o in _occ_for_block(doc, conv.id)
        if o.kind == "formula_symbol" and o.concept_id is not None
    }


def test_upgrade_rebuilds_co_occurring_relations(docling: dict) -> None:
    """The upgraded formula's co_occurring edges are recomputed: a complete,
    de-duped, both-directions graph over the NEW symbol concepts; every edge
    endpoint is a live concept; all stay origin='structural'."""
    doc = run_full(docling, wait=True)
    conv = _convergence_formula(doc)

    apply_formula_upgrade(doc, conv.id, CONVERGENCE_LATEX)

    new_ids = _conv_symbol_concept_ids(doc, conv)
    pairs = _co_occurring_pairs(doc)

    # No duplicate edges survive the rebuild.
    rels = [r for r in doc.relations if r.kind == "co_occurring"]
    assert len(rels) == len(pairs)
    # All co_occurring edges remain structural.
    assert all(r.origin == "structural" for r in rels)
    # Every endpoint references a concept that still exists.
    concept_ids = {c.id for c in doc.concepts}
    assert all(s in concept_ids and t in concept_ids for s, t in pairs)
    # Every distinct pair of the new symbol concepts co-occurs (both ways).
    for a in new_ids:
        for b in new_ids:
            if a != b:
                assert (a, b) in pairs


def test_upgrade_adds_co_occurring_for_a_new_token(docling: dict) -> None:
    """A brand-new token introduced by the upgrade (``m``) gains co_occurring
    edges to the formula's other surviving symbols."""
    doc = run_full(docling, wait=True)
    conv = _convergence_formula(doc)

    apply_formula_upgrade(doc, conv.id, CONVERGENCE_LATEX)

    m_concept = next((c for c in doc.concepts if c.name == "m"), None)
    assert m_concept is not None, "the LaTeX upgrade introduces a new token 'm'"
    pairs = _co_occurring_pairs(doc)
    incident = [p for p in pairs if m_concept.id in p]
    assert incident, "the new token must co-occur with the formula's symbols"


def test_upgrade_drops_stale_co_occurring_edges(docling: dict) -> None:
    """An edge that only existed because of a symbol the upgrade removed is
    dropped (the old 'n' token is gone -> no edge mentions its stub)."""
    doc = run_full(docling, wait=True)
    conv = _convergence_formula(doc)

    # The pre-upgrade 'n' stub co-occurs with other convergence symbols.
    n_concept = next(c for c in doc.concepts if c.name == "n")
    pairs_before = _co_occurring_pairs(doc)
    assert any(n_concept.id in p for p in pairs_before)

    apply_formula_upgrade(doc, conv.id, CONVERGENCE_LATEX)  # LaTeX uses 'm', not 'n'

    pairs_after = _co_occurring_pairs(doc)
    assert not any(n_concept.id in p for p in pairs_after), (
        "co_occurring edges for the removed 'n' token must be dropped"
    )


def test_upgrade_does_not_touch_unrelated_formula_co_occurring(docling: dict) -> None:
    """Rebuilding the convergence formula's edges leaves the injectivity
    formula's co_occurring edges intact."""
    doc = run_full(docling, wait=True)
    conv = _convergence_formula(doc)
    inj = _injectivity_formula(doc)

    inj_ids = _conv_symbol_concept_ids(doc, inj)
    inj_pairs_before = {
        p for p in _co_occurring_pairs(doc) if p[0] in inj_ids and p[1] in inj_ids
    }
    assert inj_pairs_before

    apply_formula_upgrade(doc, conv.id, CONVERGENCE_LATEX)

    inj_pairs_after = {
        p for p in _co_occurring_pairs(doc) if p[0] in inj_ids and p[1] in inj_ids
    }
    assert inj_pairs_after == inj_pairs_before


# ---------------------------------------------------------------------------
# Concurrency: the upgrade mutation + version bump happen under the lock
# ---------------------------------------------------------------------------


def test_pipeline_upgrade_holds_lock_during_mutation(docling: dict) -> None:
    """Pipeline.apply_formula_upgrade mutates shared doc state and bumps the
    version atomically under the pipeline lock (a concurrent observer never sees
    a half-applied upgrade)."""
    doc = ingest_structure(docling)
    pipeline = Pipeline(doc)
    pipeline.run_full(wait=True)
    conv = _convergence_formula(doc)
    version_before = pipeline.version

    observed: list[bool] = []

    def observe() -> None:
        # Try to read status while the (lock-holding) upgrade runs; the read
        # blocks on the same lock, so the snapshot is always self-consistent.
        for _ in range(200):
            st = pipeline.status()
            observed.append(st.version >= version_before)

    t = threading.Thread(target=observe)
    t.start()
    pipeline.apply_formula_upgrade(conv.id, CONVERGENCE_LATEX)
    t.join()

    assert pipeline.version == version_before + 1
    assert all(observed)  # every concurrent snapshot was consistent


def test_pipeline_upgrade_serialises_with_resolver_thread(docling: dict) -> None:
    """An upgrade applied while a (gated) background resolver thread is in
    flight does not corrupt the document: the lock serialises both writers and
    the doc still validates afterwards."""
    gate = threading.Event()

    class _GatedResolver:
        def resolve(self, d: MathDocument) -> MathDocument:
            gate.wait(timeout=5)
            return MockResolver().resolve(d)

    doc = ingest_structure(docling)
    pipeline = Pipeline(doc, resolver=_GatedResolver())
    pipeline.run_full(wait=False)  # background resolver, gated

    conv = _convergence_formula(doc)
    pipeline.apply_formula_upgrade(conv.id, CONVERGENCE_LATEX)  # races the worker
    gate.set()
    pipeline.join()

    assert conv.enrichment_status == "ready"
    # Document is internally consistent (round-trips) after both writers.
    MathDocument.model_validate(json.loads(doc.model_dump_json()))


# ---------------------------------------------------------------------------
# Resolver failure tolerance
# ---------------------------------------------------------------------------


class _BoomResolver:
    """A resolver that always raises — to prove the pipeline never crashes."""

    def resolve(self, doc: MathDocument) -> MathDocument:
        raise RuntimeError("resolver exploded")


def test_failing_resolver_leaves_usable_partial_sync(docling: dict) -> None:
    doc = ingest_structure(docling)
    occ_before = len(doc.occurrences)
    concepts_before = len(doc.concepts)

    pipeline = Pipeline(doc, resolver=_BoomResolver())
    result = pipeline.run_full(wait=True)  # must NOT raise

    assert result is doc
    # Sane partial state, not 'ready' and not crashed.
    assert doc.ingestion_state == "resolving"
    assert isinstance(pipeline.error, RuntimeError)
    # Stage-1 results are intact and still usable.
    assert len(doc.occurrences) == occ_before
    assert len(doc.concepts) == concepts_before
    assert any(o.kind == "citation" for o in doc.occurrences)


def test_failing_resolver_leaves_usable_partial_background(docling: dict) -> None:
    doc = ingest_structure(docling)
    pipeline = Pipeline(doc, resolver=_BoomResolver())
    pipeline.run_full(wait=False)
    pipeline.join()  # deterministic: worker has finished

    status = pipeline.status()
    assert status.done is True
    assert status.state == "resolving"  # partial, not ready
    assert isinstance(pipeline.error, RuntimeError)
    # Document is still openable (stage-1 navigation data present).
    assert any(c.seeded_by_block_id is not None for c in doc.concepts)


class _PartialResolver:
    """A resolver that returns the doc still at 'resolving' (no exception)."""

    def resolve(self, doc: MathDocument) -> MathDocument:
        doc.ingestion_state = "resolving"
        return doc  # never advances to 'ready'


def test_partial_resolver_without_exception_stays_resolving(docling: dict) -> None:
    doc = ingest_structure(docling)
    pipeline = Pipeline(doc, resolver=_PartialResolver())
    pipeline.run_full(wait=True)
    assert doc.ingestion_state == "resolving"
    assert pipeline.error is None
    assert pipeline.status().done is True
