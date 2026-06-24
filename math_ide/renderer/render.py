"""Render a :class:`~math_ide.schema.MathDocument` to interactive HTML.

This module produces the *rendered document*: a structured HTML view rebuilt
from the parsed block tree (never painted from PDF pages). Formulas are
rendered client-side by KaTeX (loaded from a CDN); occurrences become
focusable hit targets carrying the data attributes the IDE wave needs.

================================================================================
DOM CONVENTIONS (CONTRACT — the IDE wave depends on these)
================================================================================
The renderer emits a stable DOM vocabulary. Downstream waves (#11 render-bbox
measurement, #12 go-to-definition, #13 concept card) query these selectors.

Scroll container
  <main class="math-doc-scroll">                 the scrollable navigation root
    <article class="math-doc" data-document-id="…"> document wrapper

Every rendered block carries BOTH an ``id`` and a ``data-block-id`` equal to the
block's schema id, so go-to-definition can ``getElementById`` / scroll to it:
  id="<block_id>" data-block-id="<block_id>"

Block element types and classes
  Section    -> <section class="block section">
                  child <h{level} class="section-title"> + nested blocks
  Paragraph  -> <p class="block paragraph">
  Formula    -> <div class="block formula" data-enrichment="ready|pending|failed">
                  ready:  <span class="katex-target" data-latex="…"
                                data-occurrences='[{"token","attrs"}, …]'></span>
                          <span class="occ-fallback">…inline .occ anchored
                                linearized text…</span>
                          (DECOUPLED — see "Ready-formula DOM contract" below)
                  else:   <span class="formula-fallback">…inline .occ anchored
                                orig_fallback…</span>
  Formal     -> <div class="block formal {type-lower}"
                       data-formal-type="Definition|Theorem|…">
                  <div class="formal-header">Definition 1.2 (Injektivitaet)</div>
                  <p class="formal-preamble">…</p>      (only when preamble set)
                  <div class="formal-body">…</div>
                The {type-lower} class (e.g. "definition", "theorem") drives the
                per-type visual styling in styles.css.

Occurrence anchors (hit targets)
  <span class="occ"
        data-occurrence-id="<occ.id>"
        data-concept-id="<occ.concept_id or ''>"
        data-kind="formula_symbol|defined_name|citation"
        data-target-block-id="<occ.target_block_id>"   (citations only)
        data-resolvable="false"                          (only when no target yet)
        tabindex="0">…surface text…</span>
  Occurrences are anchored by their ``span`` into a *kind-specific* canonical
  string:
    formula_symbol -> the formula's ``canonical_content``
    defined_name   -> the formal block's header line
    citation       -> the paragraph's ``text``
  Spans are applied left-to-right; overlapping spans are skipped to keep text
  intact. All surrounding text is HTML-escaped.
  ``data-resolvable="false"`` marks an occurrence whose go-to-definition target
  is not known yet (``navigation.definition_target`` is ``None``) — the IDE
  shows it as a disabled "resolving…" affordance. The attribute is omitted when
  a target exists, so the default state is resolvable.

Ready-formula DOM contract (KaTeX typesetting + surviving symbol targets)
  A ``ready`` Formula DECOUPLES the typeset math from the per-symbol hit targets
  so KaTeX can own a dedicated typeset node WITHOUT deleting the occurrence
  anchors (KaTeX's ``katex.render`` replaces its host's children). A ready
  formula emits TWO siblings inside ``.block.formula``:

    <span class="katex-target" data-latex="<latex>"
          data-occurrences='[{ "token": "f",
                               "attrs": "data-occurrence-id=… data-concept-id=…
                                         data-kind=formula_symbol …" }, …]'>
    </span>                                  (empty; KaTeX renders here)
    <span class="occ-fallback">…the SAME inline-anchored linearized text the
          pending path emits, each symbol wrapped as <span class="occ">…</span>

  ``app.js`` renders ``data-latex`` into ``.katex-target`` then best-effort
  matches each ``data-occurrences`` token to the KaTeX glyph span(s) it produced
  (KaTeX wraps identifiers in ``.mord`` spans), TAGGING the matched glyph span
  with ``class="occ"`` + the token's ``attrs``. When every token matches it
  hides ``.occ-fallback`` (the glyph ``.occ`` targets take over); any token that
  cannot be matched keeps its visible ``.occ-fallback`` anchor. With no JS / no
  KaTeX the visible ``.occ-fallback`` is the working hit-target layer. Either
  way each symbol target is strictly SMALLER than the whole-formula box.
  ``data-occurrences`` is ``[]`` (and ``.occ-fallback`` absent) when the formula
  has no symbol occurrences.

Embedded navigation payload (the IDE wave depends on this)
  <script type="application/json" id="math-ide-data">…</script>
  A JSON blob (``navigation.build_ide_payload``) embedded near ``</body>``
  before ``app.js``. It carries, per occurrence, its precomputed
  ``definition_target`` plus the concepts, relations and concept cards, so
  ``app.js`` navigates and builds cards WITHOUT recomputing any logic.
================================================================================
"""

