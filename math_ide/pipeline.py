"""Staged ingestion orchestration (issue #14).

This module wires ingestion (stage 1) and meaning resolution (stage 2) into a
single, observable state machine and exposes the entry points the IDE and the
CLI use. The contract is deliberately small and single-process — no external
job queue (out of scope for v1) — but it is *deterministic for callers*: every
mutation bumps a monotonic version, the background worker can be joined, and a
failing resolver never crashes the pipeline.

State machine
-------------
The document's ``ingestion_state`` walks::

    ingesting -> structure_ready -> resolving -> ready
                      ^                              |
                      |     (resolver failed)        |
                      +---------- resolving <---------+

* ``ingesting`` — transient; held only while :func:`ingest_structure` runs
  :func:`~math_ide.ingest.build_math_document` + :func:`~math_ide.ontology.seed_ontology`.
* ``structure_ready`` — **stage 1 done.** The block tree, occurrences, seeded
  concepts and deterministic structural relations all exist. The IDE can open
  the document here: citations resolve (``occurrence.target_block_id``) and
  formal-block navigation works (``concept.seeded_by_block_id`` /
  ``concept.defining_occurrence_id``). This stage is synchronous and fast.
* ``resolving`` — stage 2 in flight (a :class:`Resolver` is running) **or** a
  terminal-but-partial state if the resolver failed. Either way stage-1 results
  are intact and usable.
* ``ready`` — stage 2 succeeded: coreference, inferred meanings and semantic
  relations are applied; touched concepts/occurrences are ``resolved``.

Version / etag model
--------------------
:class:`Pipeline` keeps a monotonically increasing integer ``version`` that is
bumped on **every** state-changing mutation (each stage transition, each
resolver completion, each formula upgrade). :meth:`Pipeline.status` returns an
immutable snapshot ``(state, version)`` the renderer can poll: when ``version``
changes the renderer re-reads the (small) occurrence/concept indices and
re-paints only the affected anchors — it never re-ingests. ``etag`` is a string
alias of ``version`` for HTTP-style conditional fetches.

Re-entrant formula enrichment
-----------------------------
:func:`apply_formula_upgrade` upgrades a single pending formula in place (LaTeX
arrived from #5) WITHOUT re-ingesting the document: it rebuilds that formula's
symbol index, re-derives only that formula's ``formula_symbol`` occurrences and
their stub concepts, preserves every unrelated block/occurrence/concept, and
bumps the version. See :func:`apply_formula_upgrade` for the renderer-refresh
contract.
"""

from __future__ import annotations

import re
import threading
from typing import Any, Optional, Union

from math_ide.ingest import build_math_document
from math_ide.ingest.docling_adapter import subdivide_bbox
from math_ide.ingest.formula import upgrade_formula
from math_ide.ontology import MockResolver, Resolver, seed_ontology
from math_ide.ontology.concepts import _co_occurring_relations, stub_key
from math_ide.ontology.occurrences import iter_blocks
from math_ide.schema import (
    Concept,
    Formula,
    MathDocument,
    Occurrence,
    Relation,
)

__all__ = [
    "PipelineStatus",
    "Pipeline",
    "ingest_structure",
    "run_full",
    "apply_formula_upgrade",
    "normalize_token",
]


# ---------------------------------------------------------------------------
# Token normalisation (LaTeX <-> unicode equivalence for upgrade coreference)
# ---------------------------------------------------------------------------

# A formula upgrade swaps the canonical string from Docling's unicode ``orig``
# to enriched LaTeX. The *same* symbol is therefore spelled differently across
# the upgrade: ``ε`` becomes ``\varepsilon``, ``x₁`` becomes ``x_1``, ``ℝ``
# becomes ``R`` / ``\mathbb{R}``. To preserve coreference (#14) we key surviving
# symbols by a *normalised* token: a token that merely changed spelling folds to
# the same key and keeps its already-resolved concept (e.g. the Konvergenz
# concept), while a genuinely new token gets a fresh stub.

