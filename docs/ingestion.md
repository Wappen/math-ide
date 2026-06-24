# Ingestion

Ingestion turns a **source document** (a mathematical PDF) into a
**math document** — the canonical tree of typed blocks defined in
`math_ide/schema.py`. This page covers stage 1: building the **block tree** from
Docling output. Occurrences, concepts and relations are filled by a later wave;
this stage leaves those indices empty and sets `ingestion_state =
"structure_ready"`.

## Two paths in, one shape out

Ingestion always consumes a **Docling-style JSON dict** (the shape Docling's
`document.export_to_dict()` produces). There are two ways to get one:

1. **Offline / fixture path (default, used by all tests).** You already have a
   Docling JSON dict (e.g. `tests/fixtures/example_docling.json`). No Docling,
   torch, or network needed. This keeps ingestion deterministic and CI-friendly.
2. **Live path (optional).** Convert a PDF/URL with Docling at runtime via
   `math_ide.ingest.docling_runner.run_docling`, which imports Docling **lazily**
   inside the function. The rest of the package imports cleanly without Docling
   installed.

Both feed the same adapter, so the produced `MathDocument` is identical in shape.

```
PDF / URL ──(optional, lazy)──► run_docling ──┐
                                              ├─► Docling JSON dict ─► build_math_document ─► MathDocument
Docling JSON file ────────────────────────────┘
```

## Public entry point

```python
from math_ide.ingest import build_math_document

doc = build_math_document(docling_dict, document_id="analysis-skript")
```

`document_id` defaults to a slug of the Docling `name` (or the source filename
stem). Every block id is namespaced under it (`{document_id}#block/...`).

## The Docling-JSON subset we consume

Documented at the top of `docling_adapter.py`. In short, per document:
`origin.{mimetype,binary_hash,filename}`, `body.children` (reading order via
`$ref`), and per text node: `label`, `text`, `orig`, and the first `prov` entry
(`page_no`, `bbox`, `charspan`). Everything else is ignored; unknown labels fall
back to `Paragraph`.

## How nodes map to blocks

| Docling `label`  | Math-document block | Notes |
|------------------|---------------------|-------|
| `section_header` | `Section`           | Subsequent blocks nest under the most recent section. |
| `text`           | `Paragraph` **or** a formal block | See formal-block detection below. |
| `formula`        | `Formula`           | `orig_fallback` set immediately; `latex` only if Docling enrichment ran. |
| (other / unknown)| `Paragraph`         | Conservative fallback. |

Source bboxes and `page_no` come straight from `prov[0]`; for mapped blocks they
match the fixture's `prov.bbox` exactly.

### Formal-block detection with preamble split (`formal_blocks.py`)

Docling often merges a formal label into a plain `text` node, sometimes behind
leading prose:

> *Ein wichtiges Konzept … ist die Injektivität. **Definition 1.2
> (Injektivität):** Eine Abbildung …*

We regex-detect the label (German **and** English spellings — `Definition`,
`Theorem`/`Satz`, `Lemma`, `Corollary`/`Folgerung`, `Proof`/`Beweis`,
`Example`/`Beispiel`, `Remark`/`Bemerkung`), capture the dotted `number`
(`X.Y`) and optional parenthesised `(DefinedName)`, and emit the matching
**distinct** schema class (`Definition`, `Theorem`, …) — never a shared enum.

Leading prose becomes the block's `preamble`; the rest becomes `body`. Bboxes
for the preamble vs. the block are estimated by **char-span subdivision** (see
below).

A bare numbered mention inside prose is a **citation**, not a header, so it stays
a `Paragraph`. The rule: a match is a header only if it (a) introduces a body
with a `:`/dash separator, (b) names what it defines via `(Name)`, or (c) opens
the node. A bare `.` is not a body separator (it ends sentences).

### Char-span subdivision

`docling_adapter.subdivide_bbox(bbox, charspan, sub_start, sub_end)` estimates a
sub-bbox for a `[start, end)` slice of a node by linear interpolation along the
box width (single-line, uniform-pitch approximation). It is reused by the
preamble split and will be reused by occurrence placement (#7).

### Formula blocks and the enrichment lifecycle (`formula.py`)

`Formula` blocks always keep Docling's linearized `orig` in `orig_fallback`, so
occurrences are extractable before LaTeX exists. If a formula node carries LaTeX
`text` (Docling formula enrichment ran), the block is born `ready`; otherwise
`pending`.

```python
from math_ide.ingest.formula import build_formula, upgrade_formula, mark_failed

f = build_formula(id, orig="∀ x₁ ∈ X : ...", text="")   # pending
upgrade_formula(f, latex)   # -> ready: latex set, symbol_index rebuilt
mark_failed(f)              # -> failed: keeps orig_fallback + source_bbox
```

The **symbol index** always indexes the *canonical content* (`latex` when ready,
else `orig_fallback`), so upgrading rebuilds it against the new string.

### Symbol index extraction (`symbols.py`)

`extract_symbol_index(content)` returns `SymbolSpan{token, start, end, kind}`
for each identifier, with offsets into `content`. It handles **both** Docling
unicode `orig` (`ε`, `x₁`, `a_n`, `ℝ`) and **LaTeX** (`\varepsilon`, `x_1`,
`\mathbb{R}`). Identifiers: single Latin letters (`function` if followed by `(`,
else `variable`), Greek letters, blackboard sets (`set`), and subscripted
identifiers kept whole (`a_n`, `x_1`).

**Operator-skip rule** (documented in code): pure structure is never indexed —
quantifiers/logic (`∀ ∃ ⇒ →`, `\forall \in \Rightarrow`), relations
(`= ≠ < > ≤ ≥ ∈ :`), arithmetic/grouping/punctuation (`+ − ( ) | , .`). Only
things that *denote a mathematical object* become symbols.

## CLI

```
python -m math_ide ingest <source> [-o OUT] [--document-id ID] [--formula] [--ocr]
```

`<source>` is a `.json` Docling dict (read directly) or a `.pdf`/URL (converted
live via the lazy Docling runner). Output is the `MathDocument` as pretty JSON
(`model_dump_json(indent=2)`). The `--formula`/`--ocr` flags only affect the live
PDF path.

`python -m math_ide` dispatches `ingest` / `render` / `serve` with **lazy**
per-subcommand imports, so a subcommand whose module is not yet built never
breaks the others.

## What's intentionally out of scope here

Occurrence extraction (#7), concept seeding and relations (#8), and meaning
resolution (#9) run in later waves. After stage 1 the document is at
`structure_ready` with empty occurrence/concept/relation indices.
