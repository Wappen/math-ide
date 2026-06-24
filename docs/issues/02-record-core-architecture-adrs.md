---
title: Record core architecture ADRs
labels: docs
---

## Summary

Capture the hard-to-reverse design decisions from the grilling session as short ADRs in `docs/adr/`.

## ADRs to write

1. **Structured re-render over PDF overlay** — the IDE renders from the math document, not PDF pages with hit-target overlays.
2. **Custom math document schema** — Docling is an ingestion adapter; the math document is canonical.
3. **Two-layer ontology (occurrences + concepts) with staged LLM meaning resolution** — formal seeds are authoritative; LLM propagates inferred meaning asynchronously.

Use the format in the domain-modeling ADR template (short paragraph each; optional considered options).

## Acceptance criteria

- [ ] `docs/adr/0001-structured-rerender.md` (or similar numbering)
- [ ] `docs/adr/0002-math-document-schema.md`
- [ ] `docs/adr/0003-occurrence-concept-ontology.md`
- [ ] Each ADR states context, decision, and why in ≤1 paragraph
- [ ] `CONTEXT.md` remains glossary-only (no duplication of ADR content)

## Out of scope

- Implementation
