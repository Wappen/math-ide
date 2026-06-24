---
title: 'Left click: go to definition'
labels: ide
---

## Summary

Implement **go to definition** (left click): navigate to the best available definition target with graceful degradation while meaning resolution is pending.

Blocked by: **#8**, **#11**.

## Behaviour (from `CONTEXT.md`)

| Click target | Action |
| --- | --- |
| Citation occurrence | Navigate to cited formal block (immediate) |
| Concept with formal block | Navigate to formal block |
| Otherwise | Navigate to defined name → LLM defining occurrence |
| Unresolved | Disabled / "resolving…" until target exists |

## Scope

- Click handler on occurrence hit-targets
- Scroll + highlight target block or defining occurrence
- Priority: formal block → defined name → defining occurrence
- Visual feedback: highlight ring on target

## Acceptance criteria

- [ ] Left-click `Definition 1.1` citation jumps to Definition 1.1 block
- [ ] Left-click `(Konvergenz)` highlights Definition 2.1
- [ ] Left-click `ε` navigates after meaning resolution completes
- [ ] Unresolved symbols show disabled state before resolution
- [ ] Keyboard-accessible alternative (e.g. Enter on focused occurrence)

## Out of scope

- Concept card (#13)
