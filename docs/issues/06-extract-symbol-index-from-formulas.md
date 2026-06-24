---
title: Extract symbol index from formula content
labels: ingestion
---

## Summary

Build a symbol index for each `Formula` block: identifier spans within LaTeX (or `orig_fallback`) used to create occurrences and place render bboxes.

Blocked by: **#5**.

## Scope

- Parse LaTeX (or linearized `orig`) for mathematical identifiers: variables, function names, constants (`ε`, `f`, `a_n`, …)
- Emit `symbol_index[]`: `{ token, start, end, kind }` offsets into canonical content string
- Re-run index when formula upgrades from fallback → LaTeX
- Skip operators-only tokens where appropriate (`∀`, `∈`, `→`) per project rules documented in code

## Acceptance criteria

- [ ] Injectivity formula indexes `f`, `x_1`, `x_2`, `X` (or equivalent)
- [ ] Convergence formula indexes `ε`, `a_n`, `L`, `N`, `R`
- [ ] Index updates after LaTeX enrichment without changing occurrence IDs (or documents migration)
- [ ] Unit tests on LaTeX and orig_fallback inputs

## Out of scope

- Occurrence records (#7)
- LLM meaning resolution
