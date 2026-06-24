---
title: Detect formal blocks with preamble split
labels: ingestion
---

## Summary

Detect numbered formal environments in Docling text nodes and emit typed blocks (`Definition`, `Theorem`, `Lemma`, …) with optional preamble.

## Context

Docling often merges formal labels into plain `text` nodes. Example from `output.json`:

> *Ein wichtiges Konzept … ist die Injektivität. Definition 1.2 (Injektivität): Eine Abbildung …*

Per `CONTEXT.md`, leading prose becomes `preamble`; the formal label and body become a `Definition` block.

Blocked by: **#3**.

## Scope

- Pattern-match formal labels (v1: German + English):
  - `Definition X.Y (Term):`
  - `Theorem` / `Satz`, `Lemma`, `Corollary` / `Folgerung`, `Proof` / `Beweis`, `Example` / `Beispiel`, `Remark` / `Bemerkung`
- Split Docling text at match boundary; estimate `source_bbox` via char-span subdivision within `prov`
- Emit typed block with `number`, `defined_name`, `body`, optional `preamble`
- Remaining text → `Paragraph`

## Acceptance criteria

- [ ] `Definition 1.1 (Menge)` from example PDF → `Definition` block (no preamble)
- [ ] `Definition 1.2 (Injektivität)` → `Definition` with preamble + body split correctly
- [ ] `Theorem`/`Satz` etc. map to distinct block types (not a shared enum wrapper)
- [ ] Tests cover clean block, preamble-prefixed block, and no-match paragraph

## Out of scope

- Concept seeding (#8)
- LLM-assisted splitting
