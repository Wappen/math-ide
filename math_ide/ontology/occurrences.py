r"""Occurrence extraction with dual bboxes (issue #7).

At import time we materialise the *occurrences* index of a
:class:`~math_ide.schema.MathDocument`: every surface appearance of
mathematical notation, each carrying its own *source bbox* (PDF page space,
estimated by char-span subdivision of the host block's bbox) and a *render
bbox* placeholder left ``None`` until layout (#11).

Four kinds are produced here (per ``CONTEXT.md``):

* ``formula_symbol`` — one per :class:`~math_ide.schema.SymbolSpan` in a
  :class:`~math_ide.schema.Formula`'s ``symbol_index``. ``span`` is the symbol's
  offsets into the formula's ``canonical_content``; the source bbox is the
  formula bbox subdivided over that span.
* ``defined_name`` — one per formal block carrying a ``defined_name``. It
  locates the defined name inside the block's reconstructed label and is the
  concept's *defining occurrence* (#8 links it).
* ``citation`` — one per explicit numbered cross-reference (``Definition 1.1``,
  ``Satz 2.3`` ...) found in paragraph prose or a formal block's body/preamble.
  ``target_block_id`` resolves deterministically to the cited formal block by
  matching environment type + number — no LLM.
* ``inline_symbol`` — one per standalone identifier or named set found *in prose*
  (a :class:`~math_ide.schema.Paragraph`'s ``text``, or a
  :class:`~math_ide.schema.FormalBlock`'s ``body``/``preamble``), e.g. the ``L``
  in "... lim n →∞ a n = L ." or the ``R`` in "... schreiben wir als R .". The
  match is conservative (#23, Phase 1): only a single Latin letter (optionally
  subscripted) bounded by non-letters, or a named set, never a letter buried in a
  German word. ``span`` indexes the host string; the source bbox is the host
  block bbox subdivided over that span.

The functions are pure and deterministic. :func:`extract_occurrences` mutates
``doc.occurrences`` in place and returns the document.
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator, Optional

from math_ide.ingest.docling_adapter import subdivide_bbox
from math_ide.ingest.formal_blocks import KEYWORD_TO_CLASS
from math_ide.ingest.symbols import (
    _UNICODE_SETS,
    _is_subscript_digit,
)
from math_ide.schema import (
    Block,
    Formula,
    FormalBlock,
    MathDocument,
    Occurrence,
    Paragraph,
)

__all__ = [
    "extract_occurrences",
    "iter_blocks",
    "reconstruct_label",
    "scan_inline_symbols",
    "CITATION_RE",
]


# ---------------------------------------------------------------------------
# Block traversal
# ---------------------------------------------------------------------------


def iter_blocks(blocks: Iterable[Block]) -> Iterator[Block]:
    """Yield every block in the tree in reading order (depth-first, pre-order)."""
    for block in blocks:
        yield block
        children = getattr(block, "children", None)
        if children:
            yield from iter_blocks(children)


# ---------------------------------------------------------------------------
# Citation grammar
# ---------------------------------------------------------------------------

# Each surface citation keyword maps (via the shared ingest table) to a formal
# block class. A citation is a keyword followed by a dotted number, e.g.
# "Definition 1.1", "Satz 2.3", "Lemma 4". We require the number so the target
# resolves deterministically to exactly one formal block (a bare "Theorem" has
# no unambiguous target).
_CITE_KEYWORDS = sorted(KEYWORD_TO_CLASS, key=len, reverse=True)
_CITE_ALT = "|".join(re.escape(k) for k in _CITE_KEYWORDS)
CITATION_RE = re.compile(
    r"\b(?P<keyword>" + _CITE_ALT + r")\s+(?P<number>\d+(?:\.\d+)*)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Label reconstruction (for defined-name occurrences)
# ---------------------------------------------------------------------------


def reconstruct_label(block: FormalBlock) -> str:
    """Rebuild the formal block's surface label + body string.

    The adapter discards the original label text, keeping only ``number`` /
    ``defined_name`` / ``body``. The block's ``source_bbox`` covers the original
    text from the keyword to the node end, so we rebuild a parallel string —
    ``"{Type} {number} ({defined_name}): {body}"`` — and subdivide the block
    bbox against it. The reconstruction is internally consistent: offsets into
    it map linearly onto the block bbox just like the original did.
    """
    keyword = block.type  # e.g. "Definition"; keyword == type for the v1 corpus
    head = keyword
    if block.number:
        head += f" {block.number}"
    if block.defined_name is not None:
        head += f" ({block.defined_name})"
    if block.body:
        return f"{head}: {block.body}"
    return head


# ---------------------------------------------------------------------------
# Occurrence builders
# ---------------------------------------------------------------------------


def _formula_symbol_occurrences(
    doc: MathDocument, formula: Formula
) -> list[Occurrence]:
    """One ``formula_symbol`` occurrence per entry in the symbol index."""
    content = formula.canonical_content
    charspan = (0, len(content))
    out: list[Occurrence] = []
    for idx, sym in enumerate(formula.symbol_index):
        occ_id = doc.mint("occ", f"{formula.id}-sym-{idx}-{sym.token}")
        source_bbox = subdivide_bbox(
            formula.source_bbox, charspan, sym.start, sym.end
        )
        out.append(
            Occurrence(
                id=occ_id,
                kind="formula_symbol",
                block_id=formula.id,
                span=(sym.start, sym.end),
                source_bbox=source_bbox,
                render_bbox=None,  # filled at layout (#11)
            )
        )
    return out


def _defined_name_occurrence(
    doc: MathDocument, block: FormalBlock
) -> Optional[Occurrence]:
    """The single defining occurrence located on a formal block's label."""
    name = block.defined_name
    if not name:
        return None
    label = reconstruct_label(block)
    start = label.find(name)
    if start < 0:  # pragma: no cover - name always present in reconstruction
        return None
    end = start + len(name)
    source_bbox = subdivide_bbox(block.source_bbox, (0, len(label)), start, end)
    occ_id = doc.mint("occ", f"{block.id}-defname-{name}")
    return Occurrence(
        id=occ_id,
        kind="defined_name",
        block_id=block.id,
        span=(start, end),
        source_bbox=source_bbox,
        render_bbox=None,
    )


