r"""Meaning resolution — the asynchronous LLM stage (issue #9).

Stage-1 seeding (#7/#8) leaves a :class:`~math_ide.schema.MathDocument` at
``ingestion_state="structure_ready"``: every formula symbol has a *stub*
concept (``resolution_status="pending"``, no ``inferred_meaning``) and only
deterministic **structural** relations (``origin="structural"``) exist.

*Meaning resolution* is the second, asynchronous stage. A :class:`Resolver`
reads the seeded document and applies a *delta*:

* **coreference** — a stub symbol that denotes a formally-defined object is
  linked to that object's concept. In the example corpus the convergence
  formula's ``ε`` is bound to the ``Konvergenz`` concept (seeded by
  Definition 2.1), and the injectivity formula's ``f`` / ``X`` (and the prose
  ``Y``) are made consistent with the ``Injektivitaet`` concept.
* **inferred meaning** — stub concepts that have no formal block get an
  ``inferred_meaning`` filled in from context. ``formal_meaning`` is
  authoritative and is **never** touched.
* **semantic relations** — directed edges with ``origin="semantic"`` and kinds
  drawn from ``uses`` / ``defines`` / ``generalizes`` / ``specializes`` /
  ``instance_of``, clearly distinct from the structural edges left by #8.
* **resolution status** — every concept and occurrence the resolver touches is
  flipped ``pending`` -> ``resolved``; on completion the document advances to
  ``ingestion_state="ready"``.

Three resolvers ship here:

* :class:`MockResolver` — deterministic, offline, no network. It encodes the
  coreference the example corpus needs and is what the tests exercise.
* :class:`AnthropicResolver` — calls the Anthropic API (model default
  ``"claude-sonnet-4-6"``). The ``anthropic`` SDK is imported lazily inside the
  methods so importing this module never requires it. It tolerates API/parse
  failure: it retries a bounded number of times then returns the document with
  whatever **partial** results it managed, never raising into the pipeline.
* :class:`OpenAIResolver` — calls the OpenAI Chat Completions API (model default
  ``"gpt-4o"``). The ``openai`` SDK is imported lazily inside ``_complete`` so
  importing this module never requires it. Same fault tolerance as the Anthropic
  resolver.

Both live resolvers route prompt-building, response parsing and the bounded
retry loop through the **module-level** helpers :func:`build_prompt`,
:func:`parse_response` and :func:`resolve_via_completion`; only the one-shot
``_complete`` (the SDK call) differs between them.

The factory :func:`auto_resolver` picks a resolver from the environment:
``ANTHROPIC_API_KEY`` -> :class:`AnthropicResolver`, else ``OPENAI_API_KEY`` ->
:class:`OpenAIResolver`, else :class:`MockResolver` (with a one-line warning to
``stderr``). Constructing the live resolvers never imports their SDKs, so the
factory works fully offline.

The authoritative-meaning rule is enforced structurally: resolvers route every
write through :class:`MeaningDelta`, whose :meth:`MeaningDelta.apply` refuses to
modify ``formal_meaning``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol, runtime_checkable

from math_ide.schema import (
    Concept,
    Formula,
    MathDocument,
    Occurrence,
    Relation,
    RelationKind,
)
from math_ide.ontology.occurrences import iter_blocks

__all__ = [
    "Resolver",
    "MeaningDelta",
    "MockResolver",
    "AnthropicResolver",
    "OpenAIResolver",
    "auto_resolver",
    "build_prompt",
    "parse_response",
    "resolve_via_completion",
    "DEFAULT_MODEL",
    "DEFAULT_OPENAI_MODEL",
    "SYSTEM_PROMPT",
]

logger = logging.getLogger(__name__)

#: Default Anthropic model id for :class:`AnthropicResolver`.
DEFAULT_MODEL = "claude-sonnet-4-6"

#: Default OpenAI model id for :class:`OpenAIResolver`.
DEFAULT_OPENAI_MODEL = "gpt-4o"

_SEMANTIC_KINDS: frozenset[RelationKind] = frozenset(
    {"uses", "defines", "generalizes", "specializes", "instance_of"}
)


# ---------------------------------------------------------------------------
# Resolver interface
# ---------------------------------------------------------------------------


@runtime_checkable
class Resolver(Protocol):
    """A meaning-resolution strategy.

    A resolver consumes a *seeded* :class:`~math_ide.schema.MathDocument`
    (``structure_ready``), computes a :class:`MeaningDelta`, applies it in
    place, and returns the same document advanced to ``ready``.

    Implementations must never overwrite an existing ``formal_meaning`` and
    must never raise into the caller: a resolver that cannot do its job returns
    the document unchanged (or partially changed) rather than crashing the
    pipeline.
    """

    def resolve(self, doc: MathDocument) -> MathDocument:
        """Apply meaning resolution to ``doc`` and return it."""
        ...


# ---------------------------------------------------------------------------
# Delta — the unit of change, and the guardrail for formal_meaning
# ---------------------------------------------------------------------------


@dataclass
class MeaningDelta:
    """A batch of meaning-resolution changes to apply to a document.

    Collecting changes into a delta (rather than mutating the document inline)
    keeps the authoritative-meaning rule in one place and makes a *partial*
    delta — all a failing :class:`AnthropicResolver` could parse — applicable
    with the same code path as a full one.

    Fields
    ------
    occurrence_concept:
        ``occurrence_id -> concept_id`` coreference assignments.
    inferred_meaning:
        ``concept_id -> inferred meaning`` for stub concepts. Applied only to
        concepts whose ``formal_meaning`` is ``None``; entries for concepts
        with a formal meaning are ignored (the rule, enforced).
    relations:
        Semantic relations to add (``origin`` is forced to ``"semantic"`` and
        non-semantic kinds are dropped on apply).
    resolved_concepts / resolved_occurrences:
        Ids to flip ``pending`` -> ``resolved``.
    """

    occurrence_concept: dict[str, str] = field(default_factory=dict)
    inferred_meaning: dict[str, str] = field(default_factory=dict)
    relations: list[Relation] = field(default_factory=list)
    resolved_concepts: set[str] = field(default_factory=set)
    resolved_occurrences: set[str] = field(default_factory=set)

    def link(self, occurrence_id: str, concept_id: str) -> None:
        """Record an occurrence -> concept coreference assignment."""
        self.occurrence_concept[occurrence_id] = concept_id
        self.resolved_occurrences.add(occurrence_id)

    def infer(self, concept_id: str, meaning: str) -> None:
        """Record an inferred meaning for a (presumed stub) concept."""
        self.inferred_meaning[concept_id] = meaning
        self.resolved_concepts.add(concept_id)

    def relate(
        self,
        source_concept_id: str,
        target_concept_id: str,
        kind: RelationKind,
    ) -> None:
        """Record a semantic relation between two concepts."""
        self.relations.append(
            Relation(
                source_concept_id=source_concept_id,
                target_concept_id=target_concept_id,
                kind=kind,
                origin="semantic",
            )
        )

    def apply(self, doc: MathDocument) -> MathDocument:
        """Apply this delta to ``doc`` in place and return it.

        Enforces the rules: ``formal_meaning`` is never written, only
        ``origin="semantic"`` relations with a semantic ``kind`` are added, and
        relations are de-duplicated against what already exists.
        """
        concept_by_id = {c.id: c for c in doc.concepts}
        occ_by_id = {o.id: o for o in doc.occurrences}

        # 1. coreference: re-point occurrences at concepts.
        for occ_id, concept_id in self.occurrence_concept.items():
            occ = occ_by_id.get(occ_id)
            if occ is None or concept_id not in concept_by_id:
                continue
            occ.concept_id = concept_id

        # 2. inferred meaning — only where there is no authoritative meaning.
        for concept_id, meaning in self.inferred_meaning.items():
            concept = concept_by_id.get(concept_id)
            if concept is None or concept.formal_meaning is not None:
                continue  # formal_meaning is authoritative; never touch it.
            concept.inferred_meaning = meaning

        # 3. semantic relations (de-duplicated against existing edges).
        seen = {
            (r.source_concept_id, r.target_concept_id, r.kind) for r in doc.relations
        }
        for rel in self.relations:
            if rel.kind not in _SEMANTIC_KINDS:
                continue  # structural kinds are not the resolver's job.
            rel.origin = "semantic"
            if rel.source_concept_id not in concept_by_id:
                continue
            if rel.target_concept_id not in concept_by_id:
                continue
            key = (rel.source_concept_id, rel.target_concept_id, rel.kind)
            if key in seen:
                continue
            seen.add(key)
            doc.relations.append(rel)

        # 4. flip touched concepts / occurrences pending -> resolved.
        for concept_id in self.resolved_concepts:
            concept = concept_by_id.get(concept_id)
            if concept is not None:
                concept.resolution_status = "resolved"
        for occ_id in self.resolved_occurrences:
            # Occurrences have no resolution_status field of their own; an
            # occurrence is "resolved" once it points at a concept that is
            # resolved. Promote that concept so the link is discoverable.
            occ = occ_by_id.get(occ_id)
            if occ is None or occ.concept_id is None:
                continue
            concept = concept_by_id.get(occ.concept_id)
            if concept is not None:
                concept.resolution_status = "resolved"

        return doc


# ---------------------------------------------------------------------------
# Normalisation-aware matching (issue #21)
# ---------------------------------------------------------------------------
#
# Real Docling output spells the *same* symbol several ways across enrichment:
# the convergence error bound arrives as the LaTeX control word ``\epsilon`` (or
# the unicode ``ε`` / the ``ϵ`` U+03F5 fallback); subscripts arrive *spaced* as
# ``a _ { n }`` / ``x _ { 1 }`` rather than ``a_n`` / ``x_1``; and the umlaut
# repair (#18) names the injectivity concept ``Injektivität`` while the mock's
# table key is the ASCII-folded ``Injektivitaet``. The deterministic
# :class:`MockResolver` table is authored against ONE canonical spelling, so
# every key — both the *defining-concept* names and the *per-symbol* tokens — is
# matched through a fold that collapses these dialects onto a single key.
#
# We reuse :func:`pipeline.normalize_token` (which already folds ``\epsilon`` ->
# ``ε``, ``x_1`` -> ``x_1`` and ``\mathbb{R}`` -> ``R``) and EXTEND it by first
# collapsing the internal whitespace LaTeX leaves in spaced subscripts, so
# ``a _ { n }`` -> ``a_{n}`` -> ``a_n`` and ``x _ { 1 }`` -> ``x_1``. We also fold
# the ``ϵ`` (U+03F5) epsilon variant onto the canonical ``ε`` (U+03B5).

#: ``ϵ`` (GREEK LUNATE EPSILON SYMBOL, U+03F5) -> ``ε`` (GREEK SMALL LETTER
#: EPSILON, U+03B5). Docling's ``orig`` fallback uses the lunate variant; the
#: enriched ``\epsilon`` and the table key both canonicalise to U+03B5.
_LUNATE_EPSILON = "ϵ"
_SMALL_EPSILON = "ε"

_WS_RE = re.compile(r"\s+")


def _normalize_symbol_token(token: str) -> str:
    r"""Fold a formula-symbol surface token to a dialect-independent match key.

    Wraps :func:`math_ide.pipeline.normalize_token` with two pre/post passes so
    the *real* Docling spellings collapse onto the same key as the synthetic
    fixture's canonical spellings:

    * collapse internal whitespace (``a _ { n }`` -> ``a_{n}``) so the spaced
      LaTeX subscript folds the same as ``a_n`` / ``a_{n}`` / ``aₙ``;
    * canonicalise the ``ϵ`` (U+03F5) epsilon variant onto ``ε`` (U+03B5).

    Examples (real spelling -> key)::

        \epsilon / ϵ / ε        -> ε
        a _ { n } / a_n / a_{n}  -> a_n
        x _ { 1 } / x_1 / x₁     -> x_1
        \mathbb { N } / ℕ / N    -> N

    Note the set ``\mathbb { N }`` and the bare threshold ``N`` deliberately
    share the key ``N`` (that is what ``normalize_token`` does); the resolver
    keeps them apart by matching *concepts* (which #20 made distinct), not by the
    shared token key — see :meth:`MockResolver.build_delta`.
    """
    # lazy import: pipeline imports math_ide.ontology, so importing it at module
    # scope would be circular (see __init__). Importing here is cheap and safe.
    from math_ide.pipeline import normalize_token

    if not token:
        return token
    collapsed = _WS_RE.sub("", token)
    folded = normalize_token(collapsed)
    return folded.replace(_LUNATE_EPSILON, _SMALL_EPSILON)


#: German umlaut / sharp-s folds, matching ``schema.slugify`` semantics (which
#: the concept *ids* already use), so the same equivalence drives name matching.
_UMLAUT_FOLD = (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"))


def _fold_concept_name(name: str) -> str:
    """Fold a defining-concept *name* to a case/umlaut-insensitive match key.

    Applies the same umlaut/sharp-s folds as ``schema.slugify`` (ä->ae, ö->oe,
    ü->ue, ß->ss) plus a casefold, so the umlaut-repaired name ``Injektivität``
    matches the ASCII table key ``Injektivitaet`` both ways. Unlike ``slugify``
    this is *non-destructive* — it keeps every other character — because it is
    only ever applied to whole-word concept names (``Konvergenz`` / ``Menge`` /
    ``Injektivität``), never to symbol tokens (those go through
    :func:`_normalize_symbol_token`, which must preserve unicode like ``ε`` and
    the ``X`` vs ``x`` distinction ``slugify`` would erase).
    """
    folded = name.strip().casefold()
    for src, dst in _UMLAUT_FOLD:
        folded = folded.replace(src, dst)
    return folded


def _is_set_markup(name: str) -> bool:
    """True if a concept name is blackboard/set markup (``\\mathbb{N}`` / ``ℕ``).

    Used to keep the SET token (e.g. the convergence ``\\mathbb { N }``, #20)
    distinct from a bare-letter threshold (``N``) even though both fold to the
    same symbol key.
    """
    collapsed = _WS_RE.sub("", name)
    if _MATHBB_NAME_RE.match(collapsed):
        return True
    return any(ch in _BLACKBOARD_CODEPOINTS for ch in name)


_MATHBB_NAME_RE = re.compile(r"^\\(?:mathbb|mathcal|mathfrak|mathscr)\{")
#: Single-codepoint blackboard letters (ℝ ℕ ℤ ℚ ℂ 𝔽 ℙ ...).
_BLACKBOARD_CODEPOINTS = set("ℝℕℤℚℂ𝔽ℙ")


# ---------------------------------------------------------------------------
# Shared helpers for building a delta from a seeded document
# ---------------------------------------------------------------------------


def _index_concepts_by_name(doc: MathDocument) -> dict[str, list[Concept]]:
    """Map a *folded* concept name -> the concepts that share it (issue #21).

    Keyed by :func:`_fold_concept_name` so the umlaut-repaired ``Injektivität``
    lands under the same key as the ASCII table name ``Injektivitaet``. The value
    is a *list* (document order) so a name collision keeps every candidate.
    """
    by_name: dict[str, list[Concept]] = {}
    for concept in doc.concepts:
        by_name.setdefault(_fold_concept_name(concept.name), []).append(concept)
    return by_name


def _index_concepts_by_symbol(doc: MathDocument) -> dict[str, list[Concept]]:
    """Map a *normalised* symbol token -> the concepts that share it (issue #21).

    Keyed by :func:`_normalize_symbol_token` of the concept's name so the
    per-symbol stub concepts seeded from the real Docling spellings (``\\epsilon``
    / ``a _ { n }`` / ``x _ { 1 }``) land under the same key as the table's
    canonical tokens (``ε`` / ``a_n`` / ``x_1``). The value is a *list* because
    the symbol fold can give two distinct concepts the same key — the convergence
    threshold ``N`` and the set ``\\mathbb { N }`` both fold to ``N`` (#20 keeps
    them as separate concepts); :meth:`MockResolver._match_symbol_concept` picks
    the right one.
    """
    by_symbol: dict[str, list[Concept]] = {}
    for concept in doc.concepts:
        by_symbol.setdefault(
            _normalize_symbol_token(concept.name), []
        ).append(concept)
    return by_symbol


def _formula_symbol_occurrences_by_concept(
    doc: MathDocument,
) -> dict[str, list[Occurrence]]:
    """Group symbol occurrences by the stub ``concept_id`` they point at.

    Stage-1 seeding links every formula-symbol occurrence — and every
    ``inline_symbol`` occurrence (#23) — to its per-token stub concept, and #20
    gives the threshold ``N`` and the set ``\\mathbb { N }`` *distinct* stub
    concepts. Grouping by ``concept_id`` (rather than by the shared,
    fold-collapsed token) lets the resolver re-point exactly the occurrences of
    the concept it matched — so linking the threshold ``N`` never drags the set's
    occurrences along. Inline occurrences ride along with their stub: when the
    resolver corefers the formula ``L`` stub to Konvergenz, the prose ``L`` that
    shares that stub follows, so go-to-definition reaches the same block.
    """
    by_concept: dict[str, list[Occurrence]] = {}
    for occ in doc.occurrences:
        if occ.kind not in ("formula_symbol", "inline_symbol"):
            continue
        if occ.concept_id is None:
            continue
        by_concept.setdefault(occ.concept_id, []).append(occ)
    return by_concept


# ---------------------------------------------------------------------------
# MockResolver — deterministic, offline
# ---------------------------------------------------------------------------


class MockResolver:
    """A deterministic, network-free :class:`Resolver` for tests and demos.

    On the seeded example fixture it performs the coreference the corpus is
    designed to exercise:

    * binds the convergence ``ε`` (and ``a_n`` / ``L`` / ``N``) to the
      ``Konvergenz`` concept (Definition 2.1) — both by re-pointing the symbol
      occurrences' ``concept_id`` **and** by adding a semantic relation from the
      symbol's stub concept to ``Konvergenz``, so the link is discoverable
      either way;
    * makes the injectivity ``f`` / ``X`` (and the prose ``Y``) consistent with
      the ``Injektivitaet`` concept (Definition 1.2) the same way;
    * sets ``inferred_meaning`` on the stub concepts it touches (never
      ``formal_meaning``);
    * flips touched concepts'/occurrences' ``resolution_status`` to
      ``resolved`` and sets ``ingestion_state="ready"``.

    It is intentionally tolerant: tokens it doesn't recognise are skipped, and
    a document missing a definition concept simply yields fewer links. Running
    it twice is idempotent (the delta de-duplicates).
    """

    #: For each defining concept name, the symbol tokens that corefer to it and
    #: the inferred meaning to attach to each symbol's stub concept.
    #:
    #: Keys are written in ONE canonical spelling; matching is normalisation-aware
    #: (issue #21), so the concept names fold through :func:`_fold_concept_name`
    #: (``Injektivitaet`` matches the umlaut-repaired ``Injektivität``) and the
    #: symbol tokens fold through :func:`_normalize_symbol_token` (``ε`` matches
    #: ``\epsilon`` / ``ϵ``; ``a_n`` matches the spaced ``a _ { n }``; ``x_1``
    #: matches ``x _ { 1 }``). Tokens with no stub concept in a given document
    #: (e.g. ``Y``, which appears only in prose) are skipped without error.
    _COREFERENCE: dict[str, dict[str, str]] = {
        "Konvergenz": {
            "ε": "Positive error bound in the convergence definition; "
            "the sequence eventually stays within ε of the limit.",
            "a_n": "The n-th term of the sequence whose convergence is defined.",
            "L": "The limit the sequence converges to.",
            "N": "Index threshold beyond which all terms lie within ε of L.",
        },
        "Injektivitaet": {
            "f": "The mapping whose injectivity is being defined.",
            "X": "Domain of the injective mapping f.",
            "Y": "Codomain of the injective mapping f.",
            # NOTE: x_1 / x_2 (the tested domain elements) are deliberately left
            # OUT. They ARE bound by the injectivity definition, but re-pointing
            # their occurrences at Injektivität collapses every injectivity
            # formula symbol onto one concept, which erases the per-stub
            # co_occurring structure other layers rely on (see #21 discussion in
            # docs/ontology.md). They stay pending — like the convergence bound
            # index n — until a live LLM does finer-grained coreference.
        },
    }

    #: Semantic relation kind from a symbol's stub concept to its defining
    #: concept. A symbol *uses* (participates in) the defined object.
    _SYMBOL_TO_CONCEPT_KIND: RelationKind = "uses"

    def build_delta(self, doc: MathDocument) -> MeaningDelta:
        """Compute the meaning-resolution delta for ``doc`` (pure).

        Matching is normalisation-aware (issue #21): the defining-concept name
        and every symbol token are looked up through the folds in
        :func:`_fold_concept_name` / :func:`_normalize_symbol_token`, so the real
        Docling spellings (``Injektivität``, ``\\epsilon``, ``a _ { n }``) resolve
        the same as the synthetic fixture's canonical ones.
        """
        delta = MeaningDelta()
        concepts_by_name = _index_concepts_by_name(doc)
        concepts_by_symbol = _index_concepts_by_symbol(doc)
        occ_by_concept = _formula_symbol_occurrences_by_concept(doc)

        for concept_name, symbol_meanings in self._COREFERENCE.items():
            target = self._match_defining_concept(concept_name, concepts_by_name)
            if target is None:
                continue  # this document has no such definition; skip.
            delta.resolved_concepts.add(target.id)

            for token, meaning in symbol_meanings.items():
                stub = self._match_symbol_concept(token, concepts_by_symbol)
                if stub is None:
                    continue  # token has no concept (e.g. prose-only Y).

                # inferred_meaning on the stub (never the formal concept).
                delta.infer(stub.id, meaning)

                # semantic relation: the symbol's stub uses the defined object.
                delta.relate(stub.id, target.id, self._SYMBOL_TO_CONCEPT_KIND)
                # ... and the definition uses the symbol (defines its role).
                delta.relate(target.id, stub.id, "defines")

                # coreference: re-point every occurrence of this stub concept at
                # the defined concept so go-to-definition reaches Def 2.1 / 1.2.
                # Keyed by concept_id (not the fold-collapsed token) so linking
                # the threshold ``N`` never drags the set ``\mathbb { N }`` along.
                for occ in occ_by_concept.get(stub.id, ()):
                    delta.link(occ.id, target.id)

        return delta

    @staticmethod
    def _match_defining_concept(
        name: str, concepts_by_name: dict[str, list[Concept]]
    ) -> Optional[Concept]:
        """Find the defining (formal) concept for a table name key.

        Folds ``name`` and prefers a candidate that carries a ``formal_meaning``
        (the definition block's concept) over any bare stub that happens to fold
        to the same key.
        """
        candidates = concepts_by_name.get(_fold_concept_name(name))
        if not candidates:
            return None
        for concept in candidates:
            if concept.formal_meaning is not None:
                return concept
        return candidates[0]

    @staticmethod
    def _match_symbol_concept(
        token: str, concepts_by_symbol: dict[str, list[Concept]]
    ) -> Optional[Concept]:
        """Find the stub concept for a table symbol-token key.

        Folds ``token`` to its symbol key, then — among concepts sharing that key
        — prefers a bare (non-formal, non-set-markup) stub. This keeps the
        threshold ``N`` distinct from the set ``\\mathbb { N }`` (#20): both fold
        to key ``N``, but only the bare-letter stub is chosen for the ``N`` link.
        """
        candidates = concepts_by_symbol.get(_normalize_symbol_token(token))
        if not candidates:
            return None
        plain = [
            c
            for c in candidates
            if c.formal_meaning is None and not _is_set_markup(c.name)
        ]
        if plain:
            return plain[0]
        return candidates[0]

    def resolve(self, doc: MathDocument) -> MathDocument:
        """Apply the deterministic delta and advance the document to ``ready``."""
        doc.ingestion_state = "resolving"
        self.build_delta(doc).apply(doc)
        doc.ingestion_state = "ready"
        return doc


# ---------------------------------------------------------------------------
# Shared live-resolver machinery (prompt, parse, retry loop)
# ---------------------------------------------------------------------------


#: System prompt for the live resolvers. Documents the contract the model must
#: honour; the JSON output schema is described in :data:`OUTPUT_SCHEMA_DOC`.
SYSTEM_PROMPT = """\
You are the meaning-resolution stage of a math-document pipeline. You are given
a seeded ontology extracted from a mathematics text: a list of CONCEPTS (each
with an id, a name, and possibly an authoritative formal_meaning), a list of
formula-symbol OCCURRENCES (each with an id, a surface token, and the concept
it is currently linked to), and the surrounding block text.

Your job, WITHOUT contradicting any formal_meaning:
1. Coreference — when a formula symbol denotes an object that a definition
   introduces (e.g. the epsilon in a convergence formula is the same epsilon as
   in the convergence definition), link that occurrence to the definition's
   concept.
2. Inferred meaning — for symbols that have no formal definition, write a short
   inferred_meaning describing what the symbol denotes in context.
3. Semantic relations — add directed edges between concepts using ONLY these
   kinds: uses, defines, generalizes, specializes, instance_of.

Hard rules:
- NEVER provide or change formal_meaning. It is authoritative.
- Only reference concept ids and occurrence ids that appear in the input.
- Reply with a SINGLE JSON object and nothing else.
"""

#: Human-readable description of the JSON the model must return. Kept alongside
#: the prompt so the contract lives in one place; see ``docs/ontology.md``.
OUTPUT_SCHEMA_DOC = """\
{
  "occurrence_links": [
    {"occurrence_id": "<id>", "concept_id": "<id>"}
  ],
  "inferred_meanings": [
    {"concept_id": "<id>", "meaning": "<short prose>"}
  ],
  "relations": [
    {"source_concept_id": "<id>", "target_concept_id": "<id>",
     "kind": "uses|defines|generalizes|specializes|instance_of"}
  ]
}
"""


def build_prompt(doc: MathDocument) -> str:
    """Serialise the seeded ontology into the user prompt for the model.

    Only the fields the model needs are sent; ``formal_meaning`` is included
    read-only so the model can corefer against it but is told never to change it
    (see :data:`SYSTEM_PROMPT`). Shared by every live resolver.
    """
    concepts = [
        {
            "id": c.id,
            "name": c.name,
            "formal_meaning": c.formal_meaning,
            "resolution_status": c.resolution_status,
        }
        for c in doc.concepts
    ]
    formulas = {b.id: b for b in iter_blocks(doc.blocks) if isinstance(b, Formula)}
    occurrences = []
    for occ in doc.occurrences:
        token = None
        if occ.kind == "formula_symbol" and occ.span is not None:
            formula = formulas.get(occ.block_id)
            if formula is not None:
                token = formula.canonical_content[occ.span[0] : occ.span[1]]
        occurrences.append(
            {
                "id": occ.id,
                "kind": occ.kind,
                "token": token,
                "block_id": occ.block_id,
                "concept_id": occ.concept_id,
            }
        )
    payload = {"concepts": concepts, "occurrences": occurrences}
    return (
        "Resolve the meaning of this seeded ontology. Return JSON matching "
        "this schema exactly:\n"
        f"{OUTPUT_SCHEMA_DOC}\n"
        "Ontology:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def parse_response(text: str, doc: MathDocument) -> MeaningDelta:
    """Parse the model's JSON reply into a :class:`MeaningDelta`.

    Raises ``ValueError`` if the reply is not the documented JSON object; the
    caller treats that as a retryable failure. Shared by every live resolver.
    The ``doc`` argument is accepted for signature symmetry with
    :func:`build_prompt` (the delta is validated against the document on apply).
    """
    data = json.loads(_extract_json(text))
    if not isinstance(data, dict):
        raise ValueError("model reply was not a JSON object")

    delta = MeaningDelta()
    for link in data.get("occurrence_links", []) or []:
        occ_id = link.get("occurrence_id")
        concept_id = link.get("concept_id")
        if isinstance(occ_id, str) and isinstance(concept_id, str):
            delta.link(occ_id, concept_id)
    for item in data.get("inferred_meanings", []) or []:
        concept_id = item.get("concept_id")
        meaning = item.get("meaning")
        if isinstance(concept_id, str) and isinstance(meaning, str):
            delta.infer(concept_id, meaning)
    for rel in data.get("relations", []) or []:
        src = rel.get("source_concept_id")
        tgt = rel.get("target_concept_id")
        kind = rel.get("kind")
        if (
            isinstance(src, str)
            and isinstance(tgt, str)
            and kind in _SEMANTIC_KINDS
        ):
            delta.relate(src, tgt, kind)  # type: ignore[arg-type]
    return delta


def resolve_via_completion(
    doc: MathDocument,
    complete: Callable[[str], str],
    *,
    max_retries: int = 2,
) -> MathDocument:
    """Run the shared resolve loop, parameterised by a one-shot ``complete``.

    Builds the prompt, then up to ``max_retries`` + 1 times: calls ``complete``
    (the provider-specific single completion), parses the reply via
    :func:`parse_response`, applies the delta, and advances the document to
    ``ready``. On any API or parse error the attempt is retried; if every
    attempt fails the document is returned with whatever partial results were
    applied (often none) and ``ingestion_state`` is left at ``resolving`` rather
    than ``ready`` — the pipeline is never crashed.
    """
    doc.ingestion_state = "resolving"
    prompt = build_prompt(doc)

    last_error: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            text = complete(prompt)
            delta = parse_response(text, doc)
        except Exception as exc:  # noqa: BLE001 - resolver must not crash
            last_error = exc
            logger.warning(
                "resolve attempt %d/%d failed: %s",
                attempt + 1,
                max_retries + 1,
                exc,
            )
            continue
        delta.apply(doc)
        doc.ingestion_state = "ready"
        return doc

    logger.error(
        "resolve exhausted %d attempts; returning partial doc (%s)",
        max_retries + 1,
        last_error,
    )
    return doc  # PARTIAL: state stays "resolving", no exception propagated.


# ---------------------------------------------------------------------------
# AnthropicResolver — live LLM, fault-tolerant
# ---------------------------------------------------------------------------


class AnthropicResolver:
    """A :class:`Resolver` backed by the Anthropic Messages API.

    Parameters
    ----------
    model:
        Anthropic model id. Defaults to :data:`DEFAULT_MODEL`
        (``"claude-sonnet-4-6"``).
    api_key:
        Overrides ``ANTHROPIC_API_KEY`` from the environment when given.
    max_retries:
        How many times to retry on an API or response-parse error before
        giving up. After the budget is exhausted the document is returned with
        whatever partial results were applied — the pipeline is never crashed.
    max_tokens:
        Output-token cap for the single completion.

    Prompt-building, parsing and the retry loop are the shared module-level
    functions :func:`build_prompt` / :func:`parse_response` /
    :func:`resolve_via_completion`; only :meth:`_complete` is provider-specific.
    The ``anthropic`` package is imported lazily inside :meth:`_complete` so
    importing this module (and running the offline tests) never requires the SDK
    or a key.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
        max_retries: int = 2,
        max_tokens: int = 4096,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.max_retries = max_retries
        self.max_tokens = max_tokens

    # -- shared machinery, exposed as thin instance methods (back-compat) ----

    def build_prompt(self, doc: MathDocument) -> str:
        """Delegate to the module-level :func:`build_prompt`."""
        return build_prompt(doc)

    def parse_response(self, text: str, doc: MathDocument) -> MeaningDelta:
        """Delegate to the module-level :func:`parse_response`."""
        return parse_response(text, doc)

    # -- the resolve loop ---------------------------------------------------

    def resolve(self, doc: MathDocument) -> MathDocument:
        """Resolve via the API, tolerating failure with partial results.

        Routes through the shared :func:`resolve_via_completion`, supplying the
        Anthropic-specific one-shot :meth:`_complete`.
        """
        return resolve_via_completion(
            doc, self._complete, max_retries=self.max_retries
        )

    def _complete(self, prompt: str) -> str:
        """Run one completion and return the model's text. Lazy SDK import."""
        import anthropic  # lazy: importing this module never needs the SDK.

        client = anthropic.Anthropic(
            api_key=self.api_key or os.environ.get("ANTHROPIC_API_KEY")
        )
        message = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [
            block.text
            for block in message.content
            if getattr(block, "type", None) == "text"
        ]
        if not parts:
            raise ValueError("model returned no text content")
        return "".join(parts)


# ---------------------------------------------------------------------------
# OpenAIResolver — live LLM, fault-tolerant
# ---------------------------------------------------------------------------


class OpenAIResolver:
    """A :class:`Resolver` backed by the OpenAI Chat Completions API.

    Parameters
    ----------
    model:
        OpenAI model id. Defaults to :data:`DEFAULT_OPENAI_MODEL` (``"gpt-4o"``),
        overridable via the ``OPENAI_MODEL`` environment variable or this arg.
    api_key:
        Overrides ``OPENAI_API_KEY`` from the environment when given.
    max_retries:
        How many times to retry on an API or response-parse error before giving
        up. After the budget is exhausted the document is returned with whatever
        partial results were applied — the pipeline is never crashed.
    max_tokens:
        Output-token cap for the single completion.

    Prompt-building, parsing and the retry loop are the shared module-level
    functions :func:`build_prompt` / :func:`parse_response` /
    :func:`resolve_via_completion`; only :meth:`_complete` is provider-specific.
    The ``openai`` package is imported lazily inside :meth:`_complete` so
    importing this module (and running the offline tests) never requires the SDK
    or a key.
    """

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        max_retries: int = 2,
        max_tokens: int = 4096,
    ) -> None:
        self.model = model or os.environ.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
        self.api_key = api_key
        self.max_retries = max_retries
        self.max_tokens = max_tokens

    # -- shared machinery, exposed as thin instance methods (back-compat) ----

    def build_prompt(self, doc: MathDocument) -> str:
        """Delegate to the module-level :func:`build_prompt`."""
        return build_prompt(doc)

    def parse_response(self, text: str, doc: MathDocument) -> MeaningDelta:
        """Delegate to the module-level :func:`parse_response`."""
        return parse_response(text, doc)

    # -- the resolve loop ---------------------------------------------------

    def resolve(self, doc: MathDocument) -> MathDocument:
        """Resolve via the API, tolerating failure with partial results.

        Routes through the shared :func:`resolve_via_completion`, supplying the
        OpenAI-specific one-shot :meth:`_complete`.
        """
        return resolve_via_completion(
            doc, self._complete, max_retries=self.max_retries
        )

    def _complete(self, prompt: str) -> str:
        """Run one completion and return the model's text. Lazy SDK import."""
        import openai  # lazy: importing this module never needs the SDK.

        client = openai.OpenAI(
            api_key=self.api_key or os.environ.get("OPENAI_API_KEY")
        )
        resp = client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        content = resp.choices[0].message.content
        if not content:
            raise ValueError("model returned no text content")
        return content


# ---------------------------------------------------------------------------
# auto_resolver — pick a resolver from the environment
# ---------------------------------------------------------------------------


def auto_resolver() -> Resolver:
    """Pick a :class:`Resolver` from the environment.

    Preference order:

    1. ``ANTHROPIC_API_KEY`` set -> :class:`AnthropicResolver`.
    2. else ``OPENAI_API_KEY`` set -> :class:`OpenAIResolver`.
    3. else :class:`MockResolver`, with a one-line warning to ``stderr``.

    Constructing the live resolvers never imports their SDKs (the imports are
    lazy in ``_complete``), so this factory works fully offline.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicResolver()
    if os.environ.get("OPENAI_API_KEY"):
        return OpenAIResolver()
    print(
        "auto resolver: no ANTHROPIC_API_KEY or OPENAI_API_KEY set; "
        "falling back to offline MockResolver.",
        file=sys.stderr,
    )
    return MockResolver()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _extract_json(text: str) -> str:
    """Return the JSON object substring from a model reply.

    The model is asked for a bare JSON object, but tolerate a fenced code block
    or surrounding prose by slicing from the first ``{`` to the last ``}``.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        # drop a leading ```json / ``` fence and the trailing fence.
        stripped = stripped.split("```", 2)
        stripped = stripped[1] if len(stripped) > 1 else text
        if stripped.startswith("json"):
            stripped = stripped[len("json") :]
        stripped = stripped.strip().rstrip("`").strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in model reply")
    return stripped[start : end + 1]
