# Math IDE — interaction layer

The interaction layer turns the **rendered document** into the *Math IDE*: users
left-click to **go to definition** (#12), right-click to open a **concept card**
(#13), and the client measures **render bboxes** at layout time (#11).

The design principle is **precompute in Python, keep the client thin**. All
navigation logic — which block a click jumps to, what a concept card contains —
is computed by pure, unit-tested Python in `math_ide.renderer.navigation` and
embedded in the page as a JSON blob. `assets/app.js` never recomputes it; it
reads the blob, measures layout, and wires the DOM.

- Navigation logic: `math_ide.renderer.navigation` (pure Python)
- Embedded payload: `<script type="application/json" id="math-ide-data">`
- Client: `math_ide/renderer/assets/app.js`
- Styles: `math_ide/renderer/assets/styles.css`
- Tests: `tests/test_navigation.py` (offline), `tests/test_ide_browser.py`
  (Playwright, skipped without a browser)

## `navigation.py` API

```python
from math_ide.renderer.navigation import (
    definition_target, concept_card, build_ide_payload,
)
```

### `definition_target(doc, occurrence_or_id) -> block_id | None`

The *go to definition* target block id for an occurrence (accepts an
`Occurrence` or its id). Priority (from `CONTEXT.md`):

1. **Citation occurrence** → its `target_block_id` (the cited formal block;
   resolves deterministically, no LLM, works at `structure_ready`).
2. The occurrence's concept's `seeded_by_block_id` (the formal block that seeded
   the concept).
3. The concept's `defined_name` occurrence's `block_id` (the naming label).
4. The concept's `defining_occurrence_id` occurrence's `block_id`.
5. `None` — nothing resolvable yet (the disabled **"resolving…"** state).

A formula symbol has no target until meaning resolution links it to a formally
defined concept (e.g. the convergence `ε` → the Konvergenz definition block).
Stub symbols with no formal block stay `None`.

### `concept_card(doc, concept_id) -> dict`

The side-panel concept card payload:

```python
{
  "id", "name", "resolution_status",
  "formal_meaning", "inferred_meaning",
  "defining_occurrence": {"id", "block_id"} | None,
  "references": [{"occurrence_id", "block_id", "kind"}, ...],
  "neighbourhood": {
    "structural": [{"concept_id"|"block_id", "kind", "origin", "name"}, ...],
    "semantic":   [{"concept_id"|"block_id", "kind", "origin", "name"}, ...],
  },
}
```

- `references` = every occurrence linked to the concept **except** its defining
  occurrence (the "references" of `CONTEXT.md`).
- The neighbourhood is split by `Relation.origin`: deterministic **structural**
  edges (`seeded_by`, `sibling`, `co_occurring`) vs LLM-inferred **semantic**
  edges (`uses`, `defines`, `generalizes`, `specializes`, `instance_of`), shown
  as *inferred*. A `seeded_by` edge targets a block, so its entry carries
  `block_id` (and `concept_id: None`); every other edge names a concept.
- Raises `KeyError` for an unknown concept id.

### `build_ide_payload(doc) -> dict`

One JSON-serialisable blob embedded in the page. Everything `app.js` needs to
navigate and build cards **without recomputation**:

```python
{
  "document_id", "ingestion_state",
  "occurrences": {
    "<occ_id>": {"block_id", "concept_id", "kind",
                 "target_block_id", "definition_target",
                 "render_bbox"}, ...
  },
  "concepts": {
    "<concept_id>": {"id", "name", "resolution_status",
                     "formal_meaning", "inferred_meaning",
                     "defining_occurrence_id", "seeded_by_block_id"}, ...
  },
  "relations": [{"source", "target", "kind", "origin", "target_is_block"}, ...],
  "cards": {"<concept_id>": <concept_card(...)>, ...},
}
```

`definition_target` is precomputed per occurrence; `cards` are precomputed so the
right-click panel is instant. Re-running `build_ide_payload` after meaning
resolution regenerates the blob with more concrete targets and resolved cards.

`render_bbox` is a **client-side, post-layout** slot: it is `null` in the embedded
payload (and in the `Occurrence` model at import) and is written by `app.js` after
layout — every `.occ` is measured once KaTeX/CDN/fonts settle, and the measured
box is stored both in `state.bboxes` and back into
`state.data.occurrences[id].render_bbox`, so a re-serialised live payload carries
the rendered-document geometry.

## Embedded payload + DOM

`render_document` embeds the payload before `app.js`:

```html
<aside id="concept-panel" class="concept-panel" hidden></aside>
<script type="application/json" id="math-ide-data">{ … }</script>
<script defer src="assets/app.js"></script>
```

The JSON is emitted with `<` escaped to `<` so a `</…` inside any string can
never prematurely close the `<script>` element.

Occurrence anchors gain one extra attribute beyond the renderer's base contract:

| Attribute                | Meaning                                              |
| ------------------------ | --------------------------------------------------- |
| `data-resolvable="false"`| `definition_target` is `None` — disabled, "resolving…" |

The attribute is **omitted** when a target exists, so the default state is
resolvable. It is kept in sync with the payload (and re-applied on `refresh`).

## Client interactions (`app.js`)

`window.mathIDE` is the public surface:

| Method                 | Behaviour                                                |
| ---------------------- | ------------------------------------------------------- |
| `renderBboxes()`       | map `occ_id -> {x, y, width, height}` in scroll-container coords (#11) |
| `remeasure()`          | re-measure all render bboxes now                         |
| `goToDefinition(occId)`| scroll to + highlight the occurrence's definition target (#12) |
| `showCard(conceptId)`  | open the concept card in the side panel (#13)           |
| `hideCard()`           | close the side panel                                     |
| `refresh(dataOrUrl)`   | reload the payload (object or URL) and re-render         |
| `data` / `bboxes`      | current payload / last-measured bboxes                  |

### #10 KaTeX typesetting

KaTeX is loaded from a CDN and **actually invoked** client-side: `app.js`
typesets every ready formula's `data-latex` into its `.katex-target` host
(`katex.render(latex, host, {throwOnError:false, displayMode:false})`, guarded by
`typeof katex`). This runs once KaTeX is ready (`whenKatexDone`) and again from
the formula-upgrade `MutationObserver` when a formula upgrades to ready, so a
ready formula shows typeset math rather than raw LaTeX source. Because
`katex.render` replaces the host's children, the per-symbol hit targets are
**decoupled** (see the renderer's ready-formula DOM contract): after typesetting,
`app.js` best-effort matches each `data-occurrences` token to the rendered KaTeX
glyph span(s) (`.mord`) and tags the matched glyph with `class="occ"` + the
token's data attributes; matched tokens hide their duplicate `.occ-fallback`
anchor, unmatched tokens keep the visible fallback. If KaTeX is unavailable the
`.occ-fallback` remains the working hit-target layer.

### #11 Render bboxes

After `DOMContentLoaded`, after `load` (KaTeX/CDN/fonts settled), and on a
debounced `resize`, the client measures each `.occ` with
`getBoundingClientRect` relative to the **scroll container's content box**
(adding its scroll offset) so a stored bbox is stable regardless of scroll
position. Each measured box is stored in `state.bboxes` **and** written back into
`state.data.occurrences[id].render_bbox` (the payload's post-layout slot).
Occurrences that aren't laid out (e.g. a hidden `.occ-fallback` after KaTeX
claimed the glyphs) are skipped so a zero-area duplicate can't clobber the real
glyph target. A `MutationObserver` watching `.formula` (`data-enrichment`
attribute and subtree changes) typesets and re-measures when a formula upgrades
from fallback → LaTeX; `mathIDE.remeasure()` forces a pass. Whether the symbol
target is its own `.occ-fallback` span or a tagged KaTeX glyph, it is strictly
smaller than the whole-formula box.

### #12 Go to definition

A left-click (or `Enter`/`Space` on a focused `.occ`) reads
`definition_target` from the payload and smooth-scrolls to that block id,
applying a `.definition-highlight` ring (a brief pulse) to the target. When the
target is `null` the anchor is disabled: a click triggers only a short
"resolving…" flash, no navigation. Citation occurrences navigate immediately
because their target is known at `structure_ready`.

### #13 Concept card

A right-click (`contextmenu`) on an `.occ` opens the side panel built from the
precomputed card for the occurrence's concept. The card shows the name +
resolution status, formal and inferred meaning, the defining occurrence, a
clickable **references** list (each navigates to that occurrence's block), and a
**neighbourhood** split into *Structural* (blue accent) and *Semantic
(inferred)* (pink accent, `inferred` badge) — clicking a related concept opens
its card, clicking a structural block edge scrolls to that block. The panel is
re-readable: after meaning resolution, call `mathIDE.refresh(newPayloadOrUrl)`
and the open card re-renders with the resolved data.

## Testing

- `tests/test_navigation.py` runs entirely offline against the resolved fixture
  (`ingest → seed_ontology → MockResolver.resolve`): citation target, defined
  name / `ε`-after-resolution targets, the unresolved → `None` case, the
  concept-card contents, and the payload shape.
- `tests/test_ide_browser.py` drives a real browser via Playwright to check
  render-bbox measurement, the symbol-smaller-than-formula invariant, KaTeX
  typesetting of a ready formula (a `.katex` element appears), re-layout on
  upgrade (a pending fallback formula mutated to ready + KaTeX content changes
  the symbol bbox and writes `render_bbox` back into the live payload), a
  go-to-definition click, the "resolving…" cue, and the concept card. It
  `pytest.importorskip`s Playwright and skips if no browser binary is present,
  so the default suite stays green without browsers; the KaTeX-dependent
  assertions additionally skip if the KaTeX CDN is unreachable.