def _citation_occurrences(
    doc: MathDocument,
    block: Block,
    text: str,
    *,
    field: str,
    targets: dict[tuple[type, str], str],
) -> list[Occurrence]:
    """Citation occurrences for one prose string belonging to ``block``.

    ``targets`` maps ``(block_class, number)`` to the cited block id so a match
    links deterministically with no LLM.
    """
    out: list[Occurrence] = []
    for idx, m in enumerate(CITATION_RE.finditer(text)):
        keyword = m.group("keyword").lower()
        number = m.group("number")
        block_class = KEYWORD_TO_CLASS.get(keyword)
        if block_class is None:  # pragma: no cover - alternation is exhaustive
            continue
        target_block_id = targets.get((block_class, number))
        start, end = m.start(), m.end()
        source_bbox = subdivide_bbox(
            block.source_bbox, (0, len(text)), start, end
        )
        occ_id = doc.mint(
            "occ", f"{block.id}-cite-{field}-{idx}-{keyword}-{number}"
        )
        out.append(
            Occurrence(
                id=occ_id,
                kind="citation",
                block_id=block.id,
                span=(start, end),
                source_bbox=source_bbox,
                render_bbox=None,
                target_block_id=target_block_id,
            )
        )
    return out


def _citation_targets(blocks: Iterable[Block]) -> dict[tuple[type, str], str]:
    """Index formal blocks by ``(class, number)`` for deterministic citation
    resolution."""
    targets: dict[tuple[type, str], str] = {}
    for block in iter_blocks(blocks):
        if isinstance(block, FormalBlock) and block.number:
            targets[(type(block), block.number)] = block.id
    return targets


# ---------------------------------------------------------------------------
# Inline-symbol grammar (issue #23, Phase 1)
# ---------------------------------------------------------------------------
#
# Prose carries most of the document's real notation (``f : X → Y``, ``L ∈ R``,
# ``lim n →∞ a n = L``, ``als R``), but it is interleaved with ordinary German
# words whose single letters must NEVER match. So we scan conservatively, reusing
# the very vocabulary the formula symbol scanner already understands
# (``symbols.py``):
#
# * a STANDALONE single Latin letter — bounded on the left by a non-letter and on
#   the right (after absorbing an optional subscript like ``a_n``) by a
#   non-letter — is an identifier. The boundary rule is what keeps the ``i`` in
#   "in", the ``d`` in "der" or the ``E`` in "Eine" from matching: those letters
#   are followed (or preceded) by another letter, i.e. they are part of a word.
# * a unicode named set (``ℝ ℕ ℤ ℚ ℂ`` ...) always matches. A bare capital
#   ``R``/``N``/``Z``/``Q``/``C`` matches only via the standalone-letter rule
#   above (e.g. "als R ." or "L ∈ R"), so "Reelle" never matches its leading R.
#
# We do NOT parse compound expressions (``f : X → Y``, ``( a n ) n ∈ N``) as
# structures — we only surface the individual identifiers/sets within them.
# Operators / quantifiers / relations (``∀ ∃ ⇒ → ∈ =`` ...), digits and
# word-internal letters are skipped.


def _is_letter(ch: str) -> bool:
    """True for any unicode letter (so word boundaries treat umlauts as letters)."""
    return ch.isalpha()


