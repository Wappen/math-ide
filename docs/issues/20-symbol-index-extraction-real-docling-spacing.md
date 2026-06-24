---
title: Symbol index extraction breaks on Docling's spaced LaTeX/linearized output
labels: ingestion
---

## Summary

`extract_symbol_index` (`math_ide/ingest/symbols.py`) assumes *tight* formula tokens (`x_1`, `a_n`, `\mathbb{R}`, unicode subscript digits, `ε` U+03B5). Live Docling 2.107.0 emits *spaced* enriched LaTeX (`x _ { 1 }`, `a _ { n }`, `\mathbb { N }`) and spaced linearized `orig` (`x 1`, `a n`), plus the lunate epsilon `ϵ` U+03F5. The fix is to make the scanner tolerant of whitespace around `_`, `{`, `}` so subscripts stay whole and `\mathbb { N }` is recognized as a set, and to treat the `GREEK ... SYMBOL` epsilon variant as a Greek variable.

## Context

On the real `example.pdf` E2E run with formula enrichment on (the default `--wait` path), the canonical string of each formula block is the enriched `latex` (`status=ready`), and Docling spaces every token. From STEP 2 of `e2e_enriched.log`:

```
Formula  status=ready latex='\forall x _ { 1 } , x _ { 2 } \in X \colon ( f ( x _ { 1 } ) = f ( x _ { 2 } ) \implies x _ { 1 } = x _ { 2 } )' orig='∀ x 1 , x 2 ∈ X : ( f ( x 1 ) = f ( x 2 ) = ⇒ x 1 = x 2 )' symbols=['x', 'x', 'X', 'f', 'x', 'f', 'x', 'x', 'x']
Formula  status=ready latex='\forall \epsilon > 0 \quad \exists N \in \mathbb { N } \ \forall n \geq N \colon | a _ { n } - L | < \epsilon' orig='∀ ϵ > 0 ∃ N ∈ N ∀ n ≥ N : | a n -L | < ϵ' symbols=['\epsilon', 'N', 'N', 'n', 'N', 'a', 'n', 'L', '\epsilon']
```

Four concrete defects, all reproduced by re-running `extract_symbol_index` on these exact strings:

1. **Subscripts are lost.** `_consume_unicode_subscript` only absorbs a subscript when `content[j] == "_"` is the *very next* character after the letter (no space allowed). In `x _ { 1 }` a space sits between `x` and `_`, so the six subscripted `x`'s all collapse to a bare `x`. In STEP 3 they all map to one concept `example#concept/sym-x-78`, so the formula symbol `x_1` and `x_2` are indistinguishable as occurrences — concept identity is corrupted.

2. **`a _ { n }` splits into two tokens.** The convergence formula yields `symbols=[..., 'a', 'n', ...]`: the variable `a` and the index `n` are emitted as separate formula symbols instead of one `a_n` token.

3. **`\mathbb { N }` becomes a bare `N` with the wrong kind.** The named-set branch matches `re.match(r"\\[A-Za-z]+\{([^}]*)\}", ...)`, which requires `\mathbb` to be immediately followed by `{` with no space. The spaced `\mathbb { N }` fails that regex, so `\mathbb` is dropped as an unknown control word and `N` is later emitted as a `variable`. The set ℕ is misclassified both in token (`N` instead of `\mathbb { N }`) and in `kind` (`variable` instead of `set`).

