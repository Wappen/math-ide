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
