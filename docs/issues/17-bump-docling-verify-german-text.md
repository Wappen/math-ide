---
title: Bump Docling and verify German umlaut text quality
labels: ingestion
---

## Summary

Upgrade the Docling dependency and re-convert `example.pdf`. Verify that `text` and `orig` strings in the exported JSON contain proper German umlauts (`ä`, `ö`, `ü`) rather than decomposed diaeresis artifacts (`¨ a`, `¨ u`, …).

## Context

The example corpus shows corrupted German text at the **Docling output** stage — before the math-document adapter runs. Docling emits decomposed diaeresis plus space plus vowel (e.g. `f¨ ur` instead of `für`, `Injektivit¨ at` instead of `Injektivität`) in both `text` and `orig` on affected nodes. That corrupts formal-block labels, concept names, and all rendered prose downstream.

**Architectural decision:** fix upstream first (Docling version / conversion quality). Do **not** add adapter-side text normalization unless this issue's verification fails — see **#18**.

`PdfPipelineOptions` in our code only exposes `do_ocr` and `do_formula_enrichment`; there is no encoding knob today. The first lever is a Docling version bump and re-conversion.

Related: **#3**, **#4**.

## Scope

- Bump `docling` lower bound in `requirements-ingest.txt` to a version that improves text extraction (pin after testing)
- Re-run live conversion on `example.pdf` (and/or commit an updated reference Docling JSON export if the project maintains one)
- Document the verified Docling version and any conversion flags used
- Record verification outcome: pass (umlauts correct) or fail (still decomposed — unblocks **#18**)

## Acceptance criteria

- [ ] `requirements-ingest.txt` updated to a tested Docling version
- [ ] Re-converted `example.pdf` JSON inspected: prose and formal labels contain `ä`/`ö`/`ü`/`ß`, not `¨` + space + vowel
- [ ] If verification **passes**: close **#18** as not needed (or mark **#18** blocked/cancelled in the issue map)
- [ ] If verification **fails**: note the failure in this issue and proceed with **#18**

## Out of scope

- Adapter-side `normalize_text()` (**#18** — only if this issue fails)
- Enabling OCR by default (**#16** covers formula default separately; OCR remains opt-in)
- Source PDF re-export / font-embedding documentation (acceptable fallback if neither bump nor **#18** fully fixes a given PDF)
