---
title: Define math document schema
labels: schema
---

## Summary

Define the canonical **math document** JSON schema: the typed block tree the Math IDE renders from and the ontology indexes into.

## Context

See [`CONTEXT.md`](../../CONTEXT.md). Docling output is an ingestion adapter only. The math document is the source of truth for the rendered view.

## Scope

- JSON Schema (or Pydantic models) for block types:
  - `Section`, `Paragraph`
  - `Definition`, `Theorem`, `Lemma`, `Corollary`, `Proof`, `Example`, `Remark`
  - `Formula`
- Shared fields: `id`, `source_bbox`, optional `children` / tree structure
- `Formula`: `latex`, `symbol_index[]`, `enrichment_status` (`pending` | `ready` | `failed`), `orig_fallback`
- `Definition` (and other formal blocks): `number`, `defined_name`, `body`, optional `preamble`
- Parallel indices (separate top-level sections or companion files):
  - `occurrences[]`
  - `concepts[]`
  - `relations[]` (structural + semantic)
- Document metadata: `document_id`, `source` provenance

## Acceptance criteria

- [ ] Schema validates the structure described in `CONTEXT.md`
- [ ] Example fixture generated from `output.json` / example PDF (even if partial)
- [ ] IDs are document-namespaced; concepts include nullable `canonical_concept_id`
- [ ] README or schema doc explains block types without implementation detail

## Out of scope

- Docling transformation (separate issue)
- Renderer or IDE UI