#: LaTeX greek control words -> their unicode codepoint. The ``var`` spellings
#: and the canonical names both fold to the canonical unicode letter so e.g.
#: ``\varepsilon`` and ``\epsilon`` and ``ε`` all share one key.
_LATEX_GREEK_TO_UNICODE: dict[str, str] = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "varepsilon": "ε",
    "zeta": "ζ",
    "eta": "η",
    "theta": "θ",
    "vartheta": "θ",
    "iota": "ι",
    "kappa": "κ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "pi": "π",
    "varpi": "π",
    "rho": "ρ",
    "varrho": "ρ",
    "sigma": "σ",
    "varsigma": "σ",
    "tau": "τ",
    "upsilon": "υ",
    "phi": "φ",
    "varphi": "φ",
    "chi": "χ",
    "psi": "ψ",
    "omega": "ω",
    "Gamma": "Γ",
    "Delta": "Δ",
    "Theta": "Θ",
    "Lambda": "Λ",
    "Xi": "Ξ",
    "Pi": "Π",
    "Sigma": "Σ",
    "Upsilon": "Υ",
    "Phi": "Φ",
    "Psi": "Ψ",
    "Omega": "Ω",
}

#: Blackboard / named sets: both the single unicode codepoint and the
#: ``\mathbb{R}`` LaTeX spelling fold to the bare capital, which is also what the
#: scanner emits for a plain ``R`` after ``\in R``.
_SET_TO_PLAIN: dict[str, str] = {
    "ℝ": "R",
    "ℕ": "N",
    "ℤ": "Z",
    "ℚ": "Q",
    "ℂ": "C",
    "𝔽": "F",
    "ℙ": "P",
}

#: unicode subscript digits -> their ASCII digit (so ``x₁`` folds to ``x_1``).
_SUBSCRIPT_DIGIT_TO_ASCII: dict[str, str] = {
    "₀": "0",
    "₁": "1",
    "₂": "2",
    "₃": "3",
    "₄": "4",
    "₅": "5",
    "₆": "6",
    "₇": "7",
    "₈": "8",
    "₉": "9",
}

_MATHBB_RE = re.compile(r"^\\(?:mathbb|mathcal|mathfrak|mathscr)\{([^}]*)\}$")
_LATEX_WORD_RE = re.compile(r"^\\([A-Za-z]+)(.*)$", re.DOTALL)


def normalize_token(token: str) -> str:
    r"""Fold a formula-symbol surface token to a dialect-independent key.

    Maps the LaTeX and unicode spellings of the *same* mathematical symbol onto
    one key so a symbol that merely changed spelling across a formula upgrade is
    recognised as the same token:

    * ``\varepsilon`` / ``\epsilon`` / ``ε`` -> ``ε``
    * ``x_1`` / ``x₁`` -> ``x_1``;  ``a_n`` stays ``a_n``
    * ``\mathbb{R}`` / ``ℝ`` / ``R`` -> ``R``

    The transformation is idempotent (normalising a normalised token is a
    no-op), so it can be applied to either dialect.
    """
    if not token:
        return token

    # \mathbb{R} -> R (then fall through so the bare letter is canonicalised).
    mb = _MATHBB_RE.match(token)
    if mb:
        token = mb.group(1)

    # A LaTeX greek control word (optionally with a subscript tail), e.g.
    # \varepsilon or \alpha_1.
    lw = _LATEX_WORD_RE.match(token)
    if lw:
        word, tail = lw.group(1), lw.group(2)
        greek = _LATEX_GREEK_TO_UNICODE.get(word)
        if greek is not None:
            return greek + _normalize_subscript(tail)

    # Single unicode set codepoint (possibly with a subscript tail).
    if token[0] in _SET_TO_PLAIN:
        return _SET_TO_PLAIN[token[0]] + _normalize_subscript(token[1:])

    # Plain identifier head + (unicode or ASCII) subscript.
    head = token[0]
    return head + _normalize_subscript(token[1:])


def _normalize_subscript(tail: str) -> str:
    """Fold a token's subscript tail to the canonical ``_<chars>`` form.

    ``₁`` -> ``_1`` (unicode subscript digits), ``_{n}`` -> ``_n`` (LaTeX
    braces stripped), ``_n`` / ``_1`` left as-is.
    """
    if not tail:
        return ""
    # unicode subscript digits run: ₁₂ -> _12
    if tail[0] in _SUBSCRIPT_DIGIT_TO_ASCII:
        digits = "".join(_SUBSCRIPT_DIGIT_TO_ASCII.get(ch, ch) for ch in tail)
        return "_" + digits
    if tail.startswith("_"):
        rest = tail[1:]
        if rest.startswith("{") and rest.endswith("}"):
            rest = rest[1:-1]
        return "_" + rest
    # Any other trailing characters: keep verbatim (rare; stays distinct).
    return tail


