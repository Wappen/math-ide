"""Docling-JSON -> math-document block adapter (issue #3).

This module turns a Docling-style ``export_to_dict()`` mapping into the
math-document *block tree* (sections, paragraphs, formula stubs). Formal-block
detection (#4) and formula symbol indexing (#6) live in sibling modules and are
invoked from here so the adapter produces a complete first-stage tree.

Docling-JSON subset we consume
------------------------------
We rely on a small, stable subset of the Docling document dict::

    {
      "origin": {"mimetype": str, "binary_hash": str, "filename": str},
      "body":   {"children": [{"$ref": "#/texts/0"}, ...]},   # reading order
      "texts": [
        {
          "self_ref": "#/texts/0",
          "label": "section_header" | "text" | "formula" | ...,
          "level": int,            # section_header only (unused for now)
          "text": str,             # rendered text; "" for un-enriched formulas
          "orig": str,             # linearized source text (formula fallback)
          "prov": [
            {
              "page_no": int,
              "bbox": {"l","t","r","b","coord_origin"},
              "charspan": [start, end]
            }
          ]
        },
        ...
      ]
    }

Only ``body.children`` reading order, each text node's ``label``/``text``/
``orig`` and the *first* ``prov`` entry (``page_no``, ``bbox``, ``charspan``)
are used. Other top-level keys (``groups``, ``pictures``, ``tables`` ...) and
extra node fields are ignored. Unknown labels fall back to ``Paragraph``.

Provenance: ``origin`` is mapped onto a :class:`SourceProvenance` with
``origin="docling_json"`` (the math document was built from a Docling dict, not
re-converted from the PDF in this process).
"""

from __future__ import annotations

from typing import Any, Optional

from math_ide.schema import (
    BBox,
    Block,
    Paragraph,
    Section,
    SourceProvenance,
)
from math_ide.ingest.formula import build_formula

__all__ = [
    "bbox_from_prov",
    "subdivide_bbox",
    "source_provenance",
    "blocks_from_docling",
]


# ---------------------------------------------------------------------------
# Provenance & geometry
# ---------------------------------------------------------------------------


def source_provenance(docling: dict[str, Any]) -> SourceProvenance:
    """Build a :class:`SourceProvenance` from the Docling ``origin`` block.

    The math document was assembled from a Docling JSON dict, so ``origin`` is
    fixed to ``"docling_json"`` regardless of the underlying source mimetype
    (which we still preserve verbatim).
    """
    origin = docling.get("origin") or {}
    return SourceProvenance(
        origin="docling_json",
        binary_hash=origin.get("binary_hash"),
        filename=origin.get("filename"),
        mimetype=origin.get("mimetype"),
    )


def bbox_from_prov(prov: dict[str, Any]) -> Optional[BBox]:
    """Build a :class:`BBox` from a single Docling ``prov`` entry, or ``None``.

    Carries ``page_no`` onto the bbox so a block's geometry is self-describing.
    """
    raw = prov.get("bbox")
    if not raw:
        return None
    return BBox(
        l=raw["l"],
        t=raw["t"],
        r=raw["r"],
        b=raw["b"],
        coord_origin=raw.get("coord_origin", "BOTTOMLEFT"),
        page_no=prov.get("page_no"),
    )


def subdivide_bbox(
    bbox: Optional[BBox],
    charspan: tuple[int, int] | list[int] | None,
    sub_start: int,
    sub_end: int,
) -> Optional[BBox]:
    """Estimate the sub-bbox for a ``[sub_start, sub_end)`` slice of a node.

    Given a node's full bbox and the node's full ``charspan`` ``[c0, c1)``, we
    linearly interpolate horizontal positions along the box width by character
    offset. This is the cheap single-line approximation reused by the preamble
    split (#4) and later by occurrence placement (#7): it assumes one text line
    and a uniform character pitch, which is good enough for provenance.

    Returns a new :class:`BBox` (same ``t``/``b``/``coord_origin``/``page_no``)
    or ``None`` when there is nothing to interpolate against. The requested
    sub-range is clamped to the node's charspan.
    """
    if bbox is None or not charspan:
        return None
    c0, c1 = int(charspan[0]), int(charspan[1])
    total = c1 - c0
    if total <= 0:
        return bbox.model_copy()

    # clamp the requested slice into the node's charspan
    s = max(c0, min(int(sub_start), c1))
    e = max(c0, min(int(sub_end), c1))
    if e < s:
        s, e = e, s

    width = bbox.r - bbox.l
    left = bbox.l + width * ((s - c0) / total)
    right = bbox.l + width * ((e - c0) / total)
    return BBox(
        l=left,
        t=bbox.t,
        r=right,
        b=bbox.b,
        coord_origin=bbox.coord_origin,
        page_no=bbox.page_no,
    )


