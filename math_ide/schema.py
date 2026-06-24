"""Canonical math-document schema (Pydantic v2).

This module is the single source of truth for the Math IDE's in-memory and
on-disk representation. Other components (ingestion, ontology, renderer,
pipeline) import these models and never redefine their shapes.

The math document is a tree of typed *blocks*. Formal environments
(``Definition``, ``Theorem``, ``Lemma``, ``Corollary``, ``Proof``,
``Example``, ``Remark``) are *distinct classes* — not a single block with a
``kind`` enum — so that downstream code can dispatch on type. Block JSON
carries a ``type`` discriminator so a serialized tree round-trips back to the
correct class via a tagged (discriminated) union.

Parallel indices live alongside the tree: ``occurrences`` (surface
appearances of notation), ``concepts`` (canonical mathematical objects), and
``relations`` (structural + semantic edges between concepts).

All identifiers are document-namespaced; use :func:`mint_id` to build them.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CoordOrigin",
    "BBox",
    "SymbolSpan",
    "Block",
    "BlockBase",
    "Section",
    "Paragraph",
    "FormalBlock",
    "Definition",
    "Theorem",
    "Lemma",
    "Corollary",
    "Proof",
    "Example",
    "Remark",
    "Formula",
    "EnrichmentStatus",
    "Occurrence",
    "OccurrenceKind",
    "Concept",
    "ResolutionStatus",
    "Relation",
    "RelationKind",
    "RelationOrigin",
    "SourceProvenance",
    "IngestionState",
    "MathDocument",
    "mint_id",
    "slugify",
]


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Return a lowercase, hyphen-separated slug suitable for an id segment.

    Non-ASCII letters common in German maths (umlauts, sharp s) are folded to
    their ASCII forms so concept slugs stay stable and url-friendly.
    """
    folded = (
        value.strip()
        .lower()
        .replace("ä", "ae")  # ä
        .replace("ö", "oe")  # ö
        .replace("ü", "ue")  # ü
        .replace("ß", "ss")  # ß
    )
    slug = _SLUG_RE.sub("-", folded).strip("-")
    return slug or "x"


def mint_id(document_id: str, kind: str, key: str) -> str:
    """Mint a document-namespaced identifier.

    Format: ``{document_id}#{kind}/{slugified key}``. ``kind`` is a short
    namespace label such as ``block``, ``occ``, ``concept`` or ``relation``;
    ``key`` is a per-kind locally-unique key (an index, a defined name, ...).

    >>> mint_id("doc1", "block", "Definition 1.1")
    'doc1#block/definition-1-1'
    """
    return f"{document_id}#{kind}/{slugify(key)}"


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

CoordOrigin = Literal["BOTTOMLEFT", "TOPLEFT"]


class BBox(BaseModel):
    """An axis-aligned bounding box on a single page.

    Coordinates mirror Docling's ``prov.bbox``: ``l``/``t``/``r``/``b`` with a
    ``coord_origin`` that says where ``(0, 0)`` sits. Used for both *source
    bbox* (PDF page space, from ingestion) and *render bbox* (rendered-document
    space, filled in at layout time).
    """

    model_config = ConfigDict(extra="forbid")

    l: float
    t: float
    r: float
    b: float
    coord_origin: CoordOrigin = "BOTTOMLEFT"
    page_no: Optional[int] = None


# ---------------------------------------------------------------------------
# Formula symbol index
# ---------------------------------------------------------------------------

SymbolKind = Literal["variable", "function", "constant", "operator", "set", "other"]


class SymbolSpan(BaseModel):
    """An identifier span inside a formula's canonical content string.

    ``start``/``end`` are character offsets into whichever string is currently
    canonical for the formula (``latex`` when enrichment is ready, otherwise
    ``orig_fallback``). ``token`` is the surface identifier (e.g. ``f``,
    ``a_n``, ``\\varepsilon``).
    """

    model_config = ConfigDict(extra="forbid")

    token: str
    start: int
    end: int
    kind: SymbolKind = "variable"


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

EnrichmentStatus = Literal["pending", "ready", "failed"]


