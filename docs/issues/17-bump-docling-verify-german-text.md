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

## Verification outcome

**Status: INCONCLUSIVE in this environment — live re-conversion was not performed.**

The `docling` lower bound in `requirements-ingest.txt` was bumped from `>=2.0.0`
to `>=2.7.0` (kept as a lower bound, not a hard pin). However, the verification
that this issue requires — re-converting `example.pdf` and inspecting the
exported `text` / `orig` strings — **could not be run** in the offline dev
environment:

- `docling` is **not installed** in the project virtualenv (and per project
  constraints it stays uninstalled so the offline test suite runs without the
  heavy SDK), so no conversion could be executed.
- `example.pdf` is **absent** (it is gitignored), so there was no input PDF to
  convert and inspect.

Because the umlaut quality of the bumped Docling could not be observed here, the
upstream fix is **unverified**. Per this issue's gate ("If verification fails:
note the failure in this issue and proceed with #18"), the inconclusive result
is treated as not-passing, and the deterministic adapter-side fallback (**#18**)
**proceeds**.

### Reconciliation with #18 (defense-in-depth)

These two paths do not conflict. The #18 `normalize_text()` repair targets only
the specific decomposed-diaeresis patterns (`¨ a` → `ä`, etc.) and is a **no-op
on already-correct text**: applied to a string that already contains proper
`ä`/`ö`/`ü`/`ß`, it changes nothing. Therefore, if a later re-conversion on real
hardware with the bumped Docling turns out to fix umlauts upstream, the #18
fallback remains **harmless** — it simply finds no decomposed patterns to
repair. Keeping both is defense-in-depth: the adapter stays robust whether or
not a given PDF / Docling version emits clean umlauts.

### Recommended follow-up

Re-run this verification on **real hardware** with `docling>=2.7.0` installed:

1. Install the ingest extras and obtain `example.pdf`.
2. Re-convert it through the normal Docling pipeline.
3. Inspect both `text` and `orig` on prose nodes and formal-block labels for
   `ä`/`ö`/`ü`/`ß` (e.g. `für`, `Injektivität`, `annähern`) rather than `¨` +
   space + vowel.
4. If umlauts are clean, record the verified version here and note that #18 is
   now redundant-but-harmless; if still decomposed, #18 carries the fix as
   designed.