def _consume_tight_subscript(text: str, start: int, head_end: int) -> int:
    """End offset of a *tight* subscript attached to a single-letter head.

    Conservative, prose-only counterpart to the formula scanner's
    :func:`symbols._consume_unicode_subscript`: it absorbs **only** an
    immediately-following ``_``-introduced run (``a_n``, ``x_12``, ``x_{1}``) or a
    run of unicode subscript digits (``x₁``). It deliberately does NOT fold the
    formula scanner's *spaced* subscripts (``a n`` -> ``a_n``): in prose a space
    almost always separates two words, so absorbing the next word's first letter
    would corrupt the match (``Y höchstens`` must yield just ``Y``).
    """
    n = len(text)
    # unicode subscript digits run: x₁ -> x₁
    if head_end < n and _is_subscript_digit(text[head_end]):
        j = head_end
        while j < n and _is_subscript_digit(text[j]):
            j += 1
        return j
    # ASCII ``_`` subscript: a_n / x_12 / x_{1}
    if head_end < n and text[head_end] == "_":
        j = head_end + 1
        if j < n and text[j] == "{":
            close = text.find("}", j)
            if close != -1:
                return close + 1
            return head_end  # unbalanced brace: keep the bare head.
        k = j
        while k < n and text[k].isascii() and text[k].isalnum():
            k += 1
        if k > j:
            return k
        return head_end  # ``_`` led nowhere usable: keep the bare head.
    return head_end


def scan_inline_symbols(text: str) -> list[tuple[int, int, str]]:
    """Find standalone identifier / named-set tokens in a prose string.

    Returns ``(start, end, token)`` triples in left-to-right order, where
    ``token == text[start:end]``. The match is deliberately conservative
    (#23, Phase 1): a single Latin letter (optionally subscripted) that is
    *bounded by non-letters*, or a unicode named set. Anything that is part of a
    word — a letter with a letter neighbour — is skipped, as are operators,
    quantifiers, digits and whitespace. Pure, no document state.
    """
    out: list[tuple[int, int, str]] = []
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]

        # unicode named set (ℝ ℕ ...) — always a symbol, regardless of neighbours.
        if ch in _UNICODE_SETS:
            out.append((i, i + 1, ch))
            i += 1
            continue

        # a letter: either a standalone single-letter identifier or part of a
        # word. Either way, consume to the end of the maximal letter run so an
        # interior letter never re-enters the loop and matches spuriously.
        if _is_letter(ch):
            j = i + 1
            while j < n and _is_letter(text[j]):
                j += 1
            word_len = j - i
            if word_len == 1 and ch.isascii():
                # a STANDALONE single Latin letter (its neighbours are
                # non-letters): an identifier, optionally tight-subscripted.
                end = _consume_tight_subscript(text, i, j)
                out.append((i, end, text[i:end]))
                i = end
                continue
            # a multi-letter word (or a non-ASCII single letter): skip it whole.
            i = j
            continue

        # operator / quantifier / digit / whitespace / punctuation: not a symbol.
        i += 1

    return out


def _inline_symbol_occurrences(
    doc: MathDocument,
    block: Block,
    text: str,
    *,
    field: str,
) -> list[Occurrence]:
    """Inline-symbol occurrences for one prose string belonging to ``block``.

    Mirrors :func:`_citation_occurrences`: the source bbox is the host block bbox
    subdivided over the matched span; ``render_bbox`` is left ``None`` for layout.
    """
    out: list[Occurrence] = []
    for idx, (start, end, token) in enumerate(scan_inline_symbols(text)):
        source_bbox = subdivide_bbox(
            block.source_bbox, (0, len(text)), start, end
        )
        occ_id = doc.mint(
            "occ", f"{block.id}-inline-{field}-{idx}-{token}"
        )
        out.append(
            Occurrence(
                id=occ_id,
                kind="inline_symbol",
                block_id=block.id,
                span=(start, end),
                source_bbox=source_bbox,
                render_bbox=None,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def extract_occurrences(doc: MathDocument) -> MathDocument:
    """Populate ``doc.occurrences`` from the block tree (mutates + returns).

    Produces ``formula_symbol``, ``defined_name``, ``citation`` and
    ``inline_symbol`` occurrences with source bboxes and ``render_bbox=None``.
    Idempotent re-runs are the caller's concern; this appends to whatever is
    already there.
    """
    targets = _citation_targets(doc.blocks)

    for block in iter_blocks(doc.blocks):
        if isinstance(block, Formula):
            doc.occurrences.extend(_formula_symbol_occurrences(doc, block))
        elif isinstance(block, FormalBlock):
            occ = _defined_name_occurrence(doc, block)
            if occ is not None:
                doc.occurrences.append(occ)
            # citations + inline notation may appear inside a formal block's
            # body/preamble prose.
            if block.body:
                doc.occurrences.extend(
                    _citation_occurrences(
                        doc, block, block.body, field="body", targets=targets
                    )
                )
                doc.occurrences.extend(
                    _inline_symbol_occurrences(
                        doc, block, block.body, field="body"
                    )
                )
            if block.preamble:
                doc.occurrences.extend(
                    _citation_occurrences(
                        doc,
                        block,
                        block.preamble,
                        field="preamble",
                        targets=targets,
                    )
                )
                doc.occurrences.extend(
                    _inline_symbol_occurrences(
                        doc, block, block.preamble, field="preamble"
                    )
                )
        elif isinstance(block, Paragraph):
            doc.occurrences.extend(
                _citation_occurrences(
                    doc, block, block.text, field="text", targets=targets
                )
            )
            doc.occurrences.extend(
                _inline_symbol_occurrences(
                    doc, block, block.text, field="text"
                )
            )
        # Section carries no notation of its own.

    return doc
