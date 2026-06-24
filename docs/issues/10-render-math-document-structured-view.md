---
title: Render math document to structured view
labels: renderer
---

## Summary

Build the **rendered document** view: walk the math document block tree and produce an interactive HTML (or equivalent) structured layout.

Blocked by: **#1**, **#7**.

## Scope

- Render block types: `Section`, `Paragraph`, formal blocks (with preamble), `Formula`
- Formula rendering via KaTeX (LaTeX) or degraded `orig_fallback` display
- Formal blocks: visually distinct styling per type (`Definition`, `Theorem`, …)
- Occurrence hit-target placeholders in DOM (data attributes: `occurrence-id`)
- Scroll container suitable for "go to definition" navigation

## Acceptance criteria

- [ ] Example math document renders readably in browser or embedded webview
- [ ] Formulas show KaTeX when `enrichment_status: ready`, fallback otherwise
- [ ] Definitions show preamble + body when present
- [ ] Occurrence anchors exist in DOM for formula symbols and defined names

## Out of scope

- Render bbox measurement (#11)
- Click handlers (#12, #13)
