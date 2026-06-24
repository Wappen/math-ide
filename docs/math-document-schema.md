# Math document schema

The **math document** is the canonical, math-centric representation of a source
PDF. The Math IDE renders from this tree — never from Docling output directly —
and the ontology indexes into it. This page describes the shapes conceptually;
the authoritative models live in `math_ide/schema.py`.

## Document

A math document carries:

- **`document_id`** — the namespace for every identifier in the document.
- **`source`** — provenance of the original input (origin, filename, mimetype,
  content hash).
- **`blocks`** — the typed block tree (below).
- **`occurrences`**, **`concepts`**, **`relations`** — the parallel ontology
  indices that point into the block tree.
- **`ingestion_state`** — where the staged pipeline has reached:
  `ingesting → structure_ready → resolving → ready`. The renderer may open the
  document as early as `structure_ready`.

All identifiers are document-namespaced (they begin with `{document_id}#…`) so
that documents never collide and so a concept id is globally meaningful.

## Blocks

A block is a typed node in the document tree. Every block has an id and an
optional **source bbox** (its location on the source PDF page). Formal
environments are **distinct block types**, not a single block with a "kind"
label.

| Block        | What it is                                                                 |
| ------------ | ------------------------------------------------------------------------- |
| `Section`    | A heading plus the blocks nested beneath it. The tree's structural spine. |
| `Paragraph`  | A run of prose. May contain citation occurrences.                         |
| `Definition` | A numbered/labelled definition that introduces a concept.                 |
| `Theorem`    | A stated theorem.                                                         |
| `Lemma`      | A supporting result.                                                      |
| `Corollary`  | A result that follows from a nearby theorem or lemma.                     |
| `Proof`      | An argument establishing a result.                                        |
| `Example`    | A worked illustration.                                                    |
| `Remark`     | A clarifying aside.                                                       |
| `Formula`    | A mathematical expression with a symbol index (below).                    |

The formal blocks (`Definition` … `Remark`) share a common shape: an optional
**number** (e.g. `1.1`), an optional **defined name** (the term in the label,
e.g. *Menge*), a **body**, and an optional **preamble** — leading prose that
Docling merged into the same text node as the formal label and that ingestion
splits back out.

### Formula

A formula always preserves Docling's linearized original text as a **fallback**
so notation is usable before LaTeX is ready. Its **enrichment status** moves
`pending → ready` (LaTeX available) or `pending → failed` (enrichment gave up,
fallback retained). Its **symbol index** is a list of identifier spans —
`{ token, start, end, kind }` — into whichever string is currently canonical
(LaTeX when ready, otherwise the fallback). Those spans drive occurrence
extraction and render-bbox placement.

## Ontology indices

These three lists sit beside the block tree and reference blocks by id.

### Occurrence

A single surface appearance of notation at one location. Three kinds exist at
import time:

- **`formula_symbol`** — a symbol inside a formula (from the symbol index).
- **`defined_name`** — the defined term in a formal block's label.
- **`citation`** — an explicit numbered cross-reference (e.g. `Definition 1.1`).

Each occurrence records its **source bbox** (PDF space, set when known) and a
**render bbox** (rendered-document space, left empty until layout). It resolves
to exactly one **concept** (empty until meaning resolution). Citation
occurrences additionally point at the cited block.

### Concept

A canonical mathematical object — the thing two occurrences mean when they refer
to the same object. A concept carries a **formal meaning** (from a formal block,
authoritative) and/or an **inferred meaning** (assigned by the LLM, never
overriding the formal meaning), a **resolution status** (`pending` /
`resolved`), its **defining occurrence**, and the formal block that **seeded**
it. It reserves a nullable `canonical_concept_id` for future cross-document
merging (unused in v1).

### Relation

A directed edge between concepts. **Structural** relations are deterministic at
import — `seeded_by` (concept ↔ its formal block), `sibling` (concepts from the
same formal block), `co_occurring` (concepts appearing in the same formula).
**Semantic** relations are assigned later by the LLM — `uses`, `defines`,
`generalizes`, `specializes`, `instance_of`.

## Round-tripping

Each block serializes with a `type` discriminator, so a saved document reloads
every block back into its specific class. The document model exposes a JSON
Schema via `MathDocument.model_json_schema()`.
