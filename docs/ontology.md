# Ontology seeding (stage 1)

The `math_ide.ontology` package turns a freshly-ingested **math document** (a
block tree with formula symbol indices) into a navigable ontology *without any
LLM*. It is the second half of synchronous, offline, deterministic ingestion
and leaves the document at `ingestion_state = "structure_ready"` — the point the
renderer may open it (#10, #14).

Two passes, run by `seed_ontology(doc)`:

1. `occurrences.extract_occurrences(doc)` — materialise the occurrences index
   with dual bboxes (#7).
2. `concepts.seed_concepts_and_relations(doc)` — seed concepts + deterministic
   structural relations and wire occurrences to concepts (#8).

Both mutate `doc` in place and return it. `seed_ontology` runs them in order;
`seed_concepts_and_relations` assumes occurrences already exist.

Meaning resolution — concept disambiguation, inferred meaning, and *semantic*
relations — is a separate asynchronous stage (#9) and never runs here.

## Occurrences (#7)

An **occurrence** is one surface appearance of mathematical notation at one
document location. Every occurrence carries:

- a **source bbox** in PDF page space, estimated by char-span subdivision of its
  host block's bbox (`docling_adapter.subdivide_bbox`, a single-line linear
  interpolation). Always set when the host block has a bbox.
- a **render bbox**, always `None` at this stage; layout fills it in (#11).

Three kinds are produced:

| kind | one per | `span` indexes into | `target_block_id` | `concept_id` (after #8) |
|------|---------|---------------------|-------------------|--------------------------|
| `formula_symbol` | `SymbolSpan` in a `Formula.symbol_index` | the formula's `canonical_content` | — | the token's stub concept |
| `defined_name` | formal block with a `defined_name` | the block's reconstructed label | — | the seeded formal concept (this is its **defining occurrence**) |
| `citation` | `<keyword> <number>` match in prose | the host block's text/body/preamble | the cited formal block | the cited block's seeded concept |

### Defined-name span and bbox

The adapter discards a formal block's original label text, keeping only
`number` / `defined_name` / `body`. The block's `source_bbox` covers the
original text from the keyword to the node end, so we rebuild a parallel label
string

```
"{Type} {number} ({defined_name}): {body}"
```

(`reconstruct_label`), locate `defined_name` in it, and subdivide the block bbox
against that reconstruction. Offsets map linearly onto the block bbox just like
the original did, so the estimate is internally consistent.

### Citation detection

`CITATION_RE` matches a formal-environment keyword (the German/English spellings
shared with `ingest.formal_blocks.KEYWORD_TO_CLASS`) **followed by a dotted
number** — `Definition 1.1`, `Satz 2.3`, `Lemma 4`. The number is required so
the citation resolves to exactly one block; a bare `Definition` has no
unambiguous target and is intentionally ignored. Resolution is a deterministic
lookup keyed on `(block class, number)`. Citations are scanned in `Paragraph`
text and in formal blocks' `body`/`preamble` (never their own label, which is
not stored on the block).

## Concepts (#8)

A **concept** is a canonical mathematical object. Two kinds are seeded:

- **Formal concepts** — one per formal-block `defined_name`. `formal_meaning` is
  lifted from the block body (authoritative; meaning resolution may add
  `inferred_meaning` but must never overwrite it). `defining_occurrence_id`
  points at that block's `defined_name` occurrence (whose `concept_id` is set to
  this concept). Because a formal concept has an authoritative meaning *and* a
  defining occurrence, it starts **`resolved`**.
- **Stub concepts** — one per *distinct formula symbol token*. No
  `formal_meaning`, no defining occurrence; each starts **`pending`** and is
  promoted by meaning resolution (#9). Every `formula_symbol` occurrence's
  `concept_id` is linked to its token's stub.

Citation occurrences' `concept_id` is set to the seeded concept of the block
they cite.

### Concept-id scheme

Both kinds keep the schema's `{document_id}#concept/{slug}` shape via
`mint_id(document_id, "concept", key)`:

- formal: `key = defined_name` → e.g. `…#concept/menge`,
  `…#concept/injektivitaet`, `…#concept/konvergenz`.
- stub: `key = stub_key(token)` = `sym-{token}-{hex codepoints}` → e.g.
  `…#concept/sym-x-58` for `X`, `…#concept/sym-x-78-2081` for `x₁`.

The codepoint suffix is necessary because `slugify` folds many distinct maths
tokens onto the same slug (`X`, `x₁`, `x₂`, `ε`, `ℝ` all slug to `x`; `N` and
`n` to `n`). Appending unicode codepoints guarantees **one stub per distinct
token** while staying url-friendly and deterministic.

`canonical_concept_id` is left `None` (reserved for cross-document merging, #v2).

### Resolution status at this stage

| concept kind | starts as |
|--------------|-----------|
| formal-block (has formal meaning + defining occurrence) | `resolved` |
| formula-symbol stub | `pending` |

## Structural relations (#8)

All relations seeded here have `origin = "structural"` (deterministic). Semantic
relations (`uses`, `defines`, `generalizes`, `specializes`, `instance_of`) are
the LLM's job (#9). Three kinds:

- **`seeded_by`** — concept → the formal block that introduced it. The target is
  a *block id*, not a concept, so `target_is_block = True` flags consumers not
  to look it up as a concept. One per formal concept.
- **`sibling`** — concepts seeded by the *same* formal block, emitted both ways.
  In v1 each block seeds exactly one concept (one `defined_name`), so the
  canonical corpus produces no sibling edges; the builder is exercised by a unit
  test with a synthetic multi-concept block.
- **`co_occurring`** — concepts whose occurrences appear in the *same* formula,
  emitted both ways between every distinct pair. In the example: `f`, `X`, `x₁`,
  `x₂` co-occur (injectivity); `ε`, `a_n`, `L`, `N`, `n`, `ℝ` co-occur
  (convergence).

Edges are de-duplicated on `(source, target, kind)`.

## Determinism

No network, no randomness, no LLM. Re-running `seed_ontology` on a fresh
`build_math_document(fixture)` yields byte-identical JSON. Offsets always index
the exact string they were measured against, so the document round-trips through
`MathDocument.model_dump_json()` / `model_validate_json()` unchanged.

# Meaning resolution (stage 2, #9)

Seeding (above) leaves the document at `structure_ready`: every formula symbol
has a **stub** concept (`resolution_status = "pending"`, no `inferred_meaning`)
and only deterministic **structural** relations exist. *Meaning resolution* is
the separate, asynchronous, LLM-driven stage that turns those stubs into a
navigable semantic layer. It lives in `math_ide/ontology/meaning.py`.

## The `Resolver` interface

```python
class Resolver(Protocol):
    def resolve(self, doc: MathDocument) -> MathDocument: ...
```

A resolver consumes a seeded document, computes a `MeaningDelta`, applies it in
place, and returns the same document. Two contracts every resolver honours:

- **`formal_meaning` is authoritative** — it is *never* read-modify-written.
  The guardrail is structural: all writes route through `MeaningDelta.apply`,
  which silently drops any `inferred_meaning` aimed at a concept that already
  has a `formal_meaning`.
- **Never crash the pipeline** — a resolver that cannot do its job returns the
  document (unchanged or partially changed) rather than raising.

`MeaningDelta` is the unit of change: `occurrence -> concept` coreference
links, `concept -> inferred_meaning` assignments, semantic `Relation`s, and the
sets of concept/occurrence ids to flip `pending -> resolved`. Applying a delta
de-duplicates relations against existing edges, so resolution is **idempotent**.

What a resolve pass does, in order:

1. **Coreference** — re-point a symbol stub's `formula_symbol` occurrences at
   the formally-defined concept they denote (so go-to-definition reaches the
   defining block).
2. **Inferred meaning** — set `inferred_meaning` on stub concepts (only those
   with no `formal_meaning`).
3. **Semantic relations** — add directed edges with `origin = "semantic"` and a
   kind drawn from `uses` / `defines` / `generalizes` / `specializes` /
   `instance_of` — clearly distinct from the structural `seeded_by` / `sibling`
   / `co_occurring` edges from #8, which are left untouched.
4. **Resolution status** — flip touched concepts/occurrences to `resolved`; on
   success set `ingestion_state = "ready"`.

## `MockResolver` (deterministic, offline)

The default, network-free resolver used by the tests. On the canonical fixture
it encodes the corpus's intended coreference:

| Defining concept | Symbol tokens linked to it |
|------------------|----------------------------|
| `Konvergenz` (Definition 2.1) | `ε`, `a_n`, `L`, `N` |
| `Injektivitaet` (Definition 1.2) | `f`, `X`, `Y` |

For each `(definition, token)` pair where the token has a stub concept,
`MockResolver`:

- sets the stub's `inferred_meaning`;
- adds two semantic relations — `stub --uses--> definition` and
  `definition --defines--> stub`;
- re-points every occurrence of that token at the definition concept;
- flips the stub `pending -> resolved`.

So the convergence **ε** ends up linked to the **Konvergenz** concept *both*
ways: every ε occurrence's `concept_id` becomes the Konvergenz concept id, and
the relation `ε-stub --uses--> Konvergenz` exists. Tokens without a stub concept
in a given document — e.g. `Y`, which appears only in the prose `f: X -> Y` and
so has no `formula_symbol` occurrence — are skipped silently; `f` and `X` are
still linked. After a pass, `ingestion_state = "ready"`.

## `AnthropicResolver` (live LLM, fault-tolerant)

Calls the Anthropic Messages API. Model default `"claude-sonnet-4-6"`; reads
`ANTHROPIC_API_KEY` (or an explicit `api_key=`). The `anthropic` SDK is imported
**lazily inside the methods**, so importing `meaning.py` (and the offline test
suite) never needs the SDK or a key.

**Prompt.** The system prompt (`meaning.SYSTEM_PROMPT`) states the task —
coreference, inferred meaning for definition-less symbols, and semantic
relations — plus the hard rules: never provide/change `formal_meaning`, only
reference ids present in the input, reply with a single JSON object. The user
prompt (`build_prompt`) serialises the seeded ontology: each concept's
`id`/`name`/`formal_meaning` (read-only, for coreference) and each occurrence's
`id`/`kind`/surface `token`/current `concept_id`.

**Expected JSON output schema** (`meaning.OUTPUT_SCHEMA_DOC`):

```json
{
  "occurrence_links": [
    {"occurrence_id": "<id>", "concept_id": "<id>"}
  ],
  "inferred_meanings": [
    {"concept_id": "<id>", "meaning": "<short prose>"}
  ],
  "relations": [
    {"source_concept_id": "<id>", "target_concept_id": "<id>",
     "kind": "uses|defines|generalizes|specializes|instance_of"}
  ]
}
```

`parse_response` tolerates a bare object, a ```` ```json ```` fence, or
surrounding prose (it slices first `{` to last `}`), and ignores entries with
the wrong types or a non-semantic relation kind.

**Failure tolerance.** On any API or parse error the call is retried up to
`max_retries` times (default 2). If every attempt fails, the document is
returned with whatever partial results were applied — typically none — and
`ingestion_state` is left at `resolving` (not `ready`) to signal partial
resolution to the pipeline. The resolver never raises into the caller. The same
`formal_meaning` guarantee holds: a failed pass changes nothing authoritative,
and the document still round-trips as a valid `MathDocument`.
