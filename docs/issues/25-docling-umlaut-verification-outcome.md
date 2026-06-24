---
title: Record #17 umlaut verification: Docling 2.107.0 still decomposed; #18 is load-bearing
labels: ingestion
---

## Summary

A live conversion of `example.pdf` was finally run with `docling 2.107.0` (well above the **#17** floor of `>=2.7.0`), so **#17**'s "Verification outcome" can move from INCONCLUSIVE to FAIL. Docling still emits decomposed diaeresis, so the upstream bump does **not** fix German umlauts; the adapter `normalize_text` from **#18** is what repairs them. Record the FAIL outcome with the tested version in **#17** and mark **#18** as load-bearing (not redundant) in the issue map.

## Context

The real end-to-end run converts `example.pdf` with `docling 2.107.0` (confirmed installed: `.venv` reports `Version: 2.107.0`), well above the `docling>=2.7.0` floor in `requirements-ingest.txt`. The raw export `docling_enriched.json` still carries the decomposed-diaeresis artifact (a `¨` plus an optional space plus a vowel) in both `text` and `orig` of prose and `section_header` nodes:

- `node[0]` (section_header): `"text": "Testskript: Einf¨ uhrung in die Analysis"`
- `node[6]` (text): `"Ein wichtiges Konzept f¨ ur Abbildungen zwischen Mengen ist die Injektivit¨ at. Definition 1.2 (Injektivit¨ at): Eine Abbildung f : X → Y heißt injektiv , wenn jedem Element des Zielbereichs Y h¨ ochstens ein Element des Definitionsbereichs X zugeordnet wird. Mathematisch ausgedr¨ uckt:"`
- Other affected tokens across the document: `pr¨ azise`, `w¨ ahrend`, `ausdr¨ uckt` (node[4]) and `ann¨ ahern` (node[9]).

All eight cited examples — `Einf¨ uhrung`, `f¨ ur`, `Injektivit¨ at`, `pr¨ azise`, `w¨ ahrend`, `ausdr¨ uckt`, `h¨ ochstens`, `ann¨ ahern` — survive the Docling 2.107.0 conversion, proving the upstream-first plan in **#17** failed at this version.

The repair happens in the adapter, not in Docling. `math_ide/ingest/docling_adapter.py` defines `_DECOMPOSED_DIAERESIS_RE = re.compile("[¨̈] ?([aouAOU])")` and applies `normalize_text` to every `text` and `orig` string read from a node. In `mathdoc_enriched.json` (the MathDocument after ingest + seed_ontology + MockResolver) the same content is clean: the Section `title` is `"Testskript: Einführung in die Analysis"`, the prose reads `für`/`präzise`/`während`/`ausdrückt`/`annähern`, and the Definition's `defined_name` is `"Injektivität"` with `formal_meaning` containing `höchstens`/`ausgedrückt`. So **#18** is the load-bearing fix; without it the formal-block `defined_name` and concept names would slug from `Injektivit¨ at`.

This was masked until now because the synthetic fixture diverges from real Docling output. `tests/fixtures/example_docling.json` ASCII-transliterates the German entirely (`"... die Injektivitaet. Definition 1.2 (Injektivitaet): Eine Abbildung f: X -> Y heisst injektiv ..."`), so it contains no `¨` diaeresis to repair and never exercises `normalize_text`. The fixture therefore cannot confirm or refute **#17**, and the real artifacts above are the first ground truth.

Residual non-umlaut mojibake remains uncovered (out of scope for `normalize_text`, candidate follow-ups):

- German typographic quotes around `für alle` linearize to ASCII apostrophes: `node[4]` shows `steht f¨ ur ' f¨ ur alle'` (the rendered quote bytes are `0x27`). The original `„ … “` quotes cannot be observed directly because `example.pdf` is gitignored; only the ASCII-`'` side is verifiable from the artifacts.
- Blackboard-bold loses to plain Latin in prose: `node[5]` ends `schreiben wir als R .` and `node[10]` has `n ∈ N`, while the matching formula LaTeX uses `\mathbb { N }` (`node[12]`). The prose `ℝ`/`ℕ` flattened to `R`/`N`.
- Inline math is space-separated: `node[13]` is `lim n →∞ a n = L .` rather than a contiguous expression.

The rendered IDE page `math_ide_enriched.html` reflects the clean (repaired) text downstream and has 21 `.occ` anchors with 14 `data-resolvable="false"`, matching the artifact descriptions.

Related: **#17** (upstream-first verification, now resolvable), **#18** (adapter `normalize_text` fallback), **#16** (formula enrichment default, the `--wait` path used here), **#3** (Docling → math-document transformer), **#15** (end-to-end acceptance tests).

## Scope

- Update `docs/issues/17-bump-docling-verify-german-text.md` "Verification outcome": change status from **INCONCLUSIVE** to **FAIL**, recording the tested version `docling 2.107.0` and the surviving tokens (`Einf¨ uhrung`, `f¨ ur`, `Injektivit¨ at`, `h¨ ochstens`, `ann¨ ahern`).
- In `docs/issues/17-*.md`, replace the "could not be run / Docling not installed / example.pdf absent" reasoning with the live result, and note that the **#18** gate ("If verification fails: proceed with #18") is now satisfied by an observed failure, not an inconclusive one.
- In `docs/issues/README.md`, update footnote `[^17]` to FAIL with version `2.107.0`, and change footnote `[^18]` from "no-op / harmless / blocked-by-17" framing to **load-bearing / required** (it actually performs the repair `Injektivit¨ at` → `Injektivität` in the real run via `_DECOMPOSED_DIAERESIS_RE` / `normalize_text` in `math_ide/ingest/docling_adapter.py`).
- Keep `normalize_text` and `_DECOMPOSED_DIAERESIS_RE` scoped to decomposed diaeresis only — do not broaden them.

## Acceptance criteria

- [ ] `docs/issues/17-*.md` records outcome **FAIL** with the verified version `docling 2.107.0` and at least three surviving decomposed tokens copied from `docling_enriched.json` (e.g. `Einf¨ uhrung`, `f¨ ur`, `Injektivit¨ at`).
- [ ] `docs/issues/README.md` footnotes describe **#17** as FAIL (not inconclusive) and **#18** as load-bearing/required (not redundant-but-harmless).
- [ ] The FAIL record cites the real artifact contrast: Docling `orig` `"Testskript: Einf¨ uhrung in die Analysis"` vs MathDocument `title` `"Testskript: Einführung in die Analysis"`, and Docling `Injektivit¨ at` vs Definition `defined_name` `"Injektivität"`.
- [ ] No source change to `_DECOMPOSED_DIAERESIS_RE` or `normalize_text` in `math_ide/ingest/docling_adapter.py` (regex pattern stays `"[¨̈] ?([aouAOU])"`).

## Out of scope

- Broadening `normalize_text` beyond decomposed diaeresis (NFC normalization, UTF-8/Latin-1 mojibake repair).
- Fixing the residual mojibake (typographic `„ … “` quotes flattened to `'`; blackboard-bold `ℝ`/`ℕ` in prose flattened to `R`/`N`; space-separated inline math like `lim n →∞ a n = L`) — track as separate follow-ups if pursued.
- Refreshing `tests/fixtures/example_docling.json` to carry real `¨`-diaeresis input (separate fixture-fidelity work).
