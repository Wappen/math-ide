---
title: Formula blocks with LaTeX enrichment and orig fallback
labels: ingestion
---

## Summary

Populate `Formula` blocks with LaTeX when Docling formula enrichment succeeds; fall back to linearized `orig` text immediately; upgrade in place when enrichment completes.

## Context

Without `--formula`, Docling formula nodes have empty `text` but useful `orig` (e.g. `∀ x₁, x₂ ∈ X : …`). Per `CONTEXT.md`, occurrences should be extractable before LaTeX is ready.

Blocked by: **#3**.

## Scope

- Enable Docling `do_formula_enrichment` in ingestion path
- `Formula` block fields:
  - `enrichment_status`: `pending` → `ready` | `failed`
  - `latex` when ready
  - `orig_fallback` always preserved from Docling `orig`
- Async upgrade path: when LaTeX arrives, update block and re-trigger symbol index refresh (#6)
- Renderer hint: show degraded linearized math until `ready`

## Acceptance criteria

- [ ] Example PDF formulas produce `Formula` blocks with `orig_fallback` immediately
- [ ] With formula enrichment enabled, blocks upgrade to `ready` with LaTeX
- [ ] Failed enrichment keeps `orig_fallback` and `status: failed` without losing `source_bbox`
- [ ] Tests for pending → ready upgrade and failed state

## Out of scope

- Symbol index extraction (#6)
- KaTeX rendering (#10)