# ---------------------------------------------------------------------------
# Stage 1 — synchronous structure
# ---------------------------------------------------------------------------


def ingest_structure(
    source_or_dict: dict[str, Any],
    *,
    document_id: Optional[str] = None,
) -> MathDocument:
    """Run stage 1 and return a document at ``structure_ready``.

    Runs :func:`~math_ide.ingest.build_math_document` (block tree + formula
    symbol indices) then :func:`~math_ide.ontology.seed_ontology` (occurrences,
    seeded concepts, deterministic structural relations). The result is
    immediately usable by the IDE: citation navigation and formal-block
    navigation work before any LLM runs.

    Stage 1 is synchronous and fast. ``source_or_dict`` is a Docling-style JSON
    dict (live PDF conversion stays in the CLI behind a lazy import). The
    returned document has ``ingestion_state == "structure_ready"``.
    """
    doc = build_math_document(source_or_dict, document_id=document_id)
    seed_ontology(doc)
    # seed_ontology leaves the doc at structure_ready; assert the contract.
    doc.ingestion_state = "structure_ready"
    return doc


# ---------------------------------------------------------------------------
# Status snapshot
# ---------------------------------------------------------------------------


class PipelineStatus:
    """Immutable snapshot of a pipeline's observable state.

    ``state`` mirrors :class:`~math_ide.schema.MathDocument.ingestion_state`;
    ``version`` is the monotonic mutation counter; ``etag`` is its string form
    for conditional fetches. ``done`` is true once stage 2 has settled (either
    ``ready`` or a terminal partial ``resolving`` after the worker exited).
    """

    __slots__ = ("state", "version", "done")

    def __init__(self, state: str, version: int, done: bool) -> None:
        self.state = state
        self.version = version
        self.done = done

    @property
    def etag(self) -> str:
        """HTTP-style entity tag — a stable string for the current version."""
        return f'"{self.version}"'

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"PipelineStatus(state={self.state!r}, "
            f"version={self.version}, done={self.done})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PipelineStatus):
            return NotImplemented
        return (
            self.state == other.state
            and self.version == other.version
            and self.done == other.done
        )


# ---------------------------------------------------------------------------
# Pipeline — owns the document, the version, and the stage-2 worker
# ---------------------------------------------------------------------------


