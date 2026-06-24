---
title: Build Docling → math document block transformer
labels: ingestion
---

## Summary

Refactor the current Docling CLI into an ingestion adapter that produces the math document block tree (stage 1, synchronous).

## Context

`pdf_to_docling.py` exports Docling markdown/JSON/LaTeX directly. The pipeline should instead emit (or additionally emit) a math document.

Blocked by: **#1** (schema).

## Scope

- Map Docling `section_header` → `Section`
- Map plain `text` → `Paragraph` (formal-block splitting is a separate issue)
- Attach `source_bbox` and `page_no` from Docling `prov`
- Preserve document provenance (`origin`, `binary_hash`, filename)
- CLI flag or subcommand: e.g. `python -m math_ide ingest example.pdf -o math-doc.json`

## Acceptance criteria

- [ ] Example PDF produces a math document with `Section`, `Paragraph`, and raw `Formula` stubs
- [ ] Source bboxes match Docling `prov` for mapped blocks
- [ ] Existing Docling export paths still work or are clearly superseded in README
- [ ] Unit tests for bbox mapping and section detection

## Out of scope

- Formal block detection (#4)
- Formula enrichment (#5)
- Occurrences / ontology
