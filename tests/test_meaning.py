"""Tests for meaning resolution — the async LLM stage (issue #9).

Only :class:`MockResolver` is exercised against real data; the
:class:`AnthropicResolver` tests stub the SDK so no network is touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from math_ide.ingest import build_math_document
from math_ide.ontology import (
    AnthropicResolver,
    MockResolver,
    Resolver,
    seed_ontology,
)
from math_ide.ontology.meaning import DEFAULT_MODEL, MeaningDelta
from math_ide.schema import MathDocument

FIXTURE = Path(__file__).parent / "fixtures" / "example_docling.json"


@pytest.fixture()
def seeded() -> MathDocument:
    """A freshly seeded (structure_ready) document from the canonical fixture."""
    docling = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return seed_ontology(build_math_document(docling))


def _concept_by_name(doc: MathDocument, name: str):
    return next(c for c in doc.concepts if c.name == name)


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


def test_mock_and_anthropic_satisfy_resolver_protocol() -> None:
    assert isinstance(MockResolver(), Resolver)
    assert isinstance(AnthropicResolver(), Resolver)


def test_resolve_returns_same_document(seeded: MathDocument) -> None:
    returned = MockResolver().resolve(seeded)
    assert returned is seeded


def test_anthropic_resolver_defaults_to_sonnet() -> None:
    assert AnthropicResolver().model == DEFAULT_MODEL == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Acceptance: ε links to the Konvergenz concept (Definition 2.1)
# ---------------------------------------------------------------------------


def test_epsilon_links_to_konvergenz_concept(seeded: MathDocument) -> None:
    """After resolution the convergence ε corefers with the Konvergenz concept.

    Asserted *both* ways the resolver records the link: every ε occurrence's
    ``concept_id`` now points at Konvergenz, AND a semantic relation connects
    ε's stub concept to Konvergenz.
    """
    eps = _concept_by_name(seeded, "ε")
    konvergenz = _concept_by_name(seeded, "Konvergenz")

    MockResolver().resolve(seeded)

    # ε occurrences (the symbol inside the convergence formula) point at the
    # Konvergenz concept now.
    eps_occurrences = [
        o
        for o in seeded.occurrences
        if o.kind == "formula_symbol"
        and o.span is not None
        and _occ_token(seeded, o) == "ε"
    ]
    assert eps_occurrences  # the fixture has ε occurrences
    assert all(o.concept_id == konvergenz.id for o in eps_occurrences)

    # ... and a semantic relation makes the link discoverable concept-to-concept.
    semantic = {
        (r.source_concept_id, r.target_concept_id, r.kind)
        for r in seeded.relations
        if r.origin == "semantic"
    }
    assert (eps.id, konvergenz.id, "uses") in semantic

    # The Konvergenz concept (already resolved) stays resolved.
    assert konvergenz.resolution_status == "resolved"


def _occ_token(doc: MathDocument, occ) -> str:
    from math_ide.schema import Formula
    from math_ide.ontology.occurrences import iter_blocks

    formula = next(
        b
        for b in iter_blocks(doc.blocks)
        if isinstance(b, Formula) and b.id == occ.block_id
    )
    return formula.canonical_content[occ.span[0] : occ.span[1]]


# ---------------------------------------------------------------------------
# Acceptance: f, X, Y consistent with the Injektivitaet definition
# ---------------------------------------------------------------------------


def test_injectivity_symbols_consistent_with_definition(seeded: MathDocument) -> None:
    """f and X (the injectivity formula's symbols) corefer with Injektivitaet."""
    inj = _concept_by_name(seeded, "Injektivitaet")
    f = _concept_by_name(seeded, "f")
    x = _concept_by_name(seeded, "X")

    MockResolver().resolve(seeded)

    semantic = {
        (r.source_concept_id, r.target_concept_id, r.kind)
        for r in seeded.relations
        if r.origin == "semantic"
    }
    # f and X both relate to the Injektivitaet concept.
    assert (f.id, inj.id, "uses") in semantic
    assert (x.id, inj.id, "uses") in semantic

    # Their occurrences in the injectivity formula now point at Injektivitaet.
    for token, concept in (("f", f), ("X", x)):
        occs = [
            o
            for o in seeded.occurrences
            if o.kind == "formula_symbol"
            and o.span is not None
            and _occ_token(seeded, o) == token
        ]
        assert occs
        assert all(o.concept_id == inj.id for o in occs)

    # f and X got an inferred meaning (they are stub concepts).
    assert f.inferred_meaning
    assert x.inferred_meaning


def test_codomain_Y_handled_even_without_a_formula_occurrence(
    seeded: MathDocument,
) -> None:
    """Y appears only in prose (f: X -> Y), so the seeder makes no Y stub.

    The MockResolver must tolerate that: f/X are still linked, and resolution
    does not crash on the missing Y token.
    """
    names = {c.name for c in seeded.concepts}
    assert "Y" not in names  # confirm the corpus shape this test guards

    # Resolution succeeds despite the missing Y token.
    MockResolver().resolve(seeded)
    assert seeded.ingestion_state == "ready"


# ---------------------------------------------------------------------------
# Rule: formal_meaning is byte-for-byte unchanged
# ---------------------------------------------------------------------------


def test_formal_meaning_unchanged_after_resolve(seeded: MathDocument) -> None:
    before = {
        c.id: c.formal_meaning
        for c in seeded.concepts
        if c.formal_meaning is not None
    }
    # the three definition concepts have formal meanings
    assert {c.name for c in seeded.concepts if c.formal_meaning is not None} == {
        "Menge",
        "Injektivitaet",
        "Konvergenz",
    }

    MockResolver().resolve(seeded)

    after = {
        c.id: c.formal_meaning
        for c in seeded.concepts
        if c.formal_meaning is not None
    }
    assert after == before  # byte-for-byte identical


def test_inferred_meaning_never_set_on_formal_concepts(seeded: MathDocument) -> None:
    MockResolver().resolve(seeded)
    for c in seeded.concepts:
        if c.formal_meaning is not None:
            # a formal concept keeps formal_meaning authoritative; the resolver
            # must not have invented an inferred_meaning for it.
            assert c.inferred_meaning is None


def test_delta_refuses_to_write_formal_meaning(seeded: MathDocument) -> None:
    """The MeaningDelta guardrail drops inferred_meaning for formal concepts."""
    konvergenz = _concept_by_name(seeded, "Konvergenz")
    original = konvergenz.formal_meaning
    delta = MeaningDelta()
    delta.infer(konvergenz.id, "BOGUS — should be ignored")
    delta.apply(seeded)
    assert konvergenz.formal_meaning == original
    assert konvergenz.inferred_meaning is None


# ---------------------------------------------------------------------------
# Semantic vs structural relations
# ---------------------------------------------------------------------------


def test_semantic_relations_present_and_marked(seeded: MathDocument) -> None:
    MockResolver().resolve(seeded)
    semantic = [r for r in seeded.relations if r.origin == "semantic"]
    assert semantic  # the resolver added some
    semantic_kinds = {"uses", "defines", "generalizes", "specializes", "instance_of"}
    for r in semantic:
        assert r.origin == "semantic"
        assert r.kind in semantic_kinds


def test_structural_relations_untouched_by_resolution(seeded: MathDocument) -> None:
    before = sorted(
        (r.source_concept_id, r.target_concept_id, r.kind)
        for r in seeded.relations
        if r.origin == "structural"
    )
    MockResolver().resolve(seeded)
    after = sorted(
        (r.source_concept_id, r.target_concept_id, r.kind)
        for r in seeded.relations
        if r.origin == "structural"
    )
    assert after == before  # structural edges neither added, removed, nor relabelled
    # and structural kinds stay structural-only
    for r in seeded.relations:
        if r.origin == "structural":
            assert r.kind in {"seeded_by", "sibling", "co_occurring"}


# ---------------------------------------------------------------------------
# Resolution status + ingestion state
# ---------------------------------------------------------------------------


def test_touched_concepts_flip_to_resolved(seeded: MathDocument) -> None:
    eps = _concept_by_name(seeded, "ε")
    assert eps.resolution_status == "pending"  # stub starts pending
    MockResolver().resolve(seeded)
    assert eps.resolution_status == "resolved"


def test_resolution_sets_ingestion_state_ready(seeded: MathDocument) -> None:
    assert seeded.ingestion_state == "structure_ready"
    MockResolver().resolve(seeded)
    assert seeded.ingestion_state == "ready"


def test_resolution_is_idempotent(seeded: MathDocument) -> None:
    r = MockResolver()
    r.resolve(seeded)
    once = seeded.model_dump_json()
    r.resolve(seeded)
    twice = seeded.model_dump_json()
    assert once == twice  # de-duplicated delta -> no drift on re-run


def test_round_trip_after_resolution(seeded: MathDocument) -> None:
    MockResolver().resolve(seeded)
    restored = MathDocument.model_validate_json(seeded.model_dump_json())
    assert restored == seeded


# ---------------------------------------------------------------------------
# AnthropicResolver — offline behaviour only (no network)
# ---------------------------------------------------------------------------


class _StubMessage:
    def __init__(self, text: str) -> None:
        self.content = [type("Block", (), {"type": "text", "text": text})()]


class _StubMessages:
    def __init__(self, behaviour) -> None:
        self._behaviour = behaviour

    def create(self, **kwargs):
        return self._behaviour(kwargs)


class _StubClient:
    def __init__(self, behaviour) -> None:
        self.messages = _StubMessages(behaviour)


def _install_stub_anthropic(monkeypatch, behaviour) -> None:
    """Patch the lazily-imported ``anthropic`` module with a stub client."""
    import types

    stub = types.ModuleType("anthropic")
    stub.Anthropic = lambda **kwargs: _StubClient(behaviour)  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "anthropic", stub)


