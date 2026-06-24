---
title: Inline math in prose yields no occurrences (most real notation is unclickable)
labels: ingestion, ontology
---

## Summary

On real `example.pdf`, occurrences are only ever minted for formula-labeled nodes (`formula_symbol`), formal-block defined names (`defined_name`), and numbered citations (`citation`). The bulk of the document's notation lives **inline in prose** (`∀`/`∃`, `als R`, `f : X → Y`, `L ∈ R`, `ϵ -Umgebung`, `( a n ) n ∈ N`, `lim n →∞ a n = L`) and produces **zero** occurrences, so it is unclickable and never coreferenced to its concept. Fix direction: scan Paragraph and FormalBlock prose for inline notation and emit occurrences for it, starting with the single identifiers and named sets the symbol scanner already understands.

## Context

The real enriched run produced only 21 occurrences — `by kind: {'defined_name': 3, 'formula_symbol': 18}` (`e2e_enriched.log` line 74), i.e. 18 `formula_symbol` from the two display formulas plus 3 `defined_name`, and **0 citation / 0 inline**. Yet the inline notation is right there in the Docling `text` nodes (`docling_enriched.json`):

- node [4] `label='text'`: `"...Der Allquantor ∀ steht f¨ ur ' f¨ ur alle', w¨ ahrend der Existenzquantor ∃ ausdr¨ uckt..."`
- node [5] `label='text'`: `"...Die Menge der reellen Zahlen schreiben wir als R ."`
- node [6] `label='text'`: `"...Eine Abbildung f : X → Y heißt injektiv ... des Zielbereichs Y h¨ ochstens ein Element des Definitionsbereichs X ..."`
- node [10] `label='text'`: `"...Eine Folge ( a n ) n ∈ N reeller Zahlen heißt konvergent gegen den Grenzwert L ∈ R , wenn in jeder noch so kleinen ϵ -Umgebung von L ..."`
- node [13] `label='text'`: `"Wenn eine Folge gegen L konvergiert, schreiben wir auch lim n →∞ a n = L ."`

`extract_occurrences()` in `math_ide/ontology/occurrences.py` produces exactly three kinds. `formula_symbol` is minted only from `Formula.symbol_index` (`_formula_symbol_occurrences`), `defined_name` only from `FormalBlock.defined_name` (`_defined_name_occurrence`), and `citation` only via `CITATION_RE = \b(keyword)\s+(number)` for numbered cross-refs (`_citation_occurrences`). Prose is scanned **only** for that numbered-citation regex — there is no inline-math token scanner anywhere in the module. So `Paragraph.text` and `FormalBlock.body`/`preamble` contribute occurrences only when they contain `Definition 1.1`-style references (and on this run, none matched in prose, hence 0 citation).

The rendered IDE confirms the consequence. In `math_ide_enriched.html` the `para-4` element wraps the inline `∀`/`∃` with **no `.occ` span at all** (`<p ... id="example#block/para-4-in-der-mathematik-nutzen">In der Mathematik ... Der Allquantor ∀ steht für ... der Existenzquantor ∃ ausdrückt ...</p>`), and `para-13` likewise renders `... lim n →∞ a n = L .` as plain text. The `definition-5` body renders `... schreiben wir als R .` with `R` unwrapped, and the `definition-10` body wraps only the defined name `Konvergenz` while leaving `( a n ) n ∈ N`, `L ∈ R`, and `ϵ -Umgebung von L` as plain prose. The page has 21 `.occ` anchors total (18 `formula_symbol` + 3 `defined_name`), all of which come from the two formulas and the three defined names — none from prose.

