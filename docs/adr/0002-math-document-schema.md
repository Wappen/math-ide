# 0002 — Custom math document schema with Docling as ingestion adapter

Status: Accepted

## Context

Ingesting a mathematical PDF requires a document model that the renderer, the ontology, and meaning resolution can all build on. Docling produces a usable structural conversion (texts, formulas, provenance), but its shape is conversion-tool-centric and carries no notion of formal mathematical environments, an occurrence/concept index, or staged enrichment state. We need to decide whether Docling's output is the working representation everything reads, or whether it is merely one input to a representation we own.

## Decision

We define a custom, project-owned *math document* schema (Pydantic v2, in `math_ide/schema.py`) as the single canonical representation. It is a tree of typed blocks — with distinct classes per formal environment (Definition, Theorem, Lemma, Corollary, Proof, Example, Remark) rather than one `FormalBlock` carrying a kind enum — alongside Section, Paragraph, and Formula blocks plus occurrence, concept, and relation indices. Docling is treated strictly as an *ingestion adapter*: `ingest/docling_adapter.py` consumes a Docling-style JSON dict and maps it into the math document; nothing downstream reads Docling output directly.

## Why

A canonical schema we own lets us model what the domain needs — formal block types, preamble splitting, formula enrichment status, the occurrence/concept ontology, document-namespaced IDs — none of which Docling expresses, and it keeps the schema the single source of truth that every other module imports rather than redefines. Isolating Docling behind a thin adapter (with its live model run lazily imported and never exercised in tests) makes ingestion offline and deterministic and lets us swap or supplement the converter later without touching the renderer, ontology, or pipeline.

## Considered options

- **Treat Docling output as the canonical model** — rejected: ties the whole system to a conversion tool's schema, has no place for formal environments or the ontology, and makes the heavy/optional dependency load-bearing everywhere.
- **Custom math document schema with Docling as one adapter** — chosen.