from __future__ import annotations

import json
from html import escape
from typing import Iterable, Optional

from math_ide.renderer.navigation import build_ide_payload, definition_target
from math_ide.schema import (
    Block,
    Formula,
    FormalBlock,
    MathDocument,
    Occurrence,
    Paragraph,
    Section,
)

__all__ = ["render_document", "render_block"]

_KATEX_VERSION = "0.16.9"
_KATEX_CSS = (
    f"https://cdn.jsdelivr.net/npm/katex@{_KATEX_VERSION}/dist/katex.min.css"
)
_KATEX_JS = (
    f"https://cdn.jsdelivr.net/npm/katex@{_KATEX_VERSION}/dist/katex.min.js"
)

# Human-readable label for each formal block type discriminator.
_FORMAL_LABELS = {
    "Definition": "Definition",
    "Theorem": "Theorem",
    "Lemma": "Lemma",
    "Corollary": "Corollary",
    "Proof": "Proof",
    "Example": "Example",
    "Remark": "Remark",
}


# ---------------------------------------------------------------------------
# Occurrence anchoring
# ---------------------------------------------------------------------------


def _occ_attrs(occ: Occurrence, targets: dict[str, Optional[str]]) -> str:
    """Render the data-attribute string for one occurrence anchor.

    ``targets`` maps occurrence id -> precomputed go-to-definition target block
    id (``None`` while unresolved). When the target is ``None`` the anchor is
    flagged ``data-resolvable="false"`` so the IDE can disable it with a
    "resolving…" cue.
    """
    attrs = [
        ("class", "occ"),
        ("data-occurrence-id", occ.id),
        ("data-concept-id", occ.concept_id or ""),
        ("data-kind", occ.kind),
    ]
    if occ.target_block_id is not None:
        attrs.append(("data-target-block-id", occ.target_block_id))
    if targets.get(occ.id) is None:
        attrs.append(("data-resolvable", "false"))
    rendered = " ".join(f'{k}="{escape(v, quote=True)}"' for k, v in attrs)
    return f"{rendered} tabindex=\"0\""


def _anchor_text(
    text: str,
    occurrences: Iterable[Occurrence],
    targets: dict[str, Optional[str]],
) -> str:
    """Wrap occurrence spans inside ``text`` as ``<span class="occ">`` anchors.

    ``occurrences`` are the occurrences whose ``span`` indexes into ``text``.
    Spans are applied left-to-right; any occurrence whose span is missing,
    out of range, empty, or overlaps an already-consumed region is skipped so
    the surrounding text is never corrupted. Everything is HTML-escaped.
    """
    spans = []
    for occ in occurrences:
        if occ.span is None:
            continue
        start, end = occ.span
        if start < 0 or end > len(text) or start >= end:
            continue
        spans.append((start, end, occ))
    # Left-to-right, longest-first on ties so a tie picks the wider anchor.
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))

    out: list[str] = []
    cursor = 0
    for start, end, occ in spans:
        if start < cursor:  # overlaps a region we already emitted; skip it
            continue
        out.append(escape(text[cursor:start]))
        surface = escape(text[start:end])
        out.append(f"<span {_occ_attrs(occ, targets)}>{surface}</span>")
        cursor = end
    out.append(escape(text[cursor:]))
    return "".join(out)


