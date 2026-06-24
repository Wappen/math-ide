---
title: 'Right click: concept card with neighbourhood'
labels: ide
---

## Summary

Implement **show references** (right click): open a side panel **concept card** with meanings, status, references, and related concepts.

Blocked by: **#9**, **#12**.

## Concept card contents

1. Concept name + `resolution_status`
2. **Formal meaning** (if any)
3. **Inferred meaning** (if any)
4. **Defining occurrence** (clickable → navigate)
5. **References** — all non-defining occurrences (clickable)
6. **Neighbourhood** — related concepts:
   - Structural (`seeded_by`, `sibling`, `co_occurring`) — immediate
   - Semantic (`uses`, `defines`, `generalizes`, `specializes`, `instance_of`) — after LLM, labelled *inferred*

## Scope

- Right-click (context menu) on occurrence hit-targets
- Side panel component; clicking reference navigates in document
- Distinguish structural vs inferred relations visually

## Acceptance criteria

- [ ] Right-click `ε` (after resolution) shows formal meaning from Konvergenz + reference list
- [ ] Structural siblings shown before LLM completes; semantic edges appear after
- [ ] Panel updates when meaning resolution finishes (live or on refresh)
- [ ] Right-click on unresolved symbol shows status + partial structural data

## Out of scope

- Cross-document search