4. **The lunate epsilon `ϵ` U+03F5 is dropped on the `orig` path.** `_is_unicode_greek` requires the unicode name to contain both `GREEK` and `LETTER`. `unicodedata.name('ϵ')` is `GREEK LUNATE EPSILON SYMBOL` — it has `GREEK` but not `LETTER`, so the check returns `False`. Re-running on the fallback `orig` string `∀ ϵ > 0 ∃ N ∈ N ∀ n ≥ N : | a n -L | < ϵ` yields `['N','N','n','N','a','n','L']` with **no** epsilon token at all. (On the live run the canonical string is the `latex`, where `\epsilon` is matched fine; this defect bites whenever a formula stays `orig_fallback`, e.g. the `--no-formula` path of **#16**.)

5. **`f (` is classified `variable`, not `function`.** The function check is `content[end] == "("` immediately after the letter. With Docling's `f (` (space before paren) `f` is tagged `variable`. The docstring's intent ("`f` in `f(x_1)` is a function") is not met on real output.

The synthetic fixture the test suite uses, `tests/fixtures/example_docling.json`, masks all of this because it diverges from real Docling output: its formula nodes carry tight unicode `orig` (`∀ x₁, x₂ ∈ X : f(x₁) = f(x₂) ⇒ x₁ = x₂` and `∀ ε > 0 ∃ N ∈ ℝ ...`) with `text` empty, so the scanner never sees spaced LaTeX, the subscripts are single codepoints `x₁`, the set is the single codepoint `ℝ`, and the epsilon is `ε` U+03B5 (`GREEK SMALL LETTER EPSILON`, which passes `_is_unicode_greek`). The fixture therefore exercises none of the spacing, none of `\mathbb { N }`, and not the lunate-epsilon variant.

Relates to **#5** (formula blocks / LaTeX enrichment + fallback), **#6** (extract symbol index), and **#16** (formula enrichment default-on, which makes the spaced `latex` the canonical path).

## Scope

- In `math_ide/ingest/symbols.py`, make `_consume_unicode_subscript` / `_consume_latex_subscript` skip optional whitespace between the letter head and `_`, between `_` and `{`, and inside `{ ... }`, so `x _ { 1 }`, `a _ { n }`, and `x_1` all produce one whole subscripted token.
- Make the `\mathbb`/`\mathcal`/`\mathfrak`/`\mathscr` set branch tolerate whitespace, i.e. match `\\mathbb\s*\{\s*([^}]*?)\s*\}` so `\mathbb { N }` is recognized and emitted with `kind="set"`.
- Reconsider the `function` classification in `_classify_letter` so a whitespace-separated `(` (e.g. `f (`) still tags the letter as a `function`, not a `variable`.
- Extend Greek detection so `GREEK ... SYMBOL` codepoints (lunate `ϵ` U+03F5, `ϑ` U+03D1, `ϕ` U+03D5, ...) are treated as Greek variables alongside `GREEK ... LETTER`, so the `orig`/`orig_fallback` path emits an epsilon token.
- Add unit tests over the **real** spaced strings quoted above (and keep, do not replace, the tight-fixture tests).

## Acceptance criteria

- [ ] On the real `example.pdf` conversion (formula enrichment on), the injectivity formula's symbol index yields **distinct** tokens for `x _ { 1 }` and `x _ { 2 }` (the subscript is part of the token), so they map to different formula-symbol concepts rather than all collapsing to `example#concept/sym-x-78`.
- [ ] `a _ { n }` in the convergence formula yields a single `a_n` token (kind `variable`), not separate `a` + `n` occurrences.
- [ ] `\mathbb { N }` yields one token with `kind="set"`, not a bare `N` with `kind="variable"`.
- [ ] Both the LaTeX `\epsilon` and the linearized `orig` lunate `ϵ` (U+03F5) yield an epsilon formula symbol; the `orig` string `∀ ϵ > 0 ∃ N ∈ N ∀ n ≥ N : | a n -L | < ϵ` no longer drops epsilon.
- [ ] `f (` (space before paren) classifies `f` as `kind="function"`.
- [ ] Existing tight-token fixture tests against `tests/fixtures/example_docling.json` still pass unchanged.

## Out of scope

- A full LaTeX / math parser or a parse tree (the scanner stays a deterministic regex-driven token pass per the module docstring and **#6**).
- Recovering correct `start`/`end` render offsets when Docling's spacing makes the canonical string differ visually from layout (render bbox assignment is **#11**).
- Mapping spaced tokens back to a normalized de-spaced canonical string for display; this issue only fixes token identity and kind, not the stored `latex`/`orig` text.
