---
title: Adapter normalize decomposed umlauts (fallback)
labels: ingestion
---

## Summary

If **#17** verification fails, add a minimal `normalize_text()` in the Docling adapter that repairs decomposed diaeresis patterns in `text` and `orig` strings before building math-document blocks.

## Context

**#17** tries an upstream Docling fix first. If `example.pdf` still exports `¨ a` / `¨ o` / `¨ u` instead of `ä` / `ö` / `ü` after the version bump, the adapter seam (ADR 0002) is the fallback: deterministic, testable, and scoped to the known artifact.

**Do not implement this issue unless #17 verification fails.**

## Scope

- Add `normalize_text(s: str) -> str` (location: `docling_adapter` or a small sibling module)
- Apply it to every `text` and `orig` string read from Docling nodes in the adapter
- **Minimal patterns only** — no NFC, no general mojibake repair:
  - `¨a` → `ä`, `¨ o` → `ö`, `¨ u` → `ü` (and the `¨o` / `¨u` variants without space)
  - Same for uppercase if observed in corpus
- Unit tests with the corrupt strings from `output.json` / `example-math.json`
- Optionally refresh `tests/fixtures/example_docling.json` if the fixture should carry real umlauts for formal-block detection tests

## Acceptance criteria

- [ ] **#17** documented as failed before merge (or issue references the failing Docling version)
- [ ] `f¨ ur` → `für`, `Injektivit¨ at` → `Injektivität`, `ann¨ ahern` → `annähern` in adapter output
- [ ] Formal-block detection and concept `defined_name` slugs use corrected text (e.g. `Injektivität`, not `Injektivit¨ at`)
- [ ] Tests do not broaden normalization beyond the decomposed-diaeresis patterns above

## Out of scope

- Unicode NFC normalization
- UTF-8 / Latin-1 mojibake repair (`Ã¼` → `ü`, etc.)
- Unconditional normalization when **#17** passes (this issue is gated on upstream failure)