# ---------------------------------------------------------------------------
# Block construction
# ---------------------------------------------------------------------------


def _resolve_ref(docling: dict[str, Any], ref: str) -> Optional[dict[str, Any]]:
    """Resolve a ``$ref`` like ``#/texts/3`` to its node dict."""
    if not ref.startswith("#/"):
        return None
    parts = ref[2:].split("/")
    cursor: Any = docling
    for part in parts:
        if isinstance(cursor, list):
            try:
                cursor = cursor[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cursor, dict):
            cursor = cursor.get(part)
        else:
            return None
        if cursor is None:
            return None
    return cursor if isinstance(cursor, dict) else None


def _iter_body_nodes(docling: dict[str, Any]):
    """Yield text nodes in reading order.

    Prefers ``body.children`` ``$ref`` order; falls back to ``texts`` order if
    the body is missing.
    """
    body = docling.get("body") or {}
    children = body.get("children")
    if children:
        for child in children:
            ref = child.get("$ref") if isinstance(child, dict) else None
            if not ref:
                continue
            node = _resolve_ref(docling, ref)
            if node is not None:
                yield node
        return
    for node in docling.get("texts", []):
        yield node


def _make_section(document_id: str, node: dict[str, Any], index: int) -> Section:
    prov = (node.get("prov") or [{}])[0]
    bbox = bbox_from_prov(prov)
    title = node.get("text") or node.get("orig") or ""
    return Section(
        id=_block_id(document_id, "section", title, index),
        title=title,
        source_bbox=bbox,
        page_no=prov.get("page_no"),
    )


def _make_formula(document_id: str, node: dict[str, Any], index: int) -> Block:
    prov = (node.get("prov") or [{}])[0]
    bbox = bbox_from_prov(prov)
    orig = node.get("orig") or ""
    return build_formula(
        _block_id(document_id, "formula", orig, index),
        orig=orig,
        text=node.get("text") or "",
        source_bbox=bbox,
        page_no=prov.get("page_no"),
    )


def _block_id(document_id: str, kind: str, key: str, index: int) -> str:
    from math_ide.schema import mint_id

    # disambiguate with the reading-order index so ids stay unique even when two
    # nodes share a key.
    return mint_id(document_id, "block", f"{kind}-{index}-{key}")


def blocks_from_docling(
    docling: dict[str, Any],
    document_id: str,
    *,
    detect_formal: bool = True,
) -> list[Block]:
    """Build the top-level block list from a Docling dict.

    ``section_header`` nodes start a new :class:`Section`; subsequent
    non-heading blocks nest under the most recent section. Plain ``text`` nodes
    become :class:`Paragraph` blocks unless ``detect_formal`` lets the
    formal-block splitter (#4) turn them into a typed formal block (+ optional
    preamble). ``formula`` nodes become :class:`Formula` stubs.
    """
    # Imported lazily to avoid an import cycle (formal_blocks uses this module's
    # subdivide_bbox / bbox helpers).
    from math_ide.ingest.formal_blocks import blocks_from_text_node

    roots: list[Block] = []
    current_section: Optional[Section] = None

    def emit(block: Block) -> None:
        if current_section is not None:
            current_section.children.append(block)
        else:
            roots.append(block)

    for index, node in enumerate(_iter_body_nodes(docling)):
        label = node.get("label")
        if label == "section_header":
            section = _make_section(document_id, node, index)
            roots.append(section)
            current_section = section
        elif label == "formula":
            emit(_make_formula(document_id, node, index))
        else:
            # plain text (or unknown label) -> paragraph / formal block(s)
            if detect_formal:
                for block in blocks_from_text_node(document_id, node, index):
                    emit(block)
            else:
                emit(_make_paragraph(document_id, node, index))

    return roots


def _make_paragraph(document_id: str, node: dict[str, Any], index: int) -> Paragraph:
    prov = (node.get("prov") or [{}])[0]
    bbox = bbox_from_prov(prov)
    text = node.get("text") or node.get("orig") or ""
    return Paragraph(
        id=_block_id(document_id, "para", text[:24], index),
        text=text,
        source_bbox=bbox,
        page_no=prov.get("page_no"),
    )
