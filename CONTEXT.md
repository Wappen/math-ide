# Math IDE

A system that ingests mathematical PDFs and makes their content navigable: users interact with the document to jump between definitions, formulas, and the places those concepts are used.

## Language

**Math IDE**:
The interactive application that presents a converted mathematical document and lets users explore it by clicking symbols, formulas, and defined concepts.
_Avoid_: Viewer, reader

**Source document**:
The original PDF that was ingested. It is the authoritative input, but not what the user reads on screen.
_Avoid_: Input file, raw PDF

**Rendered document**:
The structured view the Math IDE displays, rebuilt from parsed content rather than painted from PDF pages.
_Avoid_: PDF view, page overlay

**Math document**:
The canonical math-centric representation of a source document. A tree of typed blocks — Definition, Theorem, Lemma, Corollary, Proof, Example, Remark, Section, Paragraph, Formula, etc. — each carrying content and location. Occurrences and concepts index into blocks; the Math IDE renders from this tree, not from Docling output directly.
_Avoid_: Parsed output, conversion result

**Block**:
A typed node in the math document tree. Formal environments (Definition, Theorem, …) are distinct block types, not a shared FormalBlock with a kind label.
_Avoid_: Node, element, chunk

**Formula**:
A math document block containing a LaTeX string for rendering plus a symbol index — identifier spans within that LaTeX — used to create occurrences and place render bboxes. When LaTeX enrichment is pending, falls back to Docling's linearized `orig` text for immediate occurrence extraction; upgrades in place when enrichment completes.
_Avoid_: Equation, math region

**Concept**:
A canonical mathematical object in the ontology — the thing that `f`, `L`, or `ε` denotes when two occurrences refer to the same object. Carries formal and/or inferred meaning; may be seeded by a formal block. Identified by a document-namespaced ID; may carry an optional `canonical_concept_id` for future cross-document merging (unused in v1).
_Avoid_: Term, entity, token

**Occurrence**:
A single surface appearance of mathematical notation at a specific document location. Three kinds at import time: a symbol inside a formula, the defined name in a formal block's label, or an explicit numbered citation (e.g. `Definition 1.1`). Each occurrence has its own render bbox and source bbox, and resolves to exactly one concept.
_Avoid_: Token, mention, site

**Citation occurrence**:
An occurrence whose surface text is an explicit numbered cross-reference (e.g. `Definition 1.1`, `Satz 2.3`). Resolves deterministically to the cited formal block without LLM involvement.
_Avoid_: Cross-ref, link

**Ontology**:
The full set of concepts extracted from a single source document, together with their meanings, defining occurrences, and references. Document-local in v1; the schema should not preclude merging ontologies across related source documents later.
_Avoid_: Knowledge graph, taxonomy

**Ingestion**:
The pipeline that reads a source document and produces a math document. Runs in stages: structure and occurrences are available immediately; meaning resolution continues asynchronously in the background.
_Avoid_: Conversion, parsing (when meaning the whole pipeline)

**Meaning resolution**:
The asynchronous stage where an LLM assigns occurrences to concepts and propagates inferred meaning from formal seeds. Cannot override formal meaning.
_Avoid_: Disambiguation, NLP tagging

**Formal meaning**:
The meaning of a concept as stated in a numbered definition, theorem, or similarly labelled block. Authoritative — LLM inference cannot override it.
_Avoid_: Literal definition, official meaning

**Inferred meaning**:
The meaning an LLM assigns to a concept from surrounding context and coreference. Fills gaps where no formal block exists; propagates from formal seeds but does not contradict them.
_Avoid_: Guessed meaning, AI interpretation

**Formal block**:
A numbered or labelled mathematical environment that seeds one or more concepts in the ontology. Realised as a typed block in the math document (Definition, Theorem, Lemma, Corollary, …). May include an optional preamble — leading prose absorbed from the same Docling text node as the formal label.
_Avoid_: Environment, declaration

**Render bbox**:
The bounding box of an occurrence in the rendered document's coordinate space. Canonical for user interaction in the Math IDE.
_Avoid_: Display box, hit target

**Source bbox**:
The bounding box of the corresponding content in the source document's PDF page coordinates, as reported by ingestion. Used for provenance and validation, not primary interaction.
_Avoid_: PDF box, original bbox

**Reference**:
An occurrence that is not the defining occurrence of its concept — a later use that points back to the concept's definition.
_Avoid_: Link, mention

**Defining occurrence**:
The occurrence where a concept is introduced — typically the defined name in a formal block's label, or the first binding site the LLM identifies for symbols without a formal block.
_Avoid_: Definition site, origin

## Interaction

**Go to definition** (left click):
Navigate the rendered document to the best available definition target: formal block first, then defined name in the label, then the LLM-assigned defining occurrence. Disabled with a "resolving…" state until a target exists. Citation occurrences navigate directly to the cited formal block.
_Avoid_: Jump, follow link

**Show references** (right click):
Open a concept card in the side panel: formal and inferred meaning, resolution status, the defining occurrence, all reference occurrences, and a neighbourhood of related concepts the LLM identified.
_Avoid_: Show usages, find references

**Related concept**:
Another concept linked to the current one. Structural relations (seeded_by, sibling, co_occurring) are deterministic at import; semantic relations (uses, defines, generalizes, specializes, instance_of) are assigned by the LLM and shown as inferred in the concept card.
_Avoid_: Dependency, associated term
