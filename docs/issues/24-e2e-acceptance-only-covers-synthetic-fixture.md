---
title: Acceptance suite only exercises a synthetic fixture that diverges from example.pdf
labels: testing
---

## Summary

The **#15** end-to-end acceptance suite runs entirely against the hand-authored `tests/fixtures/example_docling.json`, never against a real Docling conversion of `example.pdf`. That fixture diverges from real Docling output, so the green suite masks a live pipeline that produces zero citation occurrences, a different section title, and a different formula-symbol token vocabulary. Add a gated real-conversion E2E test over `example.pdf` and regenerate the offline fixture from a real Docling export so the committed fixture reflects reality.

## Context

`tests/conftest.py` hardwires `FIXTURE = Path(__file__).parent / "fixtures" / "example_docling.json"`, and every acceptance fixture (`docling_dict`, `structure_ready_doc`, `resolved_doc`, `resolved_doc_readonly`) is built from it; `tests/test_acceptance_e2e.py` consumes nothing else. So the acceptance suite never touches a live Docling conversion of `example.pdf`. Each assertion encodes the fixture's idealized input, not the real artifacts:

- **Citation has zero live coverage.** The fixture invents a citation paragraph — `"Nach Definition 1.1 ist eine Menge durch ihre Elemente vollstaendig bestimmt."` (`tests/fixtures/example_docling.json` `#/texts/2`) — that does **not** exist in `example.pdf`. `_the_citation()` asserts `"fixture has a 'Definition 1.1' citation"` and `test_occurrences_citation_definition_1_1_exists` asserts `host.text[start:end] == "Definition 1.1"`, but the real run emits **0 citation occurrences**: `e2e_enriched.log` STEP 3 reports `by kind: {'defined_name': 3, 'formula_symbol': 18}` (21 occurrences total, no `citation`), and `mathdoc_enriched.json` contains zero `"kind": "citation"` occurrences. The whole **#15** CITATIONS scenario (deterministic `definition_target` to the Menge block) has no real coverage.
- **Section title diverges.** `test_structure_…` asserts `s.title == ["1 Mengen und Abbildungen", "2 Folgen und Konvergenz"]`, but real Docling emits `section_header` `'1 Grundbegriffe der Mengenlehre'` and `'2 Folgen und Grenzwerte'` (`docling_enriched.json` nodes `[3]`/`[8]`; `e2e_enriched.log` STEP 2 block tree).
- **Formula-symbol token vocabulary diverges.** `test_occurrences_formula_symbols_cover_expected_token_sets` asserts the tight tokens `{"f", "x₁", "x₂", "X"}` and `{"ε", "a_n", "L", "N"}`. The real converter never produces these: the injectivity formula latex is `\forall x _ { 1 } , x _ { 2 } \in X \colon ...` (spaced `x _ { 1 }`, not `x₁`) and the convergence latex is `\forall \epsilon > 0 \quad \exists N \in \mathbb { N } \ \forall n \geq N \colon | a _ { n } - L | < \epsilon` (`docling_enriched.json` nodes `[7]`/`[12]`). The real symbol index is `['\\epsilon', 'N', 'N', 'n', 'N', 'a', 'n', 'L', '\\epsilon']` (`e2e_enriched.log` STEP 2) — `\epsilon` not `ε`, bare `a`/`n` not `a_n`.
- **Convergence domain diverges.** The fixture's convergence formula uses ℝ (`∃ N ∈ ℝ`), but real Docling emits ℕ: `\exists N \in \mathbb { N }`, orig `∃ N ∈ N` (`docling_enriched.json` `[12]`). `test_navigation_unresolved_symbol_has_no_target` even names `ℝ / x₁ / n` as the pending example, none of which match real tokens.

The rendered page from the real run (`math_ide_enriched.html`) shows `<h2 class="section-title">1 Grundbegriffe der Mengenlehre</h2>` and `data-resolvable="false"` on 14 of 21 `.occ` anchors — consistent with the live pipeline, not the fixture. The suite is green (`276 tests collected`) yet asserts none of these real-world tokens, so it masks a live pipeline that yields no citation occurrences and a different defined-name / formula-symbol vocabulary than every assertion encodes.

