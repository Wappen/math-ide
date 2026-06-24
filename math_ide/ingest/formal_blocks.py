"""Formal-block detection with preamble split (issue #4).

Docling frequently merges a formal label into a plain ``text`` node, sometimes
with leading prose, e.g.::

    "Ein wichtiges Konzept ... ist die Injektivitaet. Definition 1.2
     (Injektivitaet): Eine Abbildung f: X -> Y heisst injektiv, wenn ..."

We detect the formal label (German + English spellings), split the node into an
optional leading *preamble* (prose before the label) plus the formal block
itself, and map it to the matching distinct schema class
(:class:`Definition`, :class:`Theorem`, ...). Source bboxes for the preamble vs.
the block are estimated with the char-span subdivision helper from
:mod:`math_ide.ingest.docling_adapter`.

A node with no formal label becomes a plain :class:`Paragraph`.

Label grammar (v1)
------------------
``<Keyword> <number>? (<DefinedName>)? <separator>? <body>`` where

* ``Keyword`` is one of the German/English environment names below;
* ``number`` is ``X`` / ``X.Y`` / ``X.Y.Z`` (dotted, digits);
* ``DefinedName`` is the parenthesised name being defined (optional);
* ``separator`` is ``:`` / ``.`` / ``--`` (optional);
* ``body`` is the rest of the node text.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Type

from math_ide.schema import (
    Block,
    Corollary,
    Definition,
    Example,
    FormalBlock,
    Lemma,
    Paragraph,
    Proof,
    Remark,
    Theorem,
    mint_id,
)
from math_ide.ingest.docling_adapter import bbox_from_prov, subdivide_bbox

__all__ = [
    "KEYWORD_TO_CLASS",
    "FormalMatch",
    "match_formal_label",
    "blocks_from_text_node",
]


# Map each surface keyword (lowercased) to its distinct schema class. German and
# English spellings both point at the SAME distinct class (never a shared enum).
KEYWORD_TO_CLASS: dict[str, Type[FormalBlock]] = {
    "definition": Definition,
    "theorem": Theorem,
    "satz": Theorem,
    "lemma": Lemma,
    "corollary": Corollary,
    "folgerung": Corollary,
    "korollar": Corollary,
    "proof": Proof,
    "beweis": Proof,
    "example": Example,
    "beispiel": Example,
    "remark": Remark,
    "bemerkung": Remark,
}

# Alternation of keywords, longest first so "definition" wins before any prefix.
_KEYWORDS = sorted(KEYWORD_TO_CLASS, key=len, reverse=True)
_KEYWORD_ALT = "|".join(re.escape(k) for k in _KEYWORDS)

# A formal label anywhere in the text. A leading ``\b`` keeps us off mid-word
# matches; a trailing ``(?![^\W\d_])`` (next char is not a unicode letter) keeps
# a keyword from matching as a *prefix* of a longer word ("Definitionen",
# "Beweise", "Satzbau", "Lemmata"). We capture the optional dotted number,
# optional parenthesised defined name and an optional separator that *introduces
# a body* (colon / en-dash / em-dash / "--"). A bare ``-`` is deliberately NOT a
# separator: a hyphenated compound starting with a keyword ("Lemma-Verfahren",
# "Definitions-Bereich") is prose, not a header. A bare ``.`` is likewise NOT a
# body separator: it ends sentences and would turn prose citations
# ("... siehe Definition 1.1.") into false blocks.
_LABEL_RE = re.compile(
    r"\b(?P<keyword>" + _KEYWORD_ALT + r")(?![^\W\d_])"
    r"(?:\s+(?P<number>\d+(?:\.\d+)*))?"
    r"(?:\s*\((?P<name>[^)]*)\))?"
    r"\s*(?P<sep>:|–|—|--)?",
    re.IGNORECASE,
)


class FormalMatch:
    """Result of locating a formal label inside a text node.

    Attributes mirror what a typed formal block needs plus the char offsets
    used to split the source node and subdivide its bbox.
    """

    __slots__ = (
        "block_class",
        "keyword",
        "number",
        "defined_name",
        "label_start",
        "body_start",
    )

    def __init__(
        self,
        block_class: Type[FormalBlock],
        keyword: str,
        number: Optional[str],
        defined_name: Optional[str],
        label_start: int,
        body_start: int,
    ) -> None:
        self.block_class = block_class
        self.keyword = keyword
        self.number = number
        self.defined_name = defined_name
        self.label_start = label_start  # index where the keyword begins
        self.body_start = body_start  # index where the body begins (after sep)


def match_formal_label(text: str) -> Optional[FormalMatch]:
    """Find the first formal label in ``text``, or ``None``.

    The label may be preceded by prose (the preamble); the part before
    ``label_start`` is that preamble. Everything from ``body_start`` on is the
    block body.
    """
    for m in _LABEL_RE.finditer(text):
        keyword = m.group("keyword").lower()
        block_class = KEYWORD_TO_CLASS.get(keyword)
        if block_class is None:  # pragma: no cover - alternation is exhaustive
            continue
        # Distinguish a block *header* from a prose *citation* ("Nach
        # Definition 1.1 ist ..."). A header either (a) introduces a body via a
        # separator (":" / dash), (b) names what it defines via "(Name)", or
        # (c) opens the node (label at the start, optional whitespace before).
        # A bare number alone is NOT enough — that is exactly the citation case.
        at_start = m.start() == 0 or text[: m.start()].strip() == ""
        is_header = bool(m.group("sep") or m.group("name")) or at_start
        if not is_header:
            continue
        name = m.group("name")
        return FormalMatch(
            block_class=block_class,
            keyword=keyword,
            number=m.group("number"),
            defined_name=name.strip() if name else None,
            label_start=m.start(),
            body_start=m.end(),
        )
    return None


def blocks_from_text_node(
    document_id: str,
    node: dict[str, Any],
    index: int,
) -> list[Block]:
    """Turn one Docling text node into one or more blocks.

    * No formal label -> a single :class:`Paragraph`.
    * Formal label with no leading prose -> the typed formal block only.
    * Formal label with leading prose -> a :class:`Paragraph` preamble *inside*
      the formal block's ``preamble`` field (a single block), as required by the
      schema's ``FormalBlock.preamble``.

    Bboxes for preamble vs. body are estimated by char-span subdivision of the
    node's full bbox.
    """
    text = node.get("text") or node.get("orig") or ""
    prov = (node.get("prov") or [{}])[0]
    bbox = bbox_from_prov(prov)
    page_no = prov.get("page_no")
    charspan = prov.get("charspan")

    match = match_formal_label(text)
    if match is None:
        return [
            Paragraph(
                id=mint_id(document_id, "block", f"para-{index}-{text[:24]}"),
                text=text,
                source_bbox=bbox,
                page_no=page_no,
            )
        ]

    preamble_text = text[: match.label_start].strip()
    body_text = text[match.body_start :].strip()

    # Estimate the formal block's bbox: it spans from the label start to the end
    # of the node. The charspan is node-local ([c0, c1)); offsets within `text`
    # map to charspan via c0 + offset.
    c0 = int(charspan[0]) if charspan else 0
    block_bbox = subdivide_bbox(
        bbox, charspan, c0 + match.label_start, c0 + len(text)
    )

    key = match.defined_name or match.number or match.keyword
    block = match.block_class(
        id=mint_id(document_id, "block", f"{match.keyword}-{index}-{key}"),
        number=match.number,
        defined_name=match.defined_name,
        body=body_text,
        preamble=preamble_text or None,
        source_bbox=block_bbox,
        page_no=page_no,
    )
    return [block]
