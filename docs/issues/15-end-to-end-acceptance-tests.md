---
title: End-to-end acceptance tests (example PDF)
labels: testing
---

## Summary

Acceptance tests that ingest the example analysis PDF and verify the full Math IDE loop: structure → occurrences → resolution → navigation.

Blocked by: **#13**, **#14**.

## Test scenarios (example PDF)

1. **Structure** — three `Definition` blocks; Definition 1.2 has preamble
2. **Occurrences** — defined names, formula symbols, at least one citation if present
3. **Citations** — deterministic resolution without LLM
4. **Resolution** — after LLM (or fixture mock), `ε` links to Konvergenz concept
5. **Navigation** — left click citation → Definition block; left click symbol → definition after resolution
6. **Concept card** — right click shows references + neighbourhood
7. **Dual bboxes** — both `source_bbox` and `render_bbox` populated post-layout

## Scope

- Fixture: committed example PDF (or generate in test setup)
- Mock LLM option for CI (deterministic resolution fixture)
- Optional: Playwright/browser test for render bboxes + clicks

## Acceptance criteria

- [ ] CI runs ingestion + ontology assertions without GPU
- [ ] At least one browser/integration test for click navigation
- [ ] LLM tests skippable via env var but runnable locally
- [ ] Test README documents how to run full vs mocked suite

## Out of scope

- Performance benchmarks
- Multi-document corpus tests
