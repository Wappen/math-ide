"""Math IDE — ingest mathematical PDFs into a navigable math document.

This package exposes the canonical :mod:`math_ide.schema` models as its public
surface so callers can ``from math_ide import MathDocument, Definition, ...``.
"""

from __future__ import annotations

from math_ide.schema import (
    BBox,
    Block,
    BlockBase,
    Concept,
    Corollary,
    Definition,
    Example,
    FormalBlock,
    Formula,
    Lemma,
    MathDocument,
    Occurrence,
    Paragraph,
    Proof,
    Relation,
    Remark,
    Section,
    SourceProvenance,
    SymbolSpan,
    Theorem,
    mint_id,
    slugify,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "BBox",
    "Block",
    "BlockBase",
    "Concept",
    "Corollary",
    "Definition",
    "Example",
    "FormalBlock",
    "Formula",
    "Lemma",
    "MathDocument",
    "Occurrence",
    "Paragraph",
    "Proof",
    "Relation",
    "Remark",
    "Section",
    "SourceProvenance",
    "SymbolSpan",
    "Theorem",
    "mint_id",
    "slugify",
]
