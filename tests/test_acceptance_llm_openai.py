r"""Live-LLM acceptance tests (issue #19) — gated so CI never hits the network.

This module mirrors ``test_acceptance_llm.py`` but runs the RESOLUTION
assertions against the *real* :class:`~math_ide.ontology.OpenAIResolver` instead
of the deterministic :class:`~math_ide.ontology.MockResolver`. It is the
"runnable locally" companion to the offline suite, for the OpenAI provider.

Gating (all must hold, else the whole module is skipped)
--------------------------------------------------------
* ``RUN_LLM_TESTS=1`` in the environment — an explicit opt-in so a developer must
  *choose* to spend tokens; absent in CI.
* ``OPENAI_API_KEY`` present — so we never construct a client without a key.
* the ``openai`` SDK importable — via :func:`pytest.importorskip`.

Run locally with::

    RUN_LLM_TESTS=1 OPENAI_API_KEY=sk-... \
        .venv/bin/python -m pytest -q tests/test_acceptance_llm_openai.py

Because the LLM is non-deterministic, the assertions are intentionally
*structural and tolerant*: they check the invariants the resolver contract must
honour on the example corpus (formal meaning never overwritten; the document
reaches ``ready`` or a sane partial; epsilon coreference and semantic relations
appear when resolution succeeds) — not exact strings.
"""

from __future__ import annotations

import os

import pytest

from math_ide.ontology import OpenAIResolver
from math_ide.ontology.occurrences import iter_blocks
from math_ide.pipeline import ingest_structure
from math_ide.renderer.navigation import concept_card, definition_target
from math_ide.schema import Formula, MathDocument

# --- module-level gating ---------------------------------------------------

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(
        os.environ.get("RUN_LLM_TESTS") != "1",
        reason="LLM tests are opt-in: set RUN_LLM_TESTS=1 to run them.",
    ),
    pytest.mark.skipif(
        not os.environ.get("OPENAI_API_KEY"),
        reason="OPENAI_API_KEY not set; cannot call the live API.",
    ),
]

# Ensure the SDK is importable; skip the module cleanly if not.
pytest.importorskip("openai", reason="openai SDK not installed")


# ---------------------------------------------------------------------------
# Local helpers (mirrors of the offline suite, kept self-contained)
# ---------------------------------------------------------------------------


def _convergence_formula(doc: MathDocument) -> Formula:
    return next(
        b
        for b in iter_blocks(doc.blocks)
        if isinstance(b, Formula) and "ε" in b.orig_fallback
    )


def _concept(doc: MathDocument, name: str):
    return next(c for c in doc.concepts if c.name == name)


def _block(doc: MathDocument, *, type_: str, defined_name: str) -> str:
    for b in iter_blocks(doc.blocks):
        if b.type == type_ and getattr(b, "defined_name", None) == defined_name:
            return b.id
    raise AssertionError(f"no {type_} block named {defined_name!r}")


def _eps_occs(doc: MathDocument, conv: Formula) -> list:
    return [
        o
        for o in doc.occurrences
        if o.kind == "formula_symbol"
        and o.block_id == conv.id
        and o.span is not None
        and conv.canonical_content[o.span[0] : o.span[1]] == "ε"
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def llm_resolved_doc(docling_dict: dict) -> MathDocument:
    """Ingest the fixture and resolve it with the live OpenAIResolver.

    The resolver is fault-tolerant: on API/parse failure it returns a partial
    document at ``resolving`` rather than raising, so the fixture never crashes
    the suite — the individual tests assert against whatever state it reached.
    """
    doc = ingest_structure(docling_dict)
    OpenAIResolver().resolve(doc)
    return doc


# ---------------------------------------------------------------------------
# RESOLUTION assertions against the live resolver
# ---------------------------------------------------------------------------


def test_llm_never_overwrites_formal_meaning(
    docling_dict: dict, llm_resolved_doc: MathDocument
) -> None:
    """#19 (LLM): formal meanings are byte-identical to pre-resolution values
    — the authoritative-meaning rule holds for the OpenAI resolver too."""
    pre = ingest_structure(docling_dict)
    formal_before = {
        c.name: c.formal_meaning
        for c in pre.concepts
        if c.formal_meaning is not None
    }
    formal_after = {
        c.name: c.formal_meaning
        for c in llm_resolved_doc.concepts
        if c.name in formal_before
    }
    assert formal_after == formal_before


def test_llm_reaches_ready_or_sane_partial(
    llm_resolved_doc: MathDocument,
) -> None:
    """#19 (LLM): resolution settles at ``ready`` (success) or a usable
    partial ``resolving`` (tolerated failure) — never a crash, never a
    half-state."""
    assert llm_resolved_doc.ingestion_state in {"ready", "resolving"}
    # Stage-1 results survive regardless of the resolver's fate.
    assert llm_resolved_doc.occurrences
    assert any(
        c.seeded_by_block_id is not None for c in llm_resolved_doc.concepts
    )


def test_llm_epsilon_coreference_when_resolution_succeeds(
    llm_resolved_doc: MathDocument,
) -> None:
    """#19 (LLM): when resolution succeeds, the convergence epsilon links to
    the Konvergenz concept and left-click navigates to its block.

    If the live call failed (partial ``resolving``), the coreference assertion
    is skipped — the contract only promises this on success."""
    doc = llm_resolved_doc
    if doc.ingestion_state != "ready":
        pytest.skip("live resolver returned a partial result; nothing to assert")

    konv = _concept(doc, "Konvergenz")
    konv_block = _block(doc, type_="Definition", defined_name="Konvergenz")
    conv = _convergence_formula(doc)
    eps_occs = _eps_occs(doc, conv)
    assert eps_occs

    # The model should corefer epsilon to Konvergenz; assert at least one does.
    linked = [o for o in eps_occs if o.concept_id == konv.id]
    assert linked, "expected the live LLM to corefer epsilon -> Konvergenz"
    assert definition_target(doc, linked[0]) == konv_block


def test_llm_adds_semantic_relations_when_successful(
    llm_resolved_doc: MathDocument,
) -> None:
    """#19 (LLM): a successful run adds origin=='semantic' relations and they
    surface in the Konvergenz concept card's semantic neighbourhood."""
    doc = llm_resolved_doc
    if doc.ingestion_state != "ready":
        pytest.skip("live resolver returned a partial result; nothing to assert")

    semantic = [r for r in doc.relations if r.origin == "semantic"]
    assert semantic, "expected the live LLM to add semantic relations"
    assert all(r.origin == "semantic" for r in semantic)

    konv = _concept(doc, "Konvergenz")
    card = concept_card(doc, konv.id)
    # Structural neighbourhood is always there; semantic appears post-resolution.
    assert card["neighbourhood"]["structural"]
    assert card["neighbourhood"]["semantic"]
