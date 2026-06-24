"""Formula-block construction and enrichment lifecycle (issue #5).

Docling emits a ``formula`` node with a linearized ``orig`` string and, only
when formula enrichment ran, a LaTeX ``text``. Per ``CONTEXT.md`` occurrences
must be extractable *before* LaTeX arrives, so we always keep ``orig`` in
``orig_fallback`` and let the formula upgrade in place later.

Lifecycle::

    build_formula(...)            # orig_fallback set; status pending/ready
        |
        +-- upgrade_formula(f, latex)  -> status "ready", latex set,
        |                                 symbol_index rebuilt against latex
        |
        +-- mark_failed(f)             -> status "failed", orig_fallback and
                                          source_bbox preserved

The symbol index always indexes the *canonical content* (``latex`` when ready,
otherwise ``orig_fallback``); rebuilding it is delegated to
:mod:`math_ide.ingest.symbols`.
"""

from __future__ import annotations

from typing import Optional

from math_ide.schema import BBox, Formula
from math_ide.ingest.symbols import extract_symbol_index

__all__ = [
    "build_formula",
    "rebuild_symbol_index",
    "upgrade_formula",
    "mark_failed",
]


def rebuild_symbol_index(formula: Formula) -> Formula:
    """Recompute ``formula.symbol_index`` from its current canonical content.

    Mutates and returns the formula. ``canonical_content`` is ``latex`` when
    ``enrichment_status == "ready"`` else ``orig_fallback`` (see the schema
    property), so this is correct in every state.
    """
    formula.symbol_index = extract_symbol_index(formula.canonical_content)
    return formula


def build_formula(
    block_id: str,
    *,
    orig: str,
    text: str = "",
    source_bbox: Optional[BBox] = None,
    page_no: Optional[int] = None,
) -> Formula:
    """Build a :class:`Formula` from a Docling formula node's fields.

    ``orig_fallback`` is always the linearized ``orig``. If ``text`` (Docling's
    LaTeX from formula enrichment) is non-empty the formula is born ``ready``
    with that LaTeX; otherwise it is ``pending``. The symbol index is built
    immediately against whichever string is canonical.
    """
    text = (text or "").strip()
    has_latex = bool(text)
    formula = Formula(
        id=block_id,
        orig_fallback=orig,
        latex=text or None,
        enrichment_status="ready" if has_latex else "pending",
        source_bbox=source_bbox,
        page_no=page_no,
    )
    return rebuild_symbol_index(formula)


def upgrade_formula(formula: Formula, latex: str) -> Formula:
    """Upgrade a pending formula in place once its LaTeX enrichment arrives.

    Sets ``latex``, flips ``enrichment_status`` to ``"ready"`` and REBUILDS the
    symbol index against the new LaTeX (offsets now index ``latex``). Returns
    the same instance.
    """
    formula.latex = latex
    formula.enrichment_status = "ready"
    return rebuild_symbol_index(formula)


def mark_failed(formula: Formula) -> Formula:
    """Mark formula enrichment as failed without losing the fallback.

    Keeps ``orig_fallback`` and ``source_bbox`` intact, clears any partial
    ``latex``, flips status to ``"failed"`` and rebuilds the symbol index
    against the (now canonical) ``orig_fallback``. Returns the same instance.
    """
    formula.latex = None
    formula.enrichment_status = "failed"
    return rebuild_symbol_index(formula)