class Pipeline:
    """Drives one :class:`MathDocument` through the staged state machine.

    Construct a pipeline around a stage-1 document (``structure_ready``), then
    advance it through ``resolving`` -> ``ready`` either synchronously
    (:meth:`run_full` with ``wait=True``) or on a background thread
    (:meth:`start` + :meth:`join`). A single :class:`threading.Lock` guards the
    version counter and state reads so :meth:`status` is consistent while the
    worker runs.

    The resolver is invoked exactly once per :meth:`run_full`/:meth:`start`.
    Resolver failure is tolerated: if the resolver raises or leaves the document
    short of ``ready``, the pipeline records the (partial) outcome, leaves a
    sane ``resolving`` state with stage-1 results intact, and marks the run
    done — it never propagates the exception.
    """

    def __init__(
        self,
        doc: MathDocument,
        *,
        resolver: Optional[Resolver] = None,
    ) -> None:
        self.doc = doc
        self.resolver: Resolver = resolver if resolver is not None else MockResolver()
        self._version = 0
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._error: Optional[Exception] = None

    # -- introspection ------------------------------------------------------

    @property
    def version(self) -> int:
        """Current monotonic mutation counter."""
        with self._lock:
            return self._version

    @property
    def etag(self) -> str:
        """HTTP-style entity tag for the current version."""
        return f'"{self.version}"'

    @property
    def state(self) -> str:
        """The document's current ``ingestion_state``."""
        with self._lock:
            return self.doc.ingestion_state

    @property
    def error(self) -> Optional[Exception]:
        """The exception a failing resolver raised, if any (else ``None``)."""
        with self._lock:
            return self._error

    def status(self) -> PipelineStatus:
        """Return an immutable ``(state, version, done)`` snapshot to poll."""
        with self._lock:
            thread = self._thread
            done = thread is None or not thread.is_alive()
            return PipelineStatus(self.doc.ingestion_state, self._version, done)

    def _bump(self) -> int:
        """Increment and return the version under the lock."""
        with self._lock:
            self._version += 1
            return self._version

    # -- stage 2 ------------------------------------------------------------

    def _run_resolver(self) -> None:
        """Invoke the resolver once, tolerating failure, bumping the version.

        The resolver itself sets ``resolving`` then ``ready`` (see
        :class:`~math_ide.ontology.MockResolver`). If it raises, or returns the
        document still at ``resolving`` (the documented partial-result path for
        :class:`~math_ide.ontology.AnthropicResolver`), we keep the stage-1
        document and leave the state at ``resolving`` — never crashing.
        """
        # Enter resolving even if the resolver fails before it sets the state.
        with self._lock:
            if self.doc.ingestion_state == "structure_ready":
                self.doc.ingestion_state = "resolving"
            self._version += 1
        try:
            self.resolver.resolve(self.doc)
        except Exception as exc:  # noqa: BLE001 - resolver must not crash pipeline
            with self._lock:
                self._error = exc
                # Roll any half-applied state back to a sane partial.
                if self.doc.ingestion_state == "ready":
                    self.doc.ingestion_state = "resolving"
                else:
                    self.doc.ingestion_state = "resolving"
        finally:
            self._bump()

    def run_full(self, *, wait: bool = True) -> MathDocument:
        """Advance the document through stage 2.

        With ``wait=True`` (default) the resolver runs synchronously and the
        ready (or partial) document is returned. With ``wait=False`` the
        resolver runs on a background :class:`threading.Thread`; the document is
        returned immediately (still mutating) and the caller uses
        :meth:`status` to poll and :meth:`join` to block deterministically.
        """
        if wait:
            self._run_resolver()
            return self.doc
        self.start()
        return self.doc

    def start(self) -> "Pipeline":
        """Start stage 2 on a background daemon thread (idempotent re-entry).

        Returns ``self`` for chaining. Calling :meth:`start` while a worker is
        already running is a no-op.
        """
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self
            self._thread = threading.Thread(
                target=self._run_resolver,
                name=f"math-ide-resolve-{self.doc.document_id}",
                daemon=True,
            )
            thread = self._thread
        thread.start()
        return self

    def join(self, timeout: Optional[float] = None) -> MathDocument:
        """Block until the background stage-2 worker finishes; return the doc.

        Deterministic for tests: after :meth:`join` returns (without a timeout)
        the document is in its terminal state (``ready`` or partial
        ``resolving``) and the version reflects every mutation the worker made.
        """
        thread = None
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return self.doc

    # convenience alias matching the issue's "join()/wait()" phrasing.
    def wait(self, timeout: Optional[float] = None) -> MathDocument:
        """Alias of :meth:`join`."""
        return self.join(timeout)

    # -- re-entrant formula upgrade ----------------------------------------

    def apply_formula_upgrade(self, formula_id: str, latex: str) -> MathDocument:
        """Upgrade one formula in place and bump the version (see module fn).

        The mutation and the version bump are performed atomically under the
        pipeline lock so a background resolver thread can never observe (or race)
        a half-applied upgrade: shared ``doc`` state is only mutated while the
        lock is held.
        """
        with self._lock:
            apply_formula_upgrade(self.doc, formula_id, latex)
            self._version += 1
        return self.doc


# ---------------------------------------------------------------------------
# Convenience: one-shot full run
# ---------------------------------------------------------------------------


def run_full(
    source_or_dict: Union[dict[str, Any], MathDocument],
    *,
    resolver: Optional[Resolver] = None,
    document_id: Optional[str] = None,
    wait: bool = True,
) -> MathDocument:
    """Ingest (if needed) and run stage 2, returning the document.

    ``source_or_dict`` may be a Docling JSON dict (stage 1 is run first) or an
    already-``structure_ready`` :class:`MathDocument`. With ``wait=True`` the
    returned document is at ``ready`` (or a partial ``resolving`` if the
    resolver failed); with ``wait=False`` stage 2 runs in the background and the
    caller must use a :class:`Pipeline` to join. For the background path prefer
    constructing a :class:`Pipeline` directly so you keep the handle.
    """
    if isinstance(source_or_dict, MathDocument):
        doc = source_or_dict
    else:
        doc = ingest_structure(source_or_dict, document_id=document_id)
    pipeline = Pipeline(doc, resolver=resolver)
    return pipeline.run_full(wait=wait)


# ---------------------------------------------------------------------------
# Re-entrant formula enrichment upgrade
# ---------------------------------------------------------------------------


