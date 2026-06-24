# Staged ingestion pipeline (`math_ide.pipeline`)

The pipeline orchestrates the two ingestion stages into one observable state
machine. Stage 1 (structure) is synchronous and fast so the IDE can open a
document immediately; stage 2 (meaning resolution) and re-entrant formula
enrichment run after, mutating the document in place and advertising progress
through a monotonic version. Single-process, no external job queue (#14
out-of-scope: distributed queue).

## State machine

```
ingesting ──► structure_ready ──► resolving ──► ready
                   ▲                   │
                   │   resolver failed │
                   └──── resolving ◄───┘   (terminal partial; stage-1 intact)
```

| State             | Meaning | Available to the IDE |
|-------------------|---------|----------------------|
| `ingesting`       | Transient; held only while `ingest_structure` builds the tree + seeds the ontology. | — |
| `structure_ready` | **Stage 1 done.** Block tree, occurrences, seeded concepts and deterministic structural relations all exist. | Open the document. **Citations** resolve (`occurrence.target_block_id`) and **formal-block navigation** works (`concept.seeded_by_block_id`, `concept.defining_occurrence_id`). |
| `resolving`       | Stage 2 (a `Resolver`) is running — *or* a terminal-but-partial state if the resolver failed. Stage-1 results are always intact. | Everything from `structure_ready`; concept cards / symbol navigation enrich as resolution lands. |
| `ready`           | Stage 2 succeeded: coreference, inferred meanings and semantic relations applied; touched concepts/occurrences `resolved`. | Full ontology. |

`ingestion_state` lives on the `MathDocument` itself (schema source of truth);
the pipeline drives the transitions and never invents new states.

## Public API

```python
from math_ide.pipeline import (
    ingest_structure,      # stage 1 -> structure_ready (sync, fast)
    Pipeline,              # owns doc + version + stage-2 worker
    run_full,              # convenience: ingest (if needed) + stage 2
    apply_formula_upgrade, # re-entrant single-formula enrichment
)
```

### Stage 1 — `ingest_structure(source_or_dict, *, document_id=None) -> MathDocument`

Runs `build_math_document` then `seed_ontology`. Returns a document at
`structure_ready`, immediately usable by the IDE. `source_or_dict` is a
Docling-style JSON dict; live PDF→JSON conversion stays in the CLI behind a lazy
Docling import.

### Stage 2 — `Pipeline`

```python
doc = ingest_structure(docling)
pipeline = Pipeline(doc, resolver=MockResolver())   # default resolver = MockResolver

# (a) synchronous wait path
pipeline.run_full(wait=True)          # returns the ready (or partial) doc
assert doc.ingestion_state == "ready"

# (b) async / background path
pipeline.run_full(wait=False)         # starts a daemon threading.Thread
...                                    # caller is not blocked
pipeline.status()                      # PipelineStatus(state, version, done) — poll this
pipeline.join()                        # block until the worker settles (deterministic)
```

* `run_full(wait=True)` runs the resolver synchronously and returns the
  document.
* `run_full(wait=False)` (or `start()`) launches the resolver on a daemon
  `threading.Thread`, returns immediately, and exposes `status()`/`state` plus
  `join()`/`wait()` so callers and tests are deterministic.
* `error` holds the exception a failing resolver raised (else `None`).

The module-level `run_full(source_or_dict, *, resolver=None, document_id=None,
wait=True)` is a one-shot convenience that accepts either a Docling dict (it
runs stage 1 first) or an already-`structure_ready` document. For the background
path, construct a `Pipeline` directly so you keep the handle to `join()`.

### `PipelineStatus`

Immutable snapshot with `.state`, `.version`, `.done`, and `.etag` (`'"<n>"'`).
`done` is `True` once stage 2 has settled — either `ready` or a terminal partial
`resolving` after the worker exited.

## Version / etag refresh model

`Pipeline` keeps a monotonically increasing integer `version`, bumped on **every
state-changing mutation**:

