r"""Precomputed navigation logic for the Math IDE (issues #12, #13).

Go-to-definition targets and concept-card payloads are computed **here, in pure
Python**, so they are unit-testable without a browser. ``app.js`` stays thin: it
reads the JSON :func:`build_ide_payload` embeds in the page and never recomputes
navigation.

Three public functions:

* :func:`definition_target` — the *go to definition* target block id for an
  occurrence (#12), or ``None`` while meaning resolution leaves it unresolved
  (the "resolving…" state).
* :func:`concept_card` — the side-panel *concept card* payload for a concept
  (#13): meanings, status, defining occurrence, references and a neighbourhood
  of related concepts split into structural vs semantic.
* :func:`build_ide_payload` — one JSON-serialisable blob the renderer embeds so
  the client can navigate and build cards with **no recomputation**.

Go-to-definition priority (per ``CONTEXT.md``)
----------------------------------------------
For an occurrence, the best available target block is chosen in this order:

1. **Citation occurrence** -> its ``target_block_id`` (the cited formal block).
2. The occurrence's concept's ``seeded_by_block_id`` (the formal block that
   introduced the concept).
3. The concept's ``defined_name`` occurrence's ``block_id`` (the label that
   names the concept).
4. The concept's ``defining_occurrence_id`` occurrence's ``block_id``.
5. ``None`` — no target yet (unresolved / still resolving).
"""

from __future__ import annotations

from typing import Optional, Union

from math_ide.schema import (
    Concept,
    MathDocument,
    Occurrence,
    Relation,
)

__all__ = [
    "definition_target",
    "concept_card",
    "build_ide_payload",
]


# ---------------------------------------------------------------------------
# Small index helpers (built per call; the documents are tiny)
# ---------------------------------------------------------------------------


def _occurrence_by_id(doc: MathDocument) -> dict[str, Occurrence]:
    return {o.id: o for o in doc.occurrences}


def _concept_by_id(doc: MathDocument) -> dict[str, Concept]:
    return {c.id: c for c in doc.concepts}


def _defined_name_block_for_concept(
    doc: MathDocument, concept_id: str
) -> Optional[str]:
    """Block id of the ``defined_name`` occurrence linked to ``concept_id``."""
    for occ in doc.occurrences:
        if occ.kind == "defined_name" and occ.concept_id == concept_id:
            return occ.block_id
    return None


def _resolve_occurrence(
    doc: MathDocument,
    occurrence_or_id: Union[Occurrence, str],
    occ_index: Optional[dict[str, Occurrence]] = None,
) -> Optional[Occurrence]:
    """Coerce an occurrence-or-id into the document's :class:`Occurrence`."""
    if isinstance(occurrence_or_id, Occurrence):
        return occurrence_or_id
    index = occ_index if occ_index is not None else _occurrence_by_id(doc)
    return index.get(occurrence_or_id)


# ---------------------------------------------------------------------------
# #12 — go to definition
# ---------------------------------------------------------------------------


def definition_target(
    doc: MathDocument,
    occurrence_or_id: Union[Occurrence, str],
) -> Optional[str]:
    """Return the go-to-definition target *block id* for an occurrence.

    ``occurrence_or_id`` may be an :class:`~math_ide.schema.Occurrence` or its
    id. Returns the best available target block id following the priority in the
    module docstring, or ``None`` when nothing is resolvable yet — the cue the
    IDE shows as a disabled "resolving…" state.
    """
    occ = _resolve_occurrence(doc, occurrence_or_id)
    if occ is None:
        return None

    # 1. A citation points straight at the cited formal block.
    if occ.kind == "citation" and occ.target_block_id is not None:
        return occ.target_block_id

    # Everything else needs a concept link (set by meaning resolution).
    if occ.concept_id is None:
        return None
    concept = _concept_by_id(doc).get(occ.concept_id)
    if concept is None:
        return None

    # 2. The formal block that seeded the concept.
    if concept.seeded_by_block_id is not None:
        return concept.seeded_by_block_id

    # 3. The block carrying the concept's defined-name label.
    name_block = _defined_name_block_for_concept(doc, concept.id)
    if name_block is not None:
        return name_block

    # 4. The block of the concept's defining occurrence.
    if concept.defining_occurrence_id is not None:
        defining = _occurrence_by_id(doc).get(concept.defining_occurrence_id)
        if defining is not None:
            return defining.block_id

    # 5. Unresolved — no target yet.
    return None


# ---------------------------------------------------------------------------
# #13 — concept card
# ---------------------------------------------------------------------------

_STRUCTURAL_ORIGIN = "structural"
_SEMANTIC_ORIGIN = "semantic"


def _related_entry(
    doc: MathDocument,
    relation: Relation,
    concept_index: dict[str, Concept],
) -> dict[str, Optional[str]]:
    """Build one neighbourhood entry from a relation whose source is the
    current concept.

    Each entry names the *other* end. ``seeded_by`` targets a block (not a
    concept), so the entry carries ``block_id`` instead of ``concept_id`` and
    derives a human name from the block id tail.
    """
    if relation.target_is_block:
        return {
            "block_id": relation.target_concept_id,
            "concept_id": None,
            "kind": relation.kind,
            "origin": relation.origin,
            "name": _block_display_name(relation.target_concept_id),
        }
    target = concept_index.get(relation.target_concept_id)
    return {
        "block_id": None,
        "concept_id": relation.target_concept_id,
        "kind": relation.kind,
        "origin": relation.origin,
        "name": target.name if target is not None else relation.target_concept_id,
    }


def _block_display_name(block_id: str) -> str:
    """A short readable label for a block id (the slug tail after ``block/``)."""
    tail = block_id.split("#", 1)[-1]
    if tail.startswith("block/"):
        tail = tail[len("block/") :]
    return tail


