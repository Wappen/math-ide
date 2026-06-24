# Renderer

Turns a `MathDocument` (the *math document*) into the **rendered document**: a
standalone, interactive HTML page rebuilt from the parsed block tree, never
painted from PDF pages.

- Module: `math_ide.renderer.render`
- CLI: `math_ide.renderer.cli` (`run`, `serve`), wired as the `render` / `serve`
  subcommands in `math_ide.__main__`.
- Styles: `math_ide/renderer/assets/styles.css`
- Client JS hook: `assets/app.js` (authored in a later wave — #11/#12/#13; its
  absence is tolerated by the browser).

## Public API

```python
from math_ide.renderer import render_document, render_block

html_page = render_document(doc)        # full standalone HTML page (str)
fragment  = render_block(block, doc)    # one block's HTML fragment (str)
```

`render_document` loads KaTeX from a CDN in `<head>`, references `assets/styles.css`
and `assets/app.js`, and wraps the document in a scroll container so
go-to-definition can scroll within it. `render_block` renders a single block
(and its descendants); it takes `doc` so it can place occurrence anchors from
the document's occurrence index.

## CLI

```bash
# Render a MathDocument JSON file to HTML
python -m math_ide render path/to/doc.json -o out.html

# Serve the rendered page + assets/ over HTTP (stdlib http.server)
python -m math_ide serve path/to/doc.json --host 127.0.0.1 -p 8000
```

`serve` materialises `index.html` plus a link to the `assets/` directory in a
temp dir and serves it, so KaTeX, `styles.css` and `app.js` all resolve.

## DOM conventions (contract for the IDE wave)

The renderer emits a stable DOM vocabulary. Downstream waves query these
selectors: #11 measures render bboxes, #12 wires go-to-definition, #13 opens the
concept card. The authoritative copy of this table lives in the module docstring
of `render.py`; keep them in sync.

### Containers

| Element                                   | Meaning                       |
| ----------------------------------------- | ----------------------------- |
| `<main class="math-doc-scroll">`          | scrollable navigation root    |
| `<article class="math-doc" data-document-id="…">` | document wrapper      |
| `<body data-ingestion-state="…">`         | pipeline state for the IDE    |

### Blocks

Every rendered block carries **both** `id="<block_id>"` and
`data-block-id="<block_id>"` (equal to the schema block id) so go-to-definition
can `getElementById` and scroll to it.

| Block type | Element + classes                                                  |
| ---------- | ------------------------------------------------------------------ |
| `Section`  | `<section class="block section">` with `<h{n} class="section-title">` |
| `Paragraph`| `<p class="block paragraph">`                                      |
| `Formula`  | `<div class="block formula" data-enrichment="ready\|pending\|failed">` |
| formal     | `<div class="block formal {type-lower}" data-formal-type="Definition\|…">` |

Formal blocks contain, in order:

```html
<div class="formal-header">Definition 1.2 (Injektivitaet)</div>
<p class="formal-preamble">…</p>   <!-- only when a preamble is present -->
<div class="formal-body">…</div>
```

The `{type-lower}` class (`definition`, `theorem`, `lemma`, `corollary`,
`proof`, `example`, `remark`) drives per-type visual styling.

### Formulas

The formula wrapper always carries `data-enrichment` so the IDE can tell ready
from degraded formulas.

- `enrichment_status == "ready"` (and `latex` present): emit a **decoupled** pair
  of siblings so KaTeX can own a dedicated typeset node *without* deleting the
  per-symbol hit targets (KaTeX's `katex.render` replaces its host's children):

  ```html
  <span class="katex-target" data-latex="<latex>"
        data-occurrences='[{"token":"f","attrs":"data-occurrence-id=… …"}, …]'>
  </span>                                  <!-- empty; KaTeX typesets here -->
  <span class="occ-fallback">…inline .occ anchored linearized text…</span>
  ```

  `app.js` typesets `data-latex` into `.katex-target`, then best-effort matches
  each `data-occurrences` token to the KaTeX glyph span(s) it produced (KaTeX
  wraps identifiers in `.mord` spans) and tags the matched glyph with
  `class="occ"` + the token's `attrs`. Matched tokens have their duplicate
  `.occ-fallback` anchor hidden; any token that can't be matched keeps its
  visible fallback anchor. With no JS / no KaTeX the `.occ-fallback` is the
  working hit-target layer. Either way each symbol target stays strictly smaller
  than the whole-formula box. `data-occurrences` is `[]` (and `.occ-fallback`
  omitted) when the formula has no symbol occurrences.
- otherwise (`pending` / `failed`): emit `<span class="formula-fallback">…</span>`
  showing the degraded linearized `orig_fallback`, with the same inline `.occ`
  anchoring (this path already works and is unchanged).

### Occurrence anchors (hit targets)

```html
<span class="occ"
      data-occurrence-id="<occ.id>"
      data-concept-id="<occ.concept_id or ''>"
      data-kind="formula_symbol|defined_name|citation"
      data-target-block-id="<occ.target_block_id>"   <!-- citations only -->
      tabindex="0">…surface text…</span>
```

An occurrence is anchored when `occ.block_id` equals the rendered block and its
`span = [s, e]` indexes a **kind-specific canonical string**:

| occurrence kind  | canonical string anchored into  |
| ---------------- | ------------------------------- |
| `formula_symbol` | the formula's `canonical_content` |
| `defined_name`   | the formal block's header line  |
| `citation`       | the paragraph's `text`          |

Anchoring rules:

- All text is HTML-escaped; anchors never corrupt surrounding text.
- Spans are applied left-to-right; an occurrence whose span is missing, empty,
  out of range, or overlaps an already-emitted region is skipped.
- `tabindex="0"` makes anchors keyboard-focusable hit targets; render-bbox
  measurement (#11) reads their layout, click handlers (#12/#13) read their
  `data-*`.
