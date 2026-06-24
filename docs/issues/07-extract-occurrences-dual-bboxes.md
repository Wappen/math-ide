---
title: Extract occurrences and assign dual bboxes
labels: ingestion, ontology
---

## Summary

Create **occurrence** records at import time and assign **source bbox** (PDF) plus a placeholder for **render bbox** (filled at layout time).

## Context

Three occurrence kinds at import (per `CONTEXT.md`):

1. Symbols inside formulas (from symbol index)
2. Defined names in formal block labels — `(Menge)`, `(Konvergenz)`
3. Explicit numbered citations — `Definition 1.1`, `Satz 2.3`

Blocked by: **#4**, **#6**.

## Scope

- `Occurrence` fields: `id`, `kind`, `block_id`, `span`, `source_bbox`, `render_bbox` (nullable), `concept_id` (nullable until resolution)
- Citation detection in `Paragraph` and formal block bodies; deterministic link to cited block
- Defined-name occurrence on formal block `defined_name` with bbox from label span
- Formula symbol occurrences linked to `Formula` block + symbol index offset

## Acceptance criteria

- [ ] Example PDF yields occurrences for `(Menge)`, `(Injektivität)`, `(Konvergenz)`
- [ ] Formula symbols have occurrences with correct `source_bbox` (formula bbox or sub-span estimate)
- [ ] `Definition 1.1` citation occurrence resolves to Definition 1.1 block without LLM
- [ ] `render_bbox` null until layout (#11); `source_bbox` always set when available

## Out of scope

- Concept assignment (#8, #9)
- Render-time bbox (#11)
