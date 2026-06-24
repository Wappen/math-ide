# Test fixtures

## `example_docling.json`

The canonical synthetic **Docling-style INPUT** for the whole pipeline. It is a
hand-written subset of what `DocumentConverter(...).convert(pdf).document.export_to_dict()`
produces, trimmed to exactly the fields the ingestion adapter relies on. It is
**input**, not a `MathDocument`; the ingestion adapter consumes it and produces
the canonical math document.

Owner: the schema agent is the single writer. Other waves (ingestion, ontology,
renderer, e2e) read it but must not edit it.

### Shape (the Docling-JSON subset we depend on)

```
{
  "schema_name": "DoclingDocument",
  "version": "1.0.0",
  "name": str,
  "origin": { "mimetype": str, "binary_hash": str, "filename": str },
  "body":   { "self_ref": "#/body", "children": [ { "$ref": "#/texts/N" }, ... ] },
  "groups": [],
  "texts": [ <text node>, ... ]
}
```

A **text node** has:

| field      | meaning                                                                 |
| ---------- | ----------------------------------------------------------------------- |
| `self_ref` | `"#/texts/N"` — JSON-pointer self reference.                            |
| `label`    | `"section_header"`, `"text"`, or `"formula"`.                           |
| `level`    | heading level (section headers only).                                   |
| `text`     | linearized text; **empty for formula nodes when enrichment is off**.    |
| `orig`     | original linearized string; for formulas this is the math fallback.     |
| `prov`     | list of provenance records (see below); present on every node.          |

A **prov record** has:

| field      | meaning                                                                 |
| ---------- | ----------------------------------------------------------------------- |
| `page_no`  | 1-based page number.                                                    |
| `bbox`     | `{ l, t, r, b, coord_origin }`, `coord_origin` = `"BOTTOMLEFT"`.        |
| `charspan` | `[start, end]` char offsets of this node's text on the page.            |

### Encoded content (the canonical example domain)

A short German analysis script chosen so downstream issues hit their acceptance
criteria:

1. **Section** "1 Mengen und Abbildungen" (`section_header`).
2. **Definition 1.1 (Menge)** — clean formal block, **no preamble**.
3. A paragraph containing the **citation** "Definition 1.1" (deterministic
   citation linking, no LLM).
4. A single `text` node that **merges leading prose with the next definition's
   label**: `"Ein wichtiges Konzept der Analysis ist die Injektivitaet.
   Definition 1.2 (Injektivitaet): Eine Abbildung f: X -> Y heisst injektiv, …"`.
   The ingestion adapter must split this into a Paragraph/preamble + a
   Definition block.
5. A **Formula** for injectivity with `orig` = `∀ x₁, x₂ ∈ X : f(x₁) = f(x₂) ⇒ x₁ = x₂`
   and empty `text` (enrichment pending). Used by the formula-fallback (#5) and
   symbol-index (#6) work.
6. **Section** "2 Folgen und Konvergenz".
7. **Definition 2.1 (Konvergenz)** — body references a sequence `a_n` and limit `L`.
8. A **Formula** for convergence with `orig` = `∀ ε > 0 ∃ N ∈ ℝ ∀ n ≥ N : |a_n − L| < ε`
   so the symbol index finds `ε`, `a_n`, `L`, `N`, and `ℝ`.

For the formula **"ready" upgrade** test (pending → ready), enrich the
injectivity formula in place with LaTeX:

```
\forall x_1,x_2 \in X : f(x_1)=f(x_2) \Rightarrow x_1=x_2
```

Every text and formula node carries `prov` with a page number, a `BOTTOMLEFT`
bbox, and a `charspan`.

## `example_docling_real.json`

A **captured real** `DocumentConverter(...).convert("example.pdf").document.export_to_dict()`
from **Docling 2.107.0** (formula enrichment on). Unlike the synthetic fixture
above — which is idealized, hand-tightened *input* — this is exactly what the
live model emits for `example.pdf`, so the offline real-shaped tests
(`test_structure_real.py` #22, `test_resolution_real.py` #21,
`test_inline_occurrences.py` #23, `test_acceptance_real.py` #24) exercise the
real code path without paying for a live GPU conversion. The gated
`test_acceptance_e2e_live.py` re-runs the live conversion and asserts the same
behaviour, so a drift between this committed snapshot and real Docling output is
caught (issue #24).

### Divergences it captures (vs. the synthetic fixture)

These are the real-world facts the synthetic fixture's idealized input hides — the
reason this fixture exists (issues #20–#24):

| aspect              | synthetic (`example_docling.json`)              | real (`example_docling_real.json`)                              |
| ------------------- | ----------------------------------------------- | --------------------------------------------------------------- |
| section titles      | `1 Mengen und Abbildungen` / `2 Folgen und Konvergenz` | `1 Grundbegriffe der Mengenlehre` / `2 Folgen und Grenzwerte` (#22) |
| document title      | absent                                          | a level-1 `section_header` → must become metadata, not a Section (#22) |
| page furniture      | absent                                          | a `page_footer` `"1"` (page number) → must be dropped (#22)      |
| citation            | a `Definition 1.1` cross-reference paragraph    | **none** — the real PDF has no numbered cross-reference → 0 citation occs (#24) |
| definition name     | `Injektivitaet` (ASCII)                         | `Injektivität` (umlaut-repaired, #18)                           |
| convergence error   | unicode `ε`                                     | LaTeX control word `\epsilon` (#20/#21)                          |
| subscripts          | tight `a_n` / `x₁`                              | spaced `a _ { n }` / `x _ { 1 }` (#20)                          |
| convergence domain  | ℝ (`∃ N ∈ ℝ`)                                  | ℕ (`\mathbb { N }`), a set token distinct from the threshold `N` (#20) |
| inline prose        | minimal                                         | real inline notation (`f : X → Y`, `lim n →∞ a n = L`, `als R`) → `inline_symbol` occs (#23) |

This fixture is **input**, not a `MathDocument`. To regenerate it from the source
PDF (requires the optional ingest extras / Docling installed):

```python
import json
from math_ide.ingest.docling_runner import run_docling
json.dump(run_docling("example.pdf", formula=True), open(
    "tests/fixtures/example_docling_real.json", "w"), ensure_ascii=False, indent=2)
```
