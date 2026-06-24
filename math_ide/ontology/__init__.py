"""Ontology package: occurrences, concepts and structural relations.

This is stage-1 *structuring* of a math document, run after ingestion has built
the block tree (and formula symbol indices). It is synchronous, offline and
deterministic — no LLM — and brings a freshly-ingested document to
``ingestion_state="structure_ready"``:

1. :func:`~math_ide.ontology.occurrences.extract_occurrences` materialises the
   occurrences index (formula symbols, defined names, numbered citations) with
   source bboxes and ``render_bbox=None`` (#7).
2. :func:`~math_ide.ontology.concepts.seed_concepts_and_relations` seeds one
   concept per formal-block defined name plus stub concepts per formula symbol,
   wires occurrences to concepts and lays down the deterministic structural
   relations ``seeded_by`` / ``sibling`` / ``co_occurring`` (#8).

Meaning resolution (concept disambiguation, inferred meaning, semantic
relations) is a separate asynchronous stage (#9), exposed here as the
:class:`Resolver` protocol with a deterministic :class:`MockResolver` and the
live :class:`AnthropicResolver` / :class:`OpenAIResolver`. :func:`auto_resolver`
picks one from the environment (Anthropic -> OpenAI -> offline mock).

Public entry point: :func:`seed_ontology`.
"""

from __future__ import annotations

from math_ide.ontology.concepts import seed_concepts_and_relations
from math_ide.ontology.meaning import (
    DEFAULT_OPENAI_MODEL,
    AnthropicResolver,
    MockResolver,
    OpenAIResolver,
    Resolver,
    auto_resolver,
)
from math_ide.ontology.occurrences import extract_occurrences
from math_ide.schema import MathDocument

__all__ = [
    "seed_ontology",
    "extract_occurrences",
    "seed_concepts_and_relations",
    "Resolver",
    "MockResolver",
    "AnthropicResolver",
    "OpenAIResolver",
    "auto_resolver",
    "DEFAULT_OPENAI_MODEL",
]


def seed_ontology(doc: MathDocument) -> MathDocument:
    """Run the full stage-1 ontology pass over ``doc`` (mutates + returns).

    Extracts occurrences then seeds concepts and structural relations, leaving
    ``doc`` at ``ingestion_state="structure_ready"``. Safe to call on a document
    fresh from :func:`math_ide.ingest.build_math_document`.
    """
    extract_occurrences(doc)
    seed_concepts_and_relations(doc)
    return doc