def _occurrences_for(
    doc: MathDocument, block_id: str, kind: str
) -> list[Occurrence]:
    """Occurrences belonging to ``block_id`` of a given ``kind``."""
    return [
        o
        for o in doc.occurrences
        if o.block_id == block_id and o.kind == kind
    ]


# ---------------------------------------------------------------------------
# Block rendering
# ---------------------------------------------------------------------------


def _block_id_attrs(block: Block) -> str:
    """The ``id`` + ``data-block-id`` pair every rendered block carries."""
    bid = escape(block.id, quote=True)
    return f'id="{bid}" data-block-id="{bid}"'


def _formal_header(block: FormalBlock) -> str:
    """Build the formal block's header line, e.g. ``Definition 1.2 (Name)``.

    Mirrors the canonical text a ``defined_name`` occurrence's span indexes
    into, so the name can be wrapped as an anchor without corrupting the rest.
    """
    label = _FORMAL_LABELS.get(block.type, block.type)
    parts = [label]
    if block.number:
        parts.append(block.number)
    header = " ".join(parts)
    if block.defined_name:
        header = f"{header} ({block.defined_name})"
    return header


def _render_section(
    section: Section,
    doc: MathDocument,
    level: int,
    targets: dict[str, Optional[str]],
) -> str:
    heading = min(level, 6)
    title = escape(section.title)
    children = "".join(
        _render_block(child, doc, level + 1, targets)
        for child in section.children
    )
    return (
        f'<section class="block section" {_block_id_attrs(section)}>'
        f'<h{heading} class="section-title">{title}</h{heading}>'
        f"{children}"
        f"</section>"
    )


def _render_paragraph(
    para: Paragraph,
    doc: MathDocument,
    level: int,
    targets: dict[str, Optional[str]],
) -> str:
    citations = _occurrences_for(doc, para.id, "citation")
    body = _anchor_text(para.text, citations, targets)
    children = "".join(
        _render_block(child, doc, level, targets) for child in para.children
    )
    return (
        f'<p class="block paragraph" {_block_id_attrs(para)}>'
        f"{body}{children}"
        f"</p>"
    )


def _occurrence_tokens(
    text: str,
    occurrences: Iterable[Occurrence],
    targets: dict[str, Optional[str]],
) -> list[dict[str, str]]:
    """The per-symbol token descriptors KaTeX matching reads (``data-occurrences``).

    Mirrors :func:`_anchor_text`'s span filtering/ordering so the JSON list lines
    up exactly with the inline ``.occ-fallback`` anchors. Each entry is
    ``{"token": <surface text>, "attrs": <occ data-attr string>}`` in
    left-to-right span order. ``attrs`` reuses :func:`_occ_attrs` so the glyph
    span ``app.js`` tags gets the identical data attributes as the fallback.
    """
    spans = []
    for occ in occurrences:
        if occ.span is None:
            continue
        start, end = occ.span
        if start < 0 or end > len(text) or start >= end:
            continue
        spans.append((start, end, occ))
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))

    tokens: list[dict[str, str]] = []
    cursor = 0
    for start, end, occ in spans:
        if start < cursor:  # overlaps an already-consumed region; skip it
            continue
        tokens.append({"token": text[start:end], "attrs": _occ_attrs(occ, targets)})
        cursor = end
    return tokens


def _render_formula(
    formula: Formula,
    doc: MathDocument,
    targets: dict[str, Optional[str]],
) -> str:
    enrichment = formula.enrichment_status
    symbols = _occurrences_for(doc, formula.id, "formula_symbol")
    if enrichment == "ready" and formula.latex is not None:
        # Decoupled: KaTeX owns the (initially empty) typeset host; the symbol
        # hit targets live in a sibling .occ-fallback (inline-anchored), and the
        # per-symbol token descriptors ride along as data-occurrences so app.js
        # can re-attach .occ targets onto the rendered KaTeX glyphs.
        tokens = _occurrence_tokens(formula.canonical_content, symbols, targets)
        data_occurrences = escape(json.dumps(tokens, ensure_ascii=False), quote=True)
        host = (
            f'<span class="katex-target" '
            f'data-latex="{escape(formula.latex, quote=True)}" '
            f'data-occurrences="{data_occurrences}"></span>'
        )
        if tokens:
            inner = _anchor_text(formula.canonical_content, symbols, targets)
            host += f'<span class="occ-fallback">{inner}</span>'
        content = host
    else:
        # Degraded: show the linearized orig fallback, still anchored.
        inner = _anchor_text(formula.canonical_content, symbols, targets)
        content = f'<span class="formula-fallback">{inner}</span>'
    return (
        f'<div class="block formula" data-enrichment="{escape(enrichment, quote=True)}" '
        f"{_block_id_attrs(formula)}>"
        f"{content}"
        f"</div>"
    )