This is the meta-issue tying together the per-symptom divergences (the live token, citation, section-title, and domain mismatches tracked alongside it). It relates to **#15** (the acceptance suite) and builds on **#16** (formula enrichment on by default — the `--wait` path that produced these artifacts) and **#17**/**#18** (umlaut handling, visible in `Einf¨ uhrung` → `Einführung`). A real conversion artifact already exists, so the offline fixture can be regenerated rather than re-authored by hand.

## Scope

- Add a gated real-conversion E2E module (e.g. `tests/test_acceptance_e2e_live.py`) that calls the live ingest path on `example.pdf` (via `docling_runner.run_docling` / `ingest_structure`), gated the same way the existing suites gate — an env opt-in like `RUN_DOCLING_TESTS=1` plus a Docling-available check using `pytest.importorskip("docling", ...)` and `pytest.mark.skipif`, mirroring `tests/test_acceptance_llm.py` (`RUN_LLM_TESTS` + key) and `tests/test_ide_browser.py` (`importorskip`).
- Assert the live block tree, occurrences, concepts, and resolution against the **real** artifacts: section titles `'1 Grundbegriffe der Mengenlehre'` / `'2 Folgen und Grenzwerte'`, three `defined_name` occurrences (`Menge`, `Injektivität`, `Konvergenz`), 18 `formula_symbol` occurrences, real latex tokens (`\epsilon`, `a _ { n }`, `x _ { 1 }`, `\mathbb { N }`), and **zero** `citation` occurrences.
- Regenerate `tests/fixtures/example_docling.json` from a real Docling `export_to_dict()` of `example.pdf` so the offline fixture matches live output (real section titles, latex tokens, ℕ domain), and update `tests/test_acceptance_e2e.py` / `tests/conftest.py` assertions and helpers (`_the_citation`, `CONVERGENCE_LATEX`, the `{"ε","a_n","L","N"}` token set) accordingly.
- Resolve the citation scenario explicitly: since `example.pdf` contains no `Definition 1.1` cross-reference, either document that the citation scenario is absent from the real PDF and drop the fabricated `Nach Definition 1.1 …` paragraph, or add a real cross-reference paragraph to the source PDF so the CITATIONS scenario has live coverage.
- Document the synthetic-vs-live relationship in `tests/README.md` (the fixture is a regenerated snapshot of real Docling output, not idealized input).

## Acceptance criteria

- [ ] A gated test converts the real `example.pdf` (skipped when Docling is absent or the env flag is unset) and asserts on the real block tree: section titles `'1 Grundbegriffe der Mengenlehre'` and `'2 Folgen und Grenzwerte'`, defined names `['Menge', 'Injektivität', 'Konvergenz']`.
- [ ] The same gated test asserts `21` occurrences with `by kind == {'defined_name': 3, 'formula_symbol': 18}` and **no** `citation` occurrence, matching `e2e_enriched.log` STEP 3.
- [ ] The gated test asserts real formula tokens — convergence symbol index includes `\epsilon` (not `ε`), bare `a`/`n` (not `a_n`), and the domain is `\mathbb { N }` (ℕ, not ℝ); injectivity latex contains `x _ { 1 }`.
- [ ] After MockResolver, the gated test asserts go-to-definition matches the real run (e.g. `N`/`L` → `definition-…-konvergenz`, `\epsilon` → `None`), per `e2e_enriched.log` STEP 4.
- [ ] `tests/fixtures/example_docling.json` is regenerated from a real Docling export; the existing offline acceptance assertions are updated to the real tokens and either lose or correctly model the citation scenario; the full suite passes offline without Docling installed.

## Out of scope

- A multi-document corpus or additional sample PDFs beyond `example.pdf`.
- Changing the ingest, occurrence-extraction, or resolution logic itself (this issue only fixes test coverage and the fixture; per-symptom behavior fixes are tracked separately).
- Running the live Docling conversion inside the default offline CI lane (it stays opt-in / gated).
