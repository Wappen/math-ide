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

**Status: FAIL — verified live with `docling 2.107.0`; decomposed diaeresis persists.**

The `docling` lower bound in `requirements-ingest.txt` was bumped from `>=2.0.0`
to `>=2.7.0` (kept as a lower bound, not a hard pin). The verification this issue
requires — re-converting `example.pdf` and inspecting the exported `text` /
`orig` strings — was **run live** with `docling 2.107.0` installed in `.venv`
(well above the `>=2.7.0` floor), and the upstream fix **failed**:

- Docling **still emits decomposed diaeresis** (`¨` plus an optional space plus a
  vowel) in both `text` and `orig`. The following tokens survive the 2.107.0
  conversion in the raw export: `Einf¨ uhrung`, `f¨ ur`, `Injektivit¨ at`,
  `pr¨ azise`, `w¨ ahrend`, `ausdr¨ uckt`, `h¨ ochstens`, `ann¨ ahern`.
- The adapter `normalize_text` (**#18**) repairs them downstream: the resulting
  MathDocument shows `Einführung`, `für`, `Injektivität`, `präzise`, `während`,
  `ausdrückt`, `höchstens`, `annähern`. Concretely, the Docling `orig`
  `"Testskript: Einf¨ uhrung in die Analysis"` becomes the MathDocument `title`
  `"Testskript: Einführung in die Analysis"`, and Docling `Injektivit¨ at`
  becomes the Definition `defined_name` `"Injektivität"`.

Because the bumped Docling still produces decomposed umlauts, the upstream fix is
**confirmed broken at 2.107.0**. This issue's gate ("If verification fails: note
the failure in this issue and proceed with #18") is now satisfied by an
**observed failure**, not an inconclusive result, so the deterministic
adapter-side repair (**#18**) **proceeds and carries the fix**.

### Reconciliation with #18 (confirmed load-bearing)

These two paths do not conflict, and the live run confirms which one does the
work. The #18 `normalize_text()` repair targets only the specific
decomposed-diaeresis patterns (`¨ a` → `ä`, etc.) and is a no-op on
already-correct text. With Docling 2.107.0 still emitting decomposed umlauts,
**#18 is load-bearing**: without it the formal-block `defined_name` and concept
names would slug from `Injektivit¨ at` rather than `Injektivität`. The repair is
also self-limiting — if a future Docling version ever emits clean umlauts
upstream, #18 finds no decomposed patterns and changes nothing, so keeping both
stays safe. As verified here, the adapter fix is required, not redundant.

### Recommended follow-up

The live verification has been performed (`docling 2.107.0`, `example.pdf`); the
FAIL outcome is recorded above. The remaining follow-ups are tracked separately:

1. Re-check on future Docling versions if/when an upstream umlaut fix lands; if
   umlauts ever become clean upstream, #18 becomes redundant-but-harmless and
   this section can be revisited.
2. Residual non-umlaut mojibake (typographic quotes flattened to `'`,
   blackboard-bold `ℝ`/`ℕ` flattened to `R`/`N`, space-separated inline math) is
   out of scope for `normalize_text` — see **#25** for the full live-run record.
