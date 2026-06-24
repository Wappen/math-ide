---
title: Staged ingestion orchestration
labels: ingestion
---

## Summary

Orchestrate **staged ingestion**: stage 1 (structure, occurrences, concept seeds) available immediately; stage 2 (meaning resolution, formula enrichment upgrade) runs asynchronously.

Blocked by: **#8**, **#9**.

## Scope

- Pipeline state machine: `ingesting` → `structure_ready` → `resolving` → `ready`
- IDE can open document at `structure_ready` (partial ontology)
- Events / polling for:
  - Formula enrichment completion (#5)
  - Meaning resolution progress (#9)
- Re-entrant updates: math document version or etag; renderer refreshes affected occurrences/concepts
- CLI: `ingest` returns fast; `--wait` blocks until fully ready

## Acceptance criteria

- [ ] Example PDF openable in IDE before LLM finishes
- [ ] Citations and formal-block navigation work at `structure_ready`
- [ ] Concept card and symbol navigation enrich as resolution completes
- [ ] Formula render upgrades from fallback to KaTeX without full re-ingest
- [ ] Documented state transitions in README or `CONTEXT.md` companion doc

## Out of scope

- Distributed job queue (single-process worker OK for v1)