class BlockBase(BaseModel):
    """Fields shared by every block in the math-document tree.

    ``id`` is document-namespaced. ``source_bbox``/``page_no`` locate the block
    in the source PDF and are nullable because not every block has reliable
    provenance (e.g. blocks synthesised by a preamble split).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    source_bbox: Optional[BBox] = None
    page_no: Optional[int] = None


class Section(BlockBase):
    """A structural heading and the blocks nested beneath it."""

    type: Literal["Section"] = "Section"
    title: str
    children: list["Block"] = Field(default_factory=list)


class Paragraph(BlockBase):
    """A run of prose. May carry citation occurrences and nested blocks."""

    type: Literal["Paragraph"] = "Paragraph"
    text: str
    children: list["Block"] = Field(default_factory=list)


class FormalBlock(BlockBase):
    """Common shape for numbered/labelled mathematical environments.

    Concrete subclasses (``Definition`` etc.) only set the ``type``
    discriminator. ``preamble`` holds leading prose absorbed from the same
    Docling text node as the formal label.
    """

    number: Optional[str] = None
    defined_name: Optional[str] = None
    body: str = ""
    preamble: Optional[str] = None


class Definition(FormalBlock):
    type: Literal["Definition"] = "Definition"


class Theorem(FormalBlock):
    type: Literal["Theorem"] = "Theorem"


class Lemma(FormalBlock):
    type: Literal["Lemma"] = "Lemma"


class Corollary(FormalBlock):
    type: Literal["Corollary"] = "Corollary"


class Proof(FormalBlock):
    type: Literal["Proof"] = "Proof"


class Example(FormalBlock):
    type: Literal["Example"] = "Example"


class Remark(FormalBlock):
    type: Literal["Remark"] = "Remark"


class Formula(BlockBase):
    """A math region.

    ``orig_fallback`` always holds Docling's linearized ``orig`` text so
    occurrences are extractable before LaTeX enrichment. ``latex`` is populated
    when ``enrichment_status`` becomes ``ready``; the symbol index is rebuilt
    against whichever string is canonical.
    """

    type: Literal["Formula"] = "Formula"
    latex: Optional[str] = None
    orig_fallback: str = ""
    enrichment_status: EnrichmentStatus = "pending"
    symbol_index: list[SymbolSpan] = Field(default_factory=list)

    @property
    def canonical_content(self) -> str:
        """The string the ``symbol_index`` offsets index into."""
        if self.enrichment_status == "ready" and self.latex is not None:
            return self.latex
        return self.orig_fallback


# Tagged union over every concrete block class. Pydantic uses the ``type``
# field to round-trip serialized blocks back to the right class.
Block = Annotated[
    Union[
        Section,
        Paragraph,
        Definition,
        Theorem,
        Lemma,
        Corollary,
        Proof,
        Example,
        Remark,
        Formula,
    ],
    Field(discriminator="type"),
]

# Resolve the forward references used by the recursive ``children`` fields.
Section.model_rebuild()
Paragraph.model_rebuild()


# ---------------------------------------------------------------------------
# Occurrences
# ---------------------------------------------------------------------------

OccurrenceKind = Literal["formula_symbol", "defined_name", "citation"]


class Occurrence(BaseModel):
    """A single surface appearance of mathematical notation at one location.

    Three import-time kinds: a symbol inside a formula, the defined name in a
    formal block's label, or an explicit numbered citation. Each carries its
    own *source bbox* (always set when known) and *render bbox* (``None`` until
    layout). ``concept_id`` is ``None`` until meaning resolution;
    ``target_block_id`` is set for citation occurrences pointing at the cited
    formal block.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: OccurrenceKind
    block_id: str
    span: Optional[tuple[int, int]] = None
    source_bbox: Optional[BBox] = None
    render_bbox: Optional[BBox] = None
    concept_id: Optional[str] = None
    target_block_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Concepts
# ---------------------------------------------------------------------------

ResolutionStatus = Literal["pending", "resolved"]


class Concept(BaseModel):
    """A canonical mathematical object in the document's ontology.

    ``id`` is ``{document_id}#{slug}``. ``canonical_concept_id`` is reserved
    for cross-document merging (unused in v1). ``formal_meaning`` comes from a
    formal block and is authoritative — meaning resolution may set
    ``inferred_meaning`` but must never overwrite ``formal_meaning``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    canonical_concept_id: Optional[str] = None
    name: str
    formal_meaning: Optional[str] = None
    inferred_meaning: Optional[str] = None
    resolution_status: ResolutionStatus = "pending"
    defining_occurrence_id: Optional[str] = None
    seeded_by_block_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------

RelationOrigin = Literal["structural", "semantic"]
RelationKind = Literal[
    # structural (deterministic, assigned at import)
    "seeded_by",
    "sibling",
    "co_occurring",
    # semantic (assigned by the LLM during meaning resolution)
    "uses",
    "defines",
    "generalizes",
    "specializes",
    "instance_of",
]


class Relation(BaseModel):
    """A directed edge between two concepts (or, for ``seeded_by``, a concept
    and the formal block that introduced it).

    ``origin`` separates deterministic structural edges from LLM-inferred
    semantic edges. For ``seeded_by`` the target is a block id; set
    ``target_is_block`` so consumers know not to look it up as a concept.
    """

    model_config = ConfigDict(extra="forbid")

    source_concept_id: str
    target_concept_id: str
    kind: RelationKind
    origin: RelationOrigin
    target_is_block: bool = False


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

DocOrigin = Literal["pdf", "docling_json", "synthetic"]


class SourceProvenance(BaseModel):
    """Where the math document came from."""

    model_config = ConfigDict(extra="forbid")

    origin: DocOrigin = "pdf"
    binary_hash: Optional[str] = None
    filename: Optional[str] = None
    mimetype: Optional[str] = None


IngestionState = Literal[
    "ingesting",
    "structure_ready",
    "resolving",
    "ready",
]


class MathDocument(BaseModel):
    """The canonical math-centric representation of a source document.

    A tree of typed ``blocks`` plus the parallel ``occurrences``/``concepts``/
    ``relations`` indices. ``ingestion_state`` tracks the staged pipeline:
    structure and occurrences are available at ``structure_ready``; meaning
    resolution advances it through ``resolving`` to ``ready``.
    """

    model_config = ConfigDict(extra="forbid")

    document_id: str
    source: SourceProvenance = Field(default_factory=SourceProvenance)
    blocks: list[Block] = Field(default_factory=list)
    occurrences: list[Occurrence] = Field(default_factory=list)
    concepts: list[Concept] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    ingestion_state: IngestionState = "ingesting"

    def mint(self, kind: str, key: str) -> str:
        """Mint a document-namespaced id within this document's namespace."""
        return mint_id(self.document_id, kind, key)


MathDocument.model_rebuild()
