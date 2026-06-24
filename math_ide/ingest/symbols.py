r"""Symbol-index extraction from a formula's canonical content (issue #6).

A :class:`~math_ide.schema.Formula` carries a ``symbol_index``: the spans of
the mathematical *identifiers* it mentions, with character offsets into
whichever string is currently canonical (``latex`` when enrichment is ready,
otherwise ``orig_fallback``). Those spans seed formula-symbol occurrences and,
later, render bboxes.

We deliberately keep this a small, deterministic, regex-driven scanner rather
than a real LaTeX/math parser: ingestion must run offline and the downstream
ontology only needs the *identifiers*, not a parse tree.

Two input dialects are supported transparently:

* **Unicode ``orig``** as Docling linearizes it, e.g.
  ``∀ x₁, x₂ ∈ X : f(x₁)=f(x₂) ⇒ x₁=x₂`` or
  ``∀ ε>0 ∃ N∈ℝ ∀ n≥N:|a_n−L|<ε`` (Greek letters, sub/superscript digits).
* **LaTeX**, e.g. ``\forall x_1,x_2 \in X : f(x_1)=f(x_2) \Rightarrow x_1=x_2``
  (``\varepsilon``, ``x_1``, ``\mathbb{R}`` ...).

Operator-skip rule
------------------
A *symbol* is something that denotes a mathematical object (a variable,
function name, constant or named set). We skip everything that is pure
*structure* — quantifiers, relations, connectives, set membership, arithmetic
and grouping. Concretely we never emit a span for:

* quantifiers / logic: ``∀ ∃ ⇒ ⇔ → ↦ ∧ ∨ ¬`` and their LaTeX spellings
  (``\forall \exists \Rightarrow \rightarrow \implies \land \lor`` ...);
* relations: ``= ≠ < > ≤ ≥ ∈ ∉ ⊂ ⊆ ⊇ ⊃ :`` (and ``\in \le \ge \neq`` ...);
* arithmetic / grouping / punctuation: ``+ - − * / · ( ) [ ] { } | , .`` and
  whitespace.

What we *do* emit (with the :class:`SymbolKind` we tag it):

* single Latin letters -> ``function`` if immediately followed by ``(`` else
  ``variable`` (so ``f`` in ``f(x_1)`` is a function, ``X`` is a variable);
* Greek letters (unicode ``ε`` or LaTeX ``\varepsilon``/``\alpha`` ...)
  -> ``variable``;
* blackboard / named sets (unicode ``ℝ ℕ ℤ ℚ ℂ`` or LaTeX ``\mathbb{R}``)
  -> ``set``;
* subscripted identifiers ``x_1``, ``a_n`` (LaTeX ``x_1``/``a_{n}`` or unicode
  ``x₁``/``a_n``) keep the subscript as part of the token -> ``variable``.

Tokens are returned in left-to-right order; duplicate surface tokens at
different offsets each get their own :class:`~math_ide.schema.SymbolSpan`.
"""

from __future__ import annotations

import re
import unicodedata

from math_ide.schema import SymbolSpan, SymbolKind

__all__ = ["extract_symbol_index"]


# --- unicode sub/superscript digit folding ---------------------------------
# Docling linearizes "x_1" as "x₁"; normalise to ASCII so tokens match the
# LaTeX dialect ("x_1") and the symbol index is dialect-independent in *value*
# (offsets always index the original canonical string).
_SUBSCRIPT_DIGITS = "₀₁₂₃₄₅₆₇₈₉"
_SUPERSCRIPT_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"


def _is_subscript_digit(ch: str) -> bool:
    return ch in _SUBSCRIPT_DIGITS


# Blackboard / named sets that appear as single unicode codepoints.
_UNICODE_SETS = {
    "ℝ": "R",
    "ℕ": "N",
    "ℤ": "Z",
    "ℚ": "Q",
    "ℂ": "C",
    "𝔽": "F",
    "ℙ": "P",
}

# LaTeX control words that are *operators/structure* -> always skipped.
_LATEX_OPERATORS = {
    "forall",
    "exists",
    "nexists",
    "in",
    "notin",
    "ni",
    "subset",
    "subseteq",
    "supset",
    "supseteq",
    "Rightarrow",
    "Leftarrow",
    "Leftrightarrow",
    "rightarrow",
    "leftarrow",
    "leftrightarrow",
    "to",
    "mapsto",
    "implies",
    "iff",
    "land",
    "lor",
    "wedge",
    "vee",
    "lnot",
    "neg",
    "le",
    "leq",
    "ge",
    "geq",
    "neq",
    "ne",
    "leqslant",
    "geqslant",
    "cdot",
    "times",
    "cap",
    "cup",
    "setminus",
    "emptyset",
    "mid",
    "colon",
    "quad",
    "qquad",
    ",",
    ";",
    "!",
    ":",
    " ",
}

