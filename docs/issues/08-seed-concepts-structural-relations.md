---
title: Seed concepts and structural relations
labels: ontology
---

## Summary

Seed **concepts** from formal blocks at import time and wire deterministic **structural relations**.

Blocked by: **#7**.

## Scope

### Concept seeding

- One concept per `defined_name` in formal blocks (e.g. `Menge`, `Injektivität`, `Konvergenz`)
- Document-namespaced IDs: `{document_id}#{slug}`
- Nullable `canonical_concept_id` (unused in v1, reserved for corpus merge)
- `formal_meaning` from formal block body
- Defining occurrence → defined name occurrence
- Formula-only symbols: concept created stub with `resolution_status: pending` (meaning resolution in #9)

### Structural relations (deterministic)

- `seeded_by` — concept → formal block
- `sibling` — concepts seeded by same formal block
- `co_occurring` — concepts with occurrences in same formula

## Acceptance criteria

- [ ] Example PDF ontology contains concepts for all three definitions
- [ ] Defining occurrences linked; later symbol occurrences start as `pending`
- [ ] Structural relations present without LLM
- [ ] Citation occurrences link to cited block's seeded concept(s)
- [ ] Unit tests for ID namespacing and sibling/co_occurring edges

## Out of scope

- LLM meaning resolution (#9)
- Semantic relations
