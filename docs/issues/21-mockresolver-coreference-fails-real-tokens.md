---
title: Offline MockResolver coreference no-ops on real example.pdf (epsilon/umlaut/subscript)
labels: ontology, llm
---

## Summary

On the default `--wait` path with no API key, `auto` (**#19**) falls back to `MockResolver`, whose `_COREFERENCE` table keys on tokens that never occur in real Docling output. The convergence `\epsilon`, the injectivity symbols, and `a_n` all stay `resolution_status="pending"`, so go-to-definition is dead for them and the **#15** acceptance scenario "after the LLM/mock, `ε` links to Konvergenz concept" fails on `example.pdf`. Either make `MockResolver` normalization-aware (reuse `pipeline.normalize_token`) or re-scope it as fixture-only and have `auto` warn that real coreference needs a live LLM.

## Context

This is the real end-to-end run on `example.pdf` (docling 2.107.0, formula enrichment ON — the **#16** default `--wait` path), captured in `scratchpad/e2e_enriched.log`, `mathdoc_enriched.json`, and `math_ide_enriched.html`.

`MockResolver._COREFERENCE` (in `math_ide/ontology/meaning.py:314`) is keyed by the literal strings `"Konvergenz"` / `"Injektivitaet"` and per-symbol tokens `"ε"`, `"a_n"`, `"L"`, `"N"`, `"f"`, `"X"`, `"Y"`. `build_delta()` looks up each *defining-concept* key via `concept_by_name.get(concept_name)`, and each *symbol* key via `_formula_symbol_occurrences_by_token(...)`. None of these match what the pipeline actually produced:

- **Injektivität block is skipped whole.** The repaired concept name (after **#18**) is `Injektivität` (umlaut), so `concept_by_name.get("Injektivitaet")` returns `None` and the entire `f`/`X`/`Y` branch is `continue`d before any per-symbol lookup. `mathdoc_enriched.json` keeps concepts `x`, `X`, `f` at `status=pending`; STEP 4 of `e2e_enriched.log` shows every `'x'`/`'X'`/`'f'` symbol `-> definition_target=None`.
- **Epsilon never matches.** The `_COREFERENCE` symbol key is the single unicode char `"ε"` (U+03B5), but the seeded concept name and occurrence token is the literal LaTeX string `\epsilon` (Docling emitted `'\\epsilon'` in the formula `latex`; its `orig` fallback is `ϵ`, U+03F5 — a third spelling). The log shows both `symbol '\epsilon' -> definition_target=None`, and the `\epsilon` concept stays `status=pending`.
- **Subscript mangling.** The `_COREFERENCE` key is `"a_n"`, but the real symbol extraction split `| a _ { n } - L |` into the tokens `'a'` and `'n'` (see the Formula `symbols=['\\epsilon', 'N', 'N', 'n', 'N', 'a', 'n', 'L', '\\epsilon']` line). So `'a'` and both `'n'` occurrences resolve to `None`.

The only links that survive are `'N'` and `'L'` to `definition-10-konvergenz`. The `'N'` links are partly spurious: the orig formula `∀ ϵ > 0 ∃ N ∈ N ...` collapses the index threshold `N` and the set `ℕ` to the same token `'N'` (this conflation is the subject of the blocker below), and all three `'N'` occurrences link to Konvergenz.

Net effect in `math_ide_enriched.html`: 21 `class="occ"` anchors, **14 `data-resolvable="false"`**, **0 `data-resolvable="true"`** (the 2 extra raw matches are `class="occ-fallback"`). So **#15** acceptance criterion 4 ("after the LLM (or fixture mock), `ε` links to Konvergenz concept") fails on the real PDF.

The synthetic fixture `tests/fixtures/example_docling.json` masks this: it carries the ASCII/unicode spellings (`Injektivitaet`, `ε`, `a_n`) that the table was authored against, so the test suite is green while the real Docling export diverges. The fix this issue could reuse already exists — `normalize_token()` in `math_ide/pipeline.py:171` folds `\epsilon`/`ϵ`/`ε -> ε`, `\mathbb{R}`/`ℝ`/`R -> R`, and subscript spellings onto one key — but `MockResolver` does not call it.

This issue **is blocked by #20** (the `ℕ`-set vs `N`-threshold token conflation); the `'N' -> Konvergenz` spuriousness cannot be cleanly fixed until #20 distinguishes the two occurrences.

Relates to **#9** (meaning-resolution pipeline), **#18** (umlaut repair that changed the defined name), **#19** (`auto` -> mock fallback).

## Scope

- Decide between (a) normalization-aware mock or (b) fixture-only mock; record the decision in `docs/ontology.md`.
- If (a): in `MockResolver.build_delta` (`math_ide/ontology/meaning.py:333`), match defining-concept keys and per-symbol keys through `pipeline.normalize_token` (and a small case/umlaut fold for concept names, e.g. `Injektivität`/`Injektivitaet`), keying `_index_concepts_by_name` and `_formula_symbol_occurrences_by_token` by normalized form. Replace the `"a_n"` key with whatever `normalize_token` produces for the real split tokens.
- If (b): mark `MockResolver` fixture-only in its docstring and have `resolve_auto_resolver()` (**#19**) emit a stderr warning when it falls back to mock on a live PDF (no real coreference).
- Do not touch the `'N'` -> Konvergenz spuriousness here; defer the `ℕ`/`N` split to **#20**.

## Acceptance criteria

- [ ] On the real `example.pdf` default `--wait` run, both `\epsilon` occurrences (`sym-0-epsilon`, `sym-8-epsilon`) become `data-resolvable="true"` and link to the Konvergenz concept; the `\epsilon` concept's `resolution_status` is `resolved` — OR a documented, tested decision that the mock does not do this and `auto` warns instead.
- [ ] Injectivity symbols `f`/`X`/`x_1`/`x_2` link to the `Injektivität` concept (Definition 1.2), or the same documented-decision escape hatch.
- [ ] A regression test asserts against the real Docling spellings (`\epsilon`, `Injektivität`, split `a`/`n`), not only `tests/fixtures/example_docling.json`.
- [ ] `math_ide_enriched.html` for the enriched run no longer reports `data-resolvable="true": 0` (under option (a)).

## Out of scope

- Splitting the `ℕ` set token from the `N` index threshold — that is **#20** (blocker).
- Changing live-LLM prompt/JSON schema or the `OpenAIResolver`/`AnthropicResolver` classes (**#9**, **#19**).
- Symbol-extraction changes that would keep `a_n` as one token (separate ingestion concern in `math_ide/ingest/symbols.py`).