# LaTeX control words that *are* identifiers (Greek letters & friends).
# Mapped to a representative kind.
_LATEX_GREEK = {
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "varepsilon",
    "zeta",
    "eta",
    "theta",
    "vartheta",
    "iota",
    "kappa",
    "lambda",
    "mu",
    "nu",
    "xi",
    "pi",
    "varpi",
    "rho",
    "varrho",
    "sigma",
    "varsigma",
    "tau",
    "upsilon",
    "phi",
    "varphi",
    "chi",
    "psi",
    "omega",
    "Gamma",
    "Delta",
    "Theta",
    "Lambda",
    "Xi",
    "Pi",
    "Sigma",
    "Upsilon",
    "Phi",
    "Psi",
    "Omega",
}

# unicode Greek block (skip the few used as operators? none here) — any letter
# whose unicode name starts with "GREEK ... LETTER" is an identifier.
def _is_unicode_greek(ch: str) -> bool:
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return False
    return "GREEK" in name and "LETTER" in name


# Operator / structure single chars we never index (unicode + ascii).
_SKIP_CHARS = set(
    "∀∃∄∈∉∋⊂⊆⊄⊃⊇⇒⇐⇔→←↔↦∧∨¬"  # logic / arrows / membership
    "=≠<>≤≥≈≡∼≅"  # relations
    "+−-*/·×∘∙±∓"  # arithmetic
    "()[]{}|‖⟨⟩"  # grouping / bars
    ":,;.…⋯∪∩∖∅"  # punctuation / set ops
    " \t\n\r"
)


def _classify_letter(token: str, followed_by_paren: bool) -> SymbolKind:
    if followed_by_paren:
        return "function"
    return "variable"


def extract_symbol_index(content: str) -> list[SymbolSpan]:
    """Return the identifier spans found in ``content``.

    ``content`` is a formula's canonical string — its ``latex`` when ready,
    else its ``orig_fallback``. Offsets in the returned spans index into
    ``content`` exactly as given (no normalisation of the source string).
    """
    spans: list[SymbolSpan] = []
    n = len(content)
    i = 0
    while i < n:
        ch = content[i]

        # whitespace / known operator chars
        if ch in _SKIP_CHARS:
            i += 1
            continue

        # ----- LaTeX control word: \name -----
        if ch == "\\":
            m = re.match(r"\\([A-Za-z]+)", content[i:])
            if m:
                word = m.group(1)
                start = i
                end = i + m.end()
                # \mathbb{R} and friends -> named set
                if word in ("mathbb", "mathcal", "mathfrak", "mathscr"):
                    brace = re.match(r"\\[A-Za-z]+\{([^}]*)\}", content[i:])
                    if brace:
                        end = i + brace.end()
                        spans.append(
                            SymbolSpan(
                                token=content[start:end],
                                start=start,
                                end=end,
                                kind="set",
                            )
                        )
                        i = end
                        continue
                if word in _LATEX_OPERATORS:
                    i = end
                    continue
                if word in _LATEX_GREEK:
                    token, end = _consume_latex_subscript(content, start, end)
                    spans.append(
                        SymbolSpan(
                            token=token, start=start, end=end, kind="variable"
                        )
                    )
                    i = end
                    continue
                # Unknown control word: treat as a named function/operator we
                # don't index (e.g. \sin, \lim) — skip to stay conservative.
                i = end
                continue
            # a lone backslash
            i += 1
            continue

        # ----- unicode named set (ℝ ...) -----
        if ch in _UNICODE_SETS:
            spans.append(
                SymbolSpan(token=ch, start=i, end=i + 1, kind="set")
            )
            i += 1
            continue

        # ----- Latin letter identifier (with optional subscript) -----
        if ch.isascii() and ch.isalpha():
            start = i
            end = i + 1
            token, end = _consume_unicode_subscript(content, start, end)
            followed = end < n and content[end] == "("
            spans.append(
                SymbolSpan(
                    token=token,
                    start=start,
                    end=end,
                    kind=_classify_letter(token, followed),
                )
            )
            i = end
            continue

        # ----- unicode Greek letter identifier -----
        if _is_unicode_greek(ch):
            start = i
            end = i + 1
            token, end = _consume_unicode_subscript(content, start, end)
            spans.append(
                SymbolSpan(token=token, start=start, end=end, kind="variable")
            )
            i = end
            continue

        # digits / superscripts / anything else not an identifier head: skip.
        i += 1

    return spans


def _consume_unicode_subscript(content: str, start: int, end: int) -> tuple[str, int]:
    """Extend a single-letter token to absorb a trailing subscript.

    Handles both ``x_1`` (ASCII ``_`` + digits/letter) and ``x₁`` (unicode
    subscript digits). Returns ``(token, new_end)`` where ``token`` is the raw
    slice ``content[start:new_end]``.
    """
    n = len(content)
    j = end
    if j < n and content[j] == "_":
        j += 1
        if j < n and content[j] == "{":
            close = content.find("}", j)
            if close != -1:
                j = close + 1
        else:
            # single token subscript: a run of word chars (a_n, x_12)
            while j < n and (content[j].isalnum()):
                j += 1
    else:
        # unicode subscript digits: x₁
        while j < n and _is_subscript_digit(content[j]):
            j += 1
    return content[start:j], j


def _consume_latex_subscript(content: str, start: int, end: int) -> tuple[str, int]:
    """As :func:`_consume_unicode_subscript` but for a LaTeX control-word head
    (``\\alpha_1`` etc.)."""
    return _consume_unicode_subscript(content, start, end)