* entering `resolving`,
* the resolver completing (success *or* tolerated failure),
* each `apply_formula_upgrade`.

`etag` is the version rendered as an HTTP-style entity tag (`"<n>"`). The
renderer polls `status()` and compares `version`:

1. **Version unchanged** → nothing to do.
2. **Version changed** → re-read the (small) `occurrences` / `concepts` indices
   and re-paint only the affected anchors. The pipeline **never re-ingests**;
   the block tree is stable except for in-place formula upgrades.

This makes refreshes cheap and conditional: a side panel showing a concept card
re-fetches only when the version moves, and a `304`-style "not modified" short
circuit is available via `etag`.

## Re-entrant formula enrichment — `apply_formula_upgrade(doc, formula_id, latex)`

A single formula's LaTeX (from formula enrichment, #5) often arrives *after* the
document is already open. `apply_formula_upgrade` upgrades just that formula
without re-ingesting the document:

1. `upgrade_formula(formula, latex)` sets `latex`, flips `enrichment_status` to
   `ready`, and **rebuilds the symbol index** against the new LaTeX (offsets now
   index `latex`, not `orig_fallback`).
2. That formula's old `formula_symbol` occurrences are dropped and re-derived
   against the new symbol index, with fresh source bboxes subdivided over the
   LaTeX and `render_bbox = None` (the renderer re-measures, #11).
3. Stub concepts for newly-appearing tokens are seeded; **tokens that survive
   keep their stub concept's identity** — so a symbol already resolved during
   stage 2 (e.g. `a_n` → its inferred meaning) stays resolved across the
   upgrade. Stub concepts orphaned by the reflow (referenced by no occurrence or
   relation) are pruned.
4. Unrelated blocks, occurrences and concepts are untouched. Unknown
   `formula_id`, or re-applying the same LaTeX, is a no-op (idempotent).

The `Pipeline.apply_formula_upgrade(formula_id, latex)` wrapper additionally
bumps the version.

### How the renderer reflows

On the version bump the renderer replaces only this formula's rendered node —
re-running KaTeX on `formula.latex` instead of rendering the `orig_fallback`
text — and re-binds the occurrence anchors for `block_id == formula_id` (their
spans and bboxes changed). No other DOM node changes; the upgrade is local.

## Resolver-failure tolerance

A resolver that raises, or that returns the document still at `resolving` (the
documented partial-result path of `AnthropicResolver`), never crashes the
pipeline:

* the exception is caught and stored on `pipeline.error`,
* `ingestion_state` is left at `resolving` (a sane partial), **not** `ready`,
* stage-1 results (tree, occurrences, seeded concepts, citation + formal-block
  navigation) remain intact and usable,
* the run is still marked `done` so callers stop polling.

The IDE therefore degrades gracefully: a document whose LLM stage failed is
still fully openable and navigable at `structure_ready`-equivalent fidelity.

## CLI usage

`python -m math_ide ingest` is **fast by default** — it runs stage 1 only and
writes a `structure_ready` document:

```bash
# stage 1 only (default) — structure_ready, no LLM
python -m math_ide ingest tests/fixtures/example_docling.json -o doc.json

# run stage 2 to 'ready' before writing (MockResolver by default)
python -m math_ide ingest tests/fixtures/example_docling.json --wait

# choose the resolver (anthropic SDK imported lazily; reads ANTHROPIC_API_KEY)
python -m math_ide ingest tests/fixtures/example_docling.json --wait --resolver anthropic
```

| Flag | Effect |
|------|--------|
| *(none)* | Stage 1 only → `structure_ready` (fast, deterministic, offline). |
| `--wait` | Also run stage 2 to `ready` before writing output. |
| `--resolver mock\|anthropic` | Stage-2 resolver used with `--wait` (default `mock`). `anthropic` is constructed lazily, only when actually used. |

All pre-existing flags (`-o/--output`, `--document-id`, `--formula`, `--ocr`)
keep working unchanged.
