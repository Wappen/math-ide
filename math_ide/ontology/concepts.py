r"""Concept seeding + deterministic structural relations (issue #8).

After occurrences exist (#7) we seed the document's *ontology*: one
:class:`~math_ide.schema.Concept` per formal-block defined name (authoritative
``formal_meaning`` from the block body, ``resolution_status="resolved"``) plus
one *stub* concept per distinct formula symbol token (no formal meaning,
``resolution_status="pending"`` until meaning resolution #9).

Occurrences are then wired to concepts:

* each ``defined_name`` occurrence becomes its concept's *defining occurrence*;
* each ``formula_symbol`` occurrence links to its token's stub concept;
* each ``citation`` occurrence links to the seeded concept of the block it cites.

Finally we lay down deterministic **structural** relations (``origin="structural"``):

* ``seeded_by`` — concept -> the formal block that introduced it
  (``target_is_block=True``);
* ``sibling`` — concepts seeded by the *same* formal block;
* ``co_occurring`` — concepts whose occurrences appear in the *same* formula.

No LLM is involved; semantic relations are added later (#9). On completion the
document advances to ``ingestion_state="structure_ready"`` — this is stage-1
completion.

Concept-id scheme
-----------------
* formal-block concepts: ``mint_id(document_id, "concept", defined_name)`` ->
  e.g. ``doc#concept/menge``.
* stub symbol concepts: ``mint_id(document_id, "concept", stub_key(token))``
  where :func:`stub_key` appends the token's unicode codepoints so visually
  colliding tokens (``X`` vs ``x_1`` vs ``ε`` vs ``ℝ``; ``N`` vs ``n``) stay
  distinct after slugification -> e.g. ``doc#concept/sym-x-58`` for ``X``.
"""

from __future__ import annotations

from typing import Optional

from math_ide.ontology.occurrences import iter_blocks
from math_ide.schema import (
    Concept,
    Formula,
    FormalBlock,
    MathDocument,
    Occurrence,
    Relation,
)

__all__ = [
    "seed_concepts_and_relations",
    "stub_key",
]


# ---------------------------------------------------------------------------
# Concept ids
# ---------------------------------------------------------------------------


def stub_key(token: str) -> str:
    """Collision-free id key for a formula-symbol stub concept.

    ``slugify`` folds many distinct maths tokens onto the same slug (``X``,
    ``x_1``, ``ε`` and ``ℝ`` all slug to ``x``; ``N`` and ``n`` to ``n``).
    Appending the token's unicode codepoints keeps one stub per *distinct*
    token while staying inside the ``{document_id}#concept/{slug}`` convention.
    """
    codepoints = "-".join(format(ord(ch), "x") for ch in token)
    return f"sym-{token}-{codepoints}"


# ---------------------------------------------------------------------------
# Relation de-duplication
# ---------------------------------------------------------------------------


def _add_relation(
    seen: set[tuple[str, str, str]],
    out: list[Relation],
    relation: Relation,
) -> None:
    """Append ``relation`` unless an identical (source, target, kind) edge
    already exists."""
    key = (relation.source_concept_id, relation.target_concept_id, relation.kind)
    if key in seen:
        return
    seen.add(key)
    out.append(relation)


# ---------------------------------------------------------------------------
# Structural relation builders (pure, testable)
# ---------------------------------------------------------------------------


def _sibling_relations(
    concepts: list[Concept],
    seen: set[tuple[str, str, str]],
) -> list[Relation]:
    """Undirected (emitted both ways) ``sibling`` edges between concepts that
    share a ``seeded_by_block_id``."""
    by_block: dict[str, list[str]] = {}
    for concept in concepts:
        if concept.seeded_by_block_id is None:
            continue
        by_block.setdefault(concept.seeded_by_block_id, []).append(concept.id)

    out: list[Relation] = []
    for ids in by_block.values():
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                _add_relation(
                    seen,
                    out,
                    Relation(
                        source_concept_id=a,
                        target_concept_id=b,
                        kind="sibling",
                        origin="structural",
                    ),
                )
                _add_relation(
                    seen,
                    out,
                    Relation(
                        source_concept_id=b,
                        target_concept_id=a,
                        kind="sibling",
                        origin="structural",
                    ),
                )
    return out