def _render_formal(
    block: FormalBlock,
    doc: MathDocument,
    targets: dict[str, Optional[str]],
) -> str:
    type_class = block.type.lower()
    header_text = _formal_header(block)
    names = _occurrences_for(doc, block.id, "defined_name")
    header = _anchor_text(header_text, names, targets)
    parts = [f'<div class="formal-header">{header}</div>']
    if block.preamble:
        parts.append(
            f'<p class="formal-preamble">{escape(block.preamble)}</p>'
        )
    parts.append(f'<div class="formal-body">{escape(block.body)}</div>')
    return (
        f'<div class="block formal {type_class}" '
        f'data-formal-type="{escape(block.type, quote=True)}" '
        f"{_block_id_attrs(block)}>"
        f"{''.join(parts)}"
        f"</div>"
    )


def _render_block(
    block: Block,
    doc: MathDocument,
    level: int,
    targets: dict[str, Optional[str]],
) -> str:
    if isinstance(block, Section):
        return _render_section(block, doc, level, targets)
    if isinstance(block, Paragraph):
        return _render_paragraph(block, doc, level, targets)
    if isinstance(block, Formula):
        return _render_formula(block, doc, targets)
    if isinstance(block, FormalBlock):
        return _render_formal(block, doc, targets)
    # Defensive: an unknown block type still gets an addressable container.
    return f'<div class="block unknown" {_block_id_attrs(block)}></div>'


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _definition_targets(doc: MathDocument) -> dict[str, Optional[str]]:
    """Precompute every occurrence's go-to-definition target once.

    Used to flag ``data-resolvable="false"`` on anchors with no target yet,
    keeping the rendered DOM consistent with the embedded payload.
    """
    return {occ.id: definition_target(doc, occ) for occ in doc.occurrences}


def render_block(block: Block, doc: MathDocument, level: int = 2) -> str:
    """Render a single block (and its descendants) to an HTML fragment.

    ``doc`` supplies the occurrence index used to place hit-target anchors.
    ``level`` seeds the heading depth for nested sections.
    """
    return _render_block(block, doc, level, _definition_targets(doc))


def render_document(doc: MathDocument) -> str:
    """Render a whole math document to a standalone HTML page.

    The page loads KaTeX from a CDN in ``<head>`` and embeds the IDE navigation
    payload (``navigation.build_ide_payload``) as
    ``<script type="application/json" id="math-ide-data">`` before referencing
    ``app.js`` near ``</body>`` (absence of ``app.js`` is tolerated by the
    browser). A ``<main class="math-doc-scroll">`` wraps the document so
    go-to-definition can scroll within it.
    """
    targets = _definition_targets(doc)
    body = "".join(
        _render_block(block, doc, 2, targets) for block in doc.blocks
    )
    document_id = escape(doc.document_id, quote=True)
    title = escape(doc.source.filename or doc.document_id)
    # The payload is JSON embedded in a <script> element. Escape "<" so a "</"
    # inside any string can never prematurely close the <script> tag.
    payload_json = json.dumps(
        build_ide_payload(doc), ensure_ascii=False
    ).replace("<", "\\u003c")
    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="{_KATEX_CSS}">
<link rel="stylesheet" href="assets/styles.css">
<script defer src="{_KATEX_JS}"></script>
</head>
<body data-ingestion-state="{escape(doc.ingestion_state, quote=True)}">
<main class="math-doc-scroll">
<article class="math-doc" data-document-id="{document_id}">
{body}
</article>
</main>
<aside id="concept-panel" class="concept-panel" hidden aria-live="polite"></aside>
<script type="application/json" id="math-ide-data">{payload_json}</script>
<script defer src="assets/app.js"></script>
</body>
</html>
"""
