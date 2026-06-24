"""Shared pytest fixtures + marker registration for the Math IDE suite.

The acceptance suites (``test_acceptance_e2e.py`` / ``test_acceptance_llm.py``)
drive the *public* pipeline API against the canonical synthetic Docling-JSON
fixture (``fixtures/example_docling.json``). That fixture is the committed,
offline stand-in for the example analysis PDF: ingestion consumes a
Docling-style ``export_to_dict()`` mapping, so a hand-authored JSON dict
exercises exactly the same code path a live ``docling`` conversion would feed
in — minus the heavy/GPU dependency. See ``tests/README.md`` for the rationale.

Fixtures here are deliberately thin wrappers around the public entry points
(:func:`math_ide.pipeline.ingest_structure` / :func:`math_ide.pipeline.run_full`)
so cross-test helpers never leak into the library modules. Mutating fixtures are
function-scoped; read-only snapshots are session-scoped for speed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from math_ide.ontology import MockResolver
from math_ide.pipeline import ingest_structure, run_full
from math_ide.schema import MathDocument

FIXTURE = Path(__file__).parent / "fixtures" / "example_docling.json"


# The custom markers ``llm`` and ``browser`` are registered in ``pytest.ini``
# (the single, canonical place) so ``--strict-markers`` never warns. The browser
# test (``test_ide_browser.py``) currently self-skips via ``importorskip`` and
# does not yet carry the marker; the marker is reserved for it / future tagging.


# ---------------------------------------------------------------------------
# Raw Docling dict
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def docling_dict() -> dict:
    """The canonical synthetic Docling-JSON fixture, parsed once per session.

    Read-only: tests must not mutate the returned dict (it is shared). Pass it to
    :func:`math_ide.pipeline.ingest_structure`, which re-parses it into fresh
    blocks every call, so document-level mutation never leaks between tests.
    """
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Stage-1 (structure_ready) documents
# ---------------------------------------------------------------------------


@pytest.fixture()
def structure_ready_doc(docling_dict: dict) -> MathDocument:
    """A fresh stage-1 document (``structure_ready``), per test.

    Occurrences + seeded concepts + deterministic structural relations exist;
    no resolver has run. Function-scoped because callers mutate it (resolve,
    upgrade formulas, ...).
    """
    return ingest_structure(docling_dict)


# ---------------------------------------------------------------------------
# Stage-2 (ready) documents — resolved with the deterministic MockResolver
# ---------------------------------------------------------------------------


def _build_resolved(docling_dict: dict) -> MathDocument:
    """Ingest -> seed -> MockResolver, returning a ``ready`` document."""
    doc = ingest_structure(docling_dict)
    run_full(doc, resolver=MockResolver(), wait=True)
    return doc


@pytest.fixture(scope="session")
def resolved_doc_readonly(docling_dict: dict) -> MathDocument:
    """A session-scoped, fully resolved document for read-only assertions.

    Built once (ingest + seed + MockResolver) and shared across read-only tests
    for speed. Tests that mutate the document must use :func:`resolved_doc`
    instead — mutating this shared instance would bleed into other tests.
    """
    return _build_resolved(docling_dict)


@pytest.fixture()
def resolved_doc(docling_dict: dict) -> MathDocument:
    """A fresh, fully resolved document per test (safe to mutate)."""
    return _build_resolved(docling_dict)