def _co_occurring_relations(
    formula_concept_ids: list[list[str]],
    seen: set[tuple[str, str, str]],
) -> list[Relation]:
    """Undirected (emitted both ways) ``co_occurring`` edges between distinct
    concepts that occur together in the same formula."""
    out: list[Relation] = []
    for ids in formula_concept_ids:
        distinct = list(dict.fromkeys(ids))  # stable de-dupe, drop repeats
        for i, a in enumerate(distinct):
            for b in distinct[i + 1 :]:
                _add_relation(
                    seen,
                    out,
                    Relation(
                        source_concept_id=a,
                        target_concept_id=b,
                        kind="co_occurring",
                        origin="structural",
                    ),
                )
                _add_relation(
                    seen,
                    out,
                    Relation(
                        source_concept_id=b,
                        target_concept_id=a,
                        kind="co_occurring",
                        origin="structural",
                    ),
                )
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def seed_concepts_and_relations(doc: MathDocument) -> MathDocument:
    """Seed concepts + structural relations from the tree and occurrences.

    Requires occurrences (#7) to already exist. Mutates ``doc.concepts`` /
    ``doc.relations`` / occurrence ``concept_id`` links in place, sets
    ``ingestion_state="structure_ready"``, and returns the document.
    """
    # Index occurrences once for cheap lookup.
    defined_name_occ: dict[str, Occurrence] = {}  # block_id -> occurrence
    formula_symbol_occ: dict[str, list[Occurrence]] = {}  # block_id -> occ list
    citation_occ: list[Occurrence] = []
    for occ in doc.occurrences:
        if occ.kind == "defined_name":
            defined_name_occ[occ.block_id] = occ
        elif occ.kind == "formula_symbol":
            formula_symbol_occ.setdefault(occ.block_id, []).append(occ)
        elif occ.kind == "citation":
            citation_occ.append(occ)

    relations: list[Relation] = []
    rel_seen: set[tuple[str, str, str]] = set()

    # --- 1. formal-block concepts (authoritative, resolved) ----------------
    block_concept_id: dict[str, str] = {}  # block_id -> concept id
    for block in iter_blocks(doc.blocks):
        if not isinstance(block, FormalBlock) or not block.defined_name:
            continue
        concept_id = doc.mint("concept", block.defined_name)
        defining = defined_name_occ.get(block.id)
        concept = Concept(
            id=concept_id,
            name=block.defined_name,
            formal_meaning=block.body or None,
            resolution_status="resolved",
            defining_occurrence_id=defining.id if defining else None,
            seeded_by_block_id=block.id,
        )
        doc.concepts.append(concept)
        block_concept_id[block.id] = concept_id
        if defining is not None:
            defining.concept_id = concept_id

        # structural: seeded_by (concept -> block)
        _add_relation(
            rel_seen,
            relations,
            Relation(
                source_concept_id=concept_id,
                target_concept_id=block.id,
                kind="seeded_by",
                origin="structural",
                target_is_block=True,
            ),
        )

    # --- 2. stub concepts per distinct formula symbol token ----------------
    stub_concept_id: dict[str, str] = {}  # token -> stub concept id
    formula_concept_ids: list[list[str]] = []  # per-formula concept id lists
    for block in iter_blocks(doc.blocks):
        if not isinstance(block, Formula):
            continue
        this_formula: list[str] = []
        for occ in formula_symbol_occ.get(block.id, []):
            token = _occurrence_token(block, occ)
            if token is None:  # pragma: no cover - spans always valid here
                continue
            concept_id = stub_concept_id.get(token)
            if concept_id is None:
                concept_id = doc.mint("concept", stub_key(token))
                stub_concept_id[token] = concept_id
                doc.concepts.append(
                    Concept(
                        id=concept_id,
                        name=token,
                        formal_meaning=None,
                        resolution_status="pending",
                    )
                )
            occ.concept_id = concept_id
            this_formula.append(concept_id)
        formula_concept_ids.append(this_formula)

    # --- 3. citation occurrences -> cited block's seeded concept -----------
    for occ in citation_occ:
        if occ.target_block_id is None:
            continue
        occ.concept_id = block_concept_id.get(occ.target_block_id)

    # --- 4. structural relations: sibling + co_occurring -------------------
    relations.extend(_sibling_relations(doc.concepts, rel_seen))
    relations.extend(_co_occurring_relations(formula_concept_ids, rel_seen))

    doc.relations.extend(relations)
    doc.ingestion_state = "structure_ready"
    return doc


def _occurrence_token(formula: Formula, occ: Occurrence) -> Optional[str]:
    """The surface token a formula-symbol occurrence points at.

    Reads it from the formula's canonical content via the occurrence span so it
    stays correct whether the formula is enriched or still on its fallback.
    """
    if occ.span is None:
        return None
    start, end = occ.span
    return formula.canonical_content[start:end]