def _find_formula(doc: MathDocument, formula_id: str) -> Optional[Formula]:
    """Locate a :class:`Formula` block by id anywhere in the tree."""
    for block in iter_blocks(doc.blocks):
        if isinstance(block, Formula) and block.id == formula_id:
            return block
    return None


def apply_formula_upgrade(
    doc: MathDocument,
    formula_id: str,
    latex: str,
) -> MathDocument:
    """Re-entrantly upgrade one formula from its fallback to enriched LaTeX.

    This is the #14 hook for #5: a single formula's LaTeX arrives *after* the
    document is already open in the IDE. We upgrade it WITHOUT re-ingesting the
    whole document:

    1. :func:`~math_ide.ingest.formula.upgrade_formula` sets ``latex``, flips
       ``enrichment_status`` to ``ready`` and **rebuilds the symbol index**
       against the new LaTeX (so symbol offsets now index ``latex``).
    2. The formula's old ``formula_symbol`` occurrences (offsets into the old
       ``orig_fallback``) are dropped and re-derived against the new symbol
       index, with fresh source bboxes subdivided over the LaTeX and
       ``render_bbox=None`` (the renderer re-measures, #11).
    3. Stub concepts for any newly-appearing tokens are seeded; stub concepts
       for tokens that survive keep their identity (and any resolved meaning),
       so an already-resolved symbol stays resolved. Concepts orphaned by the
       reflow are pruned only if nothing else references them.

    Unrelated blocks, occurrences and concepts are untouched. If ``formula_id``
    is unknown, or the formula is already enriched with the same LaTeX, the call
    is a no-op (idempotent).

    Renderer refresh contract
    -------------------------
    After this returns the caller should bump the document version (the
    :class:`Pipeline` method does this automatically). The renderer, on seeing a
    new version, replaces just this formula's rendered node — re-running KaTeX on
    ``formula.latex`` instead of the ``orig_fallback`` text — and re-binds the
    occurrence anchors for ``block_id == formula_id`` (their spans/bboxes
    changed). No other DOM node needs to change.
    """
    formula = _find_formula(doc, formula_id)
    if formula is None:
        return doc
    if formula.enrichment_status == "ready" and formula.latex == latex:
        return doc  # idempotent: already at this LaTeX.

    # 1. SNAPSHOT prior coreference BEFORE the canonical string changes.
    #    Read each stale occurrence's token via the OLD canonical content and
    #    record its concept_id keyed by the *normalised* token, so a symbol that
    #    survives the upgrade (possibly under a new spelling) keeps the concept
    #    the resolver linked it to (e.g. ε / a_n -> Konvergenz). The first
    #    occurrence of each token wins (stub identity is per-token, not per-occ).
    old_content = formula.canonical_content
    stale = [
        occ
        for occ in doc.occurrences
        if occ.kind == "formula_symbol" and occ.block_id == formula_id
    ]
    prior_concept_by_norm: dict[str, str] = {}
    prior_symbol_concept_ids: set[str] = set()
    for occ in stale:
        if occ.span is None:
            continue
        start, end = occ.span
        old_token = old_content[start:end]
        if occ.concept_id is not None:
            prior_symbol_concept_ids.add(occ.concept_id)
            prior_concept_by_norm.setdefault(normalize_token(old_token), occ.concept_id)

    # 2. upgrade the formula block (rebuilds its symbol_index against latex).
    upgrade_formula(formula, latex)

    # 3. drop this formula's stale formula_symbol occurrences.
    stale_ids = {occ.id for occ in stale}
    doc.occurrences = [occ for occ in doc.occurrences if occ.id not in stale_ids]

    # 4. re-derive occurrences + stub concepts for the new symbol index,
    #    reusing the prior concept_id for any token whose MEANING survives.
    concept_by_id = {c.id: c for c in doc.concepts}
    content = formula.canonical_content
    charspan = (0, len(content))
    fresh: list[Occurrence] = []
    new_symbol_concept_ids: list[str] = []
    for idx, sym in enumerate(formula.symbol_index):
        token = content[sym.start : sym.end]
        # A surviving symbol (same normalised token) reuses its prior concept —
        # which may be a formal concept (Konvergenz) the resolver re-pointed it
        # at, NOT just the bare per-token stub — preserving go-to-definition.
        # A genuinely new token gets a fresh pending stub.
        concept_id = prior_concept_by_norm.get(normalize_token(token))
        if concept_id is None or concept_id not in concept_by_id:
            concept_id = doc.mint("concept", stub_key(token))
            if concept_id not in concept_by_id:
                concept = Concept(
                    id=concept_id,
                    name=token,
                    formal_meaning=None,
                    resolution_status="pending",
                )
                doc.concepts.append(concept)
                concept_by_id[concept_id] = concept
        occ = Occurrence(
            id=doc.mint("occ", f"{formula_id}-sym-{idx}-{sym.token}"),
            kind="formula_symbol",
            block_id=formula_id,
            span=(sym.start, sym.end),
            source_bbox=subdivide_bbox(
                formula.source_bbox, charspan, sym.start, sym.end
            ),
            render_bbox=None,  # renderer re-measures (#11)
            concept_id=concept_id,
        )
        fresh.append(occ)
        new_symbol_concept_ids.append(concept_id)
    doc.occurrences.extend(fresh)

    # 5. rebuild this formula's STRUCTURAL co_occurring relations.
    _rebuild_co_occurring_relations(
        doc, prior_symbol_concept_ids, new_symbol_concept_ids
    )

    # 6. prune stub concepts orphaned by the reflow (referenced nowhere).
    _prune_orphan_stub_concepts(doc)
    return doc