This is a **coverage gap**, not a spec violation. The occurrences.py module docstring (line 4) promises "every surface appearance of mathematical notation", but `CONTEXT.md` (line 36) actually scopes an occurrence to exactly three import-time kinds (formula symbol, defined name, numbered citation). Missing inline prose math is therefore consistent with the documented v1 design — but it badly undershoots what a reader needs: most of the real notation is dead text. The synthetic fixture masks this because it diverges from real Docling output: `tests/fixtures/example_docling.json` prose nodes carry essentially no inline math (no `∀`/`∃`, no `f : X → Y`, no `( a n ) n ∈ N`, no `lim n →∞`), and its formula nodes have empty `"text"`, so the suite never exercises inline prose notation. Relates to **#7** (occurrence extraction with dual bboxes) and **#8** (seed concepts and structural relations), and to the `CONTEXT.md` occurrence definition.

## Scope

- Add an inline-math scanner to `math_ide/ontology/occurrences.py` that walks `Paragraph.text` and `FormalBlock.body`/`preamble`, emitting a new occurrence kind for inline notation found in prose, with `source_bbox` computed via `subdivide_bbox` over the host block's bbox (mirroring `_citation_occurrences`) and `render_bbox=None` (filled at layout, #11).
- Phase 1: restrict matches to tokens the existing symbol vocabulary already understands — single identifiers (`f`, `L`, `n`, `a`) and named sets (`R`/`ℝ`, `N`/`ℕ`) — and the standalone quantifiers `∀`/`∃`; do not attempt to parse `f : X → Y`, `( a n ) n ∈ N`, or `lim n →∞ a n = L` as compound expressions yet.
- Wire the new inline occurrences into `extract_occurrences()` alongside the existing `formula_symbol` / `defined_name` / `citation` paths, deterministically and with no LLM.
- Link each inline occurrence to the matching concept so coreference holds: an inline `L` / `f` / `ℝ` in prose must resolve to the same concept as its `formula_symbol` occurrence (cf. the `sym-l-4c`, `sym-f-66` concepts already minted), enabling go-to-definition (#12) and the concept card (#13) from prose.
- Update `CONTEXT.md` (occurrence definition, line 36) and the occurrences.py docstring to name the new inline kind, keeping the two consistent.
- Add a real-output-shaped fixture (or extend `tests/fixtures/example_docling.json`) whose prose nodes carry the inline notation from real nodes [4]/[6]/[10]/[13], so the gap stops being invisible to the suite.

## Acceptance criteria

- [ ] Running the pipeline on the real `example.pdf` conversion yields inline occurrences from prose: `extract_occurrences()` produces at least one occurrence for the inline `L` in node [13] and the inline `R` (ℝ) in node [5], and the `by kind` summary in the e2e log includes a non-zero inline count (no longer only `{'defined_name': 3, 'formula_symbol': 18}`).
- [ ] In `math_ide_enriched.html`, the `para-13` element (`... lim n →∞ a n = L .`) and the `definition-5` body (`... schreiben wir als R .`) contain at least one `.occ` span for their inline notation, where today they have none.
- [ ] An inline prose `L` occurrence resolves to the **same** concept id as the formula `L` occurrence (`example#concept/sym-l-4c`), and inline `f` to `example#concept/sym-f-66`, so go-to-definition / concept card work from prose.
- [ ] A test using real-Docling-shaped prose (inline `∀`/`∃`, `als R`, `L ∈ R`) asserts inline occurrences are emitted; the existing three-kind tests still pass.

## Out of scope

- Parsing arbitrarily complex inline LaTeX or compound expressions (`f : X → Y`, `( a n ) n ∈ N`, `lim n →∞ a n = L`) as structured formulas — Phase 1 covers single identifiers, named sets, and standalone quantifiers only.
- Promoting inline matches into full `Formula` blocks or running formula enrichment on prose spans (**#5**, **#16**).
- New inferred-meaning resolution behavior for inline occurrences beyond reusing the existing concept-linking path (**#9**, **#19**).
- The decomposed-umlaut text quality issue affecting these same prose nodes (`pr¨ azise`, `Injektivit¨ at`) — see **#17** / **#18**.