def test_anthropic_resolver_applies_valid_reply(monkeypatch, seeded) -> None:
    """A well-formed JSON reply is parsed and applied; doc reaches ready."""
    eps = _concept_by_name(seeded, "ε")
    konvergenz = _concept_by_name(seeded, "Konvergenz")
    eps_occ = next(
        o
        for o in seeded.occurrences
        if o.kind == "formula_symbol"
        and o.span is not None
        and _occ_token(seeded, o) == "ε"
    )
    reply = json.dumps(
        {
            "occurrence_links": [
                {"occurrence_id": eps_occ.id, "concept_id": konvergenz.id}
            ],
            "inferred_meanings": [
                {"concept_id": eps.id, "meaning": "error bound"}
            ],
            "relations": [
                {
                    "source_concept_id": eps.id,
                    "target_concept_id": konvergenz.id,
                    "kind": "uses",
                }
            ],
        }
    )
    _install_stub_anthropic(monkeypatch, lambda kwargs: _StubMessage(reply))

    AnthropicResolver(max_retries=1).resolve(seeded)

    assert seeded.ingestion_state == "ready"
    assert eps_occ.concept_id == konvergenz.id
    assert eps.inferred_meaning == "error bound"
    semantic = {
        (r.source_concept_id, r.target_concept_id, r.kind)
        for r in seeded.relations
        if r.origin == "semantic"
    }
    assert (eps.id, konvergenz.id, "uses") in semantic


