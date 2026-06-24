---
title: Meaning resolution pipeline (async LLM)
labels: ontology, llm
---

## Summary

Async **meaning resolution** stage: LLM assigns `occurrence → concept`, propagates **inferred meaning**, and adds **semantic relations** — without overriding formal meaning.

Blocked by: **#8**.

## Scope

- Job queue or background worker triggered after stage-1 ingestion
- Input: math document blocks, occurrences, seeded concepts, structural relations
- LLM tasks:
  - Coreference: all `f`, `ε`, etc. → canonical concept
  - `inferred_meaning` for symbols without formal blocks
  - Semantic relations: `uses`, `defines`, `generalizes`, `specializes`, `instance_of`
- Rules:
  - **Formal meaning is authoritative** — never overridden
  - Update `resolution_status` on concepts/occurrences: `pending` → `resolved`
- Persist results back into math document / ontology indices
- Configurable LLM provider; prompt + JSON output schema documented

## Acceptance criteria

- [ ] After resolution, `ε` in convergence formula links to concept seeded by Definition 2.1
- [ ] `f`, `X`, `Y` in injectivity formula share concepts consistent with Definition 1.2
- [ ] Formal meaning unchanged after LLM pass
- [ ] Semantic relations marked as inferred (distinct from structural)
- [ ] Pipeline tolerates LLM failure (partial results, retry)

## Out of scope

- IDE concept card UI (#13)
- Cross-document ontology merge