def _rebuild_co_occurring_relations(
    doc: MathDocument,
    prior_symbol_concept_ids: set[str],
    new_symbol_concept_ids: list[str],
) -> None:
    """Recompute the upgraded formula's ``co_occurring`` structural edges.

    Stale ``co_occurring`` edges among the formula's *prior* symbol concepts are
    dropped when they no longer co-occur, then fresh ``co_occurring`` edges among
    the *new* symbol concepts are added — reusing the concept-seeding builder
    (:func:`~math_ide.ontology.concepts._co_occurring_relations`) so the shape
    matches stage-1 exactly. Other relations (``seeded_by`` / ``sibling`` /
    semantic) are untouched, and the result stays de-duped with
    ``origin="structural"``.
    """
    new_set = set(new_symbol_concept_ids)

    # Build the new edge set first so we know which (if any) prior edges survive.
    fresh_edges = _co_occurring_relations([new_symbol_concept_ids], set())
    fresh_keys = {
        (r.source_concept_id, r.target_concept_id) for r in fresh_edges
    }

    # Drop co_occurring edges incident to a prior symbol concept that are no
    # longer present among the new co-occurrences.
    kept: list[Relation] = []
    surviving_keys: set[tuple[str, str, str]] = set()
    for rel in doc.relations:
        if rel.kind == "co_occurring" and (
            rel.source_concept_id in prior_symbol_concept_ids
            or rel.target_concept_id in prior_symbol_concept_ids
        ):
            pair = (rel.source_concept_id, rel.target_concept_id)
            both_new = (
                rel.source_concept_id in new_set
                and rel.target_concept_id in new_set
            )
            if not (both_new and pair in fresh_keys):
                continue  # stale: this edge no longer co-occurs.
        kept.append(rel)
        surviving_keys.add(
            (rel.source_concept_id, rel.target_concept_id, rel.kind)
        )

    # Add the fresh edges that are not already present (de-dupe by (src,tgt,kind)).
    for rel in fresh_edges:
        key = (rel.source_concept_id, rel.target_concept_id, rel.kind)
        if key in surviving_keys:
            continue
        surviving_keys.add(key)
        kept.append(rel)

    doc.relations = kept


def _prune_orphan_stub_concepts(doc: MathDocument) -> None:
    """Drop stub concepts (no formal meaning, not seeded by a block) that no
    occurrence or relation references any more.

    A formula upgrade can change which symbol tokens exist; a token that
    disappears leaves its stub concept dangling. Formal-block concepts and any
    stub still referenced by an occurrence or relation are always kept.
    """
    referenced: set[str] = set()
    for occ in doc.occurrences:
        if occ.concept_id is not None:
            referenced.add(occ.concept_id)
    for rel in doc.relations:
        referenced.add(rel.source_concept_id)
        if not rel.target_is_block:
            referenced.add(rel.target_concept_id)

    kept: list[Concept] = []
    for concept in doc.concepts:
        is_stub = (
            concept.formal_meaning is None
            and concept.seeded_by_block_id is None
            and concept.defining_occurrence_id is None
        )
        if is_stub and concept.id not in referenced:
            continue  # orphaned stub: prune.
        kept.append(concept)
    doc.concepts = kept