def concept_card(doc: MathDocument, concept_id: str) -> dict:
    """Build the side-panel concept-card payload for ``concept_id`` (#13).

    Shape::

        {
          "id", "name", "resolution_status",
          "formal_meaning", "inferred_meaning",
          "defining_occurrence": {"id", "block_id"} | None,
          "references": [{"occurrence_id", "block_id", "kind"}, ...],
          "neighbourhood": {"structural": [...], "semantic": [...]},
        }

    ``references`` are every non-defining occurrence linked to the concept.
    Neighbourhood entries are ``{concept_id|block_id, kind, origin, name}`` and
    are split by ``Relation.origin``: deterministic ``structural`` edges vs
    LLM-inferred ``semantic`` edges (shown as *inferred* in the UI).
    """
    concept = _concept_by_id(doc).get(concept_id)
    if concept is None:
        raise KeyError(f"unknown concept id: {concept_id!r}")

    defining_id = concept.defining_occurrence_id
    occ_index = _occurrence_by_id(doc)

    defining_occurrence: Optional[dict[str, str]] = None
    if defining_id is not None and defining_id in occ_index:
        defining_occurrence = {
            "id": defining_id,
            "block_id": occ_index[defining_id].block_id,
        }

    # References: every occurrence linked to this concept that is not the
    # defining occurrence (deduplicated, in document order).
    references: list[dict[str, str]] = []
    for occ in doc.occurrences:
        if occ.concept_id != concept_id:
            continue
        if defining_id is not None and occ.id == defining_id:
            continue
        references.append(
            {
                "occurrence_id": occ.id,
                "block_id": occ.block_id,
                "kind": occ.kind,
            }
        )

    # Neighbourhood: relations whose source is this concept, split by origin.
    concept_index = _concept_by_id(doc)
    structural: list[dict] = []
    semantic: list[dict] = []
    for rel in doc.relations:
        if rel.source_concept_id != concept_id:
            continue
        entry = _related_entry(doc, rel, concept_index)
        if rel.origin == _SEMANTIC_ORIGIN:
            semantic.append(entry)
        else:
            structural.append(entry)

    return {
        "id": concept.id,
        "name": concept.name,
        "resolution_status": concept.resolution_status,
        "formal_meaning": concept.formal_meaning,
        "inferred_meaning": concept.inferred_meaning,
        "defining_occurrence": defining_occurrence,
        "references": references,
        "neighbourhood": {"structural": structural, "semantic": semantic},
    }


# ---------------------------------------------------------------------------
# Embeddable client payload
# ---------------------------------------------------------------------------


def build_ide_payload(doc: MathDocument) -> dict:
    """Build the JSON-serialisable payload the renderer embeds for ``app.js``.

    The client uses this to navigate and build concept cards **without
    recomputing** any Python logic. Shape::

        {
          "document_id": str,
          "ingestion_state": str,
          "occurrences": {
            "<occ_id>": {
              "block_id", "concept_id", "kind",
              "target_block_id", "definition_target", "render_bbox"
            }, ...
          },
          "concepts": {
            "<concept_id>": {
              "id", "name", "resolution_status",
              "formal_meaning", "inferred_meaning",
              "defining_occurrence_id", "seeded_by_block_id"
            }, ...
          },
          "relations": [
            {"source", "target", "kind", "origin", "target_is_block"}, ...
          ],
          "cards": {"<concept_id>": <concept_card(...)>, ...}
        }

    ``definition_target`` is precomputed per occurrence (``None`` while
    unresolved). ``cards`` are precomputed so the right-click panel is instant;
    they regenerate when :func:`build_ide_payload` is re-run after resolution.

    Each occurrence carries a ``render_bbox`` slot seeded from the model's
    :attr:`~math_ide.schema.Occurrence.render_bbox` (``None`` at import). It is
    populated **client-side, post-layout**: ``app.js`` measures every ``.occ``
    after KaTeX/CDN/fonts settle and writes the measured box back into
    ``state.data.occurrences[id].render_bbox`` (mirroring ``state.bboxes``), so a
    re-serialised payload carries the rendered-document geometry (#11).
    """
    occurrences: dict[str, dict] = {}
    for occ in doc.occurrences:
        occurrences[occ.id] = {
            "block_id": occ.block_id,
            "concept_id": occ.concept_id,
            "kind": occ.kind,
            "target_block_id": occ.target_block_id,
            "definition_target": definition_target(doc, occ),
            "render_bbox": (
                occ.render_bbox.model_dump() if occ.render_bbox is not None else None
            ),
        }

    concepts: dict[str, dict] = {}
    for concept in doc.concepts:
        concepts[concept.id] = {
            "id": concept.id,
            "name": concept.name,
            "resolution_status": concept.resolution_status,
            "formal_meaning": concept.formal_meaning,
            "inferred_meaning": concept.inferred_meaning,
            "defining_occurrence_id": concept.defining_occurrence_id,
            "seeded_by_block_id": concept.seeded_by_block_id,
        }

    relations: list[dict] = [
        {
            "source": r.source_concept_id,
            "target": r.target_concept_id,
            "kind": r.kind,
            "origin": r.origin,
            "target_is_block": r.target_is_block,
        }
        for r in doc.relations
    ]

    cards: dict[str, dict] = {
        concept.id: concept_card(doc, concept.id) for concept in doc.concepts
    }

    return {
        "document_id": doc.document_id,
        "ingestion_state": doc.ingestion_state,
        "occurrences": occurrences,
        "concepts": concepts,
        "relations": relations,
        "cards": cards,
    }
