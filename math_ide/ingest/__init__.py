"""Ingestion package: Docling JSON dict -> math-document block tree.

This is stage 1 of ingestion (synchronous, offline, deterministic). It turns a
Docling-style ``export_to_dict()`` mapping into a :class:`MathDocument` whose
``blocks`` tree is fully populated:

* ``section_header`` -> :class:`~math_ide.schema.Section`
* plain ``text`` -> :class:`~math_ide.schema.Paragraph`, or a typed formal block
  (:class:`Definition`/:class:`Theorem`/...) with optional preamble (#4)
* ``formula`` -> :class:`~math_ide.schema.Formula` stub with ``orig_fallback``
  set immediately and a symbol index (#5/#6)

Occurrences, concepts and relations are filled by a later wave; they are left
empty here and ``ingestion_state`` is set to ``"structure_ready"``.

Public entry point: :func:`build_math_document`.
"""

from __future__ import annotations

from typing import Any, Optional

from math_ide.schema import MathDocument, slugify
from math_ide.ingest.docling_adapter import blocks_from_docling, source_provenance

__all__ = ["build_math_document"]


def _default_document_id(docling: dict[str, Any]) -> str:
    """Derive a stable document id from the Docling dict.

    Prefers the document ``name``, then the source filename stem, then a
    constant. Always slugified so it is a safe id-namespace segment.
    """
    name = docling.get("name")
    if not name:
        origin = docling.get("origin") or {}
        filename = origin.get("filename") or ""
        name = filename.rsplit("/", 1)[-1]
        if "." in name:
            name = name.rsplit(".", 1)[0]
    return slugify(name or "doc")


def build_math_document(
    docling: dict[str, Any],
    *,
    document_id: Optional[str] = None,
) -> MathDocument:
    """Build a :class:`MathDocument` block tree from a Docling JSON dict.

    ``document_id`` defaults to a slug derived from the Docling ``name`` /
    source filename. The returned document has its ``blocks`` populated and
    ``ingestion_state == "structure_ready"``; the occurrence/concept/relation
    indices are intentionally empty (filled by a later ingestion wave).
    """
    doc_id = document_id or _default_document_id(docling)
    blocks = blocks_from_docling(docling, doc_id)
    return MathDocument(
        document_id=doc_id,
        source=source_provenance(docling),
        blocks=blocks,
        ingestion_state="structure_ready",
    )