def test_anthropic_resolver_tolerates_failure_with_partial_doc(
    monkeypatch, seeded
) -> None:
    """On repeated API failure the resolver returns a usable (partial) doc."""
    calls = {"n": 0}

    def always_fail(_kwargs):
        calls["n"] += 1
        raise RuntimeError("simulated API outage")

    _install_stub_anthropic(monkeypatch, always_fail)

    formal_before = {
        c.id: c.formal_meaning
        for c in seeded.concepts
        if c.formal_meaning is not None
    }

    result = AnthropicResolver(max_retries=2).resolve(seeded)

    # never crashed; same document is returned and is still usable
    assert result is seeded
    assert calls["n"] == 3  # initial attempt + 2 retries

    # partial: no semantic relations were added, structural ones intact
    assert not any(r.origin == "semantic" for r in result.relations)
    assert any(r.origin == "structural" for r in result.relations)

    # formal meaning still authoritative and unchanged
    formal_after = {
        c.id: c.formal_meaning
        for c in result.concepts
        if c.formal_meaning is not None
    }
    assert formal_after == formal_before

    # state did not advance to ready (signals partial resolution to the pipeline)
    assert result.ingestion_state == "resolving"

    # the document still round-trips — it is a valid MathDocument
    restored = MathDocument.model_validate_json(result.model_dump_json())
    assert restored == result


def test_anthropic_resolver_retries_then_succeeds(monkeypatch, seeded) -> None:
    """A transient failure is retried; a later success is applied."""
    eps = _concept_by_name(seeded, "ε")
    reply = json.dumps(
        {
            "inferred_meanings": [{"concept_id": eps.id, "meaning": "epsilon"}],
            "relations": [],
            "occurrence_links": [],
        }
    )
    state = {"n": 0}

    def fail_once(_kwargs):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("transient")
        return _StubMessage(reply)

    _install_stub_anthropic(monkeypatch, fail_once)

    AnthropicResolver(max_retries=2).resolve(seeded)
    assert state["n"] == 2  # failed once, succeeded on the retry
    assert seeded.ingestion_state == "ready"
    assert eps.inferred_meaning == "epsilon"


def test_anthropic_resolver_tolerates_unparseable_reply(monkeypatch, seeded) -> None:
    """Non-JSON replies are treated as failures, not crashes."""
    _install_stub_anthropic(
        monkeypatch, lambda kwargs: _StubMessage("I cannot help with that.")
    )
    result = AnthropicResolver(max_retries=1).resolve(seeded)
    assert result is seeded
    assert result.ingestion_state == "resolving"  # partial, never crashed


def test_anthropic_resolver_handles_fenced_json(monkeypatch, seeded) -> None:
    """A reply wrapped in a ```json fence is still parsed."""
    eps = _concept_by_name(seeded, "ε")
    inner = json.dumps(
        {
            "inferred_meanings": [{"concept_id": eps.id, "meaning": "fenced"}],
        }
    )
    fenced = f"Here you go:\n```json\n{inner}\n```\n"
    _install_stub_anthropic(monkeypatch, lambda kwargs: _StubMessage(fenced))
    AnthropicResolver(max_retries=0).resolve(seeded)
    assert eps.inferred_meaning == "fenced"
    assert seeded.ingestion_state == "ready"


def test_build_prompt_includes_concepts_and_tokens(seeded: MathDocument) -> None:
    prompt = AnthropicResolver().build_prompt(seeded)
    assert "Konvergenz" in prompt
    assert "ε" in prompt
    # the documented schema keys appear so the model knows the contract
    assert "occurrence_links" in prompt
    assert "inferred_meanings" in prompt
