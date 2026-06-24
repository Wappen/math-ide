"""Tests for symbol-index extraction (issue #6).

Covers both Docling unicode ``orig`` and LaTeX input, offset correctness, and
the operator-skip rule.
"""

from __future__ import annotations

from math_ide.ingest.symbols import extract_symbol_index

INJ_ORIG = "∀ x₁, x₂ ∈ X : f(x₁) = f(x₂) ⇒ x₁ = x₂"
INJ_LATEX = r"\forall x_1,x_2 \in X : f(x_1)=f(x_2) \Rightarrow x_1=x_2"
CONV_ORIG = "∀ ε > 0 ∃ N ∈ ℝ ∀ n ≥ N : |a_n − L| < ε"
CONV_LATEX = (
    r"\forall \varepsilon>0 \, \exists N \in \mathbb{R} "
    r"\, \forall n \ge N : |a_n - L| < \varepsilon"
)


def _tokens(content: str) -> list[str]:
    return [s.token for s in extract_symbol_index(content)]


def _assert_offsets_consistent(content: str) -> None:
    for s in extract_symbol_index(content):
        assert content[s.start : s.end] == s.token


# ---------------------------------------------------------------------------
# Injectivity (acceptance: f, x_1/x₁, x_2/x₂, X)
# ---------------------------------------------------------------------------


def test_injectivity_unicode_orig():
    tokens = _tokens(INJ_ORIG)
    assert "f" in tokens
    assert "x₁" in tokens
    assert "x₂" in tokens
    assert "X" in tokens
    _assert_offsets_consistent(INJ_ORIG)


def test_injectivity_latex():
    tokens = _tokens(INJ_LATEX)
    assert "f" in tokens
    assert "x_1" in tokens
    assert "x_2" in tokens
    assert "X" in tokens
    _assert_offsets_consistent(INJ_LATEX)


def test_injectivity_f_is_function_x_is_variable():
    spans = {s.token: s for s in extract_symbol_index(INJ_ORIG)}
    assert spans["f"].kind == "function"  # followed by "("
    assert spans["X"].kind == "variable"


# ---------------------------------------------------------------------------
# Convergence (acceptance: ε, a_n, L, N, R/ℝ)
# ---------------------------------------------------------------------------


def test_convergence_unicode_orig():
    tokens = _tokens(CONV_ORIG)
    assert "ε" in tokens
    assert "a_n" in tokens
    assert "L" in tokens
    assert "N" in tokens
    assert "ℝ" in tokens
    _assert_offsets_consistent(CONV_ORIG)


def test_convergence_latex():
    tokens = _tokens(CONV_LATEX)
    assert "\\varepsilon" in tokens
    assert "a_n" in tokens
    assert "L" in tokens
    assert "N" in tokens
    assert "\\mathbb{R}" in tokens
    _assert_offsets_consistent(CONV_LATEX)


def test_blackboard_set_kind():
    spans = {s.token: s for s in extract_symbol_index(CONV_ORIG)}
    assert spans["ℝ"].kind == "set"
    latex_spans = {s.token: s for s in extract_symbol_index(CONV_LATEX)}
    assert latex_spans["\\mathbb{R}"].kind == "set"


# ---------------------------------------------------------------------------
# Operator-skip rule
# ---------------------------------------------------------------------------


def test_operators_and_quantifiers_skipped_unicode():
    tokens = _tokens(CONV_ORIG)
    for op in ["∀", "∃", "∈", "≥", ">", "<", "−", "|", ":", "0"]:
        assert op not in tokens


def test_operators_and_quantifiers_skipped_latex():
    tokens = _tokens(INJ_LATEX)
    for op in ["\\forall", "\\in", "\\Rightarrow", "=", ":", ","]:
        assert op not in tokens
    # control words for operators don't leak in any spelling
    conv_tokens = _tokens(CONV_LATEX)
    for op in ["\\exists", "\\ge", "\\forall"]:
        assert op not in conv_tokens


def test_no_spurious_digit_tokens():
    # "∀ ε > 0 ..." -- the constant 0 is not an identifier we index.
    tokens = _tokens(CONV_ORIG)
    assert "0" not in tokens


# ---------------------------------------------------------------------------
# Subscript handling parity
# ---------------------------------------------------------------------------


def test_a_n_subscript_kept_as_single_token():
    spans = extract_symbol_index("|a_n − L|")
    tokens = [s.token for s in spans]
    assert "a_n" in tokens
    assert "L" in tokens
    # not split into "a" and "n"
    assert "a" not in tokens


def test_unicode_subscript_kept():
    spans = extract_symbol_index("x₁ = x₂")
    assert [s.token for s in spans] == ["x₁", "x₂"]


# ---------------------------------------------------------------------------
# Real Docling 2.107.0 spaced output (issue #20)
#
# Live formula enrichment spaces every token in the enriched ``latex``
# (``x _ { 1 }``, ``a _ { n }``, ``\mathbb { N }``, ``f (``) and linearizes the
# fallback ``orig`` by dropping ``_`` and keeping only spacing (``a n``), with
# the lunate epsilon ``ϵ`` U+03F5 instead of ``ε`` U+03B5. These are the exact
# strings from the E2E log; the synthetic fixture uses tight tokens that mask
# all of this, so we exercise the spaced forms directly here.
# ---------------------------------------------------------------------------

INJ_LATEX_SPACED = (
    r"\forall x _ { 1 } , x _ { 2 } \in X \colon "
    r"( f ( x _ { 1 } ) = f ( x _ { 2 } ) \implies x _ { 1 } = x _ { 2 } )"
)
CONV_LATEX_SPACED = (
    r"\forall \epsilon > 0 \quad \exists N \in \mathbb { N } "
    r"\ \forall n \geq N \colon | a _ { n } - L | < \epsilon"
)
CONV_ORIG_SPACED = "∀ ϵ > 0 ∃ N ∈ N ∀ n ≥ N : | a n -L | < ϵ"


def test_injectivity_latex_spaced_subscripts_are_distinct_whole_tokens():
    spans = extract_symbol_index(INJ_LATEX_SPACED)
    tokens = [s.token for s in spans]
    # x _ { 1 } and x _ { 2 } stay whole and are DISTINCT tokens, not a bare x.
    assert "x _ { 1 }" in tokens
    assert "x _ { 2 }" in tokens
    assert "x" not in tokens
    # X is a plain variable, f is a function despite the space before "(".
    by_token = {s.token: s for s in spans}
    assert by_token["X"].kind == "variable"
    assert by_token["f"].kind == "function"
    _assert_offsets_consistent(INJ_LATEX_SPACED)


def test_injectivity_latex_spaced_x1_x2_have_separate_offsets():
    spans = extract_symbol_index(INJ_LATEX_SPACED)
    x1_starts = sorted(s.start for s in spans if s.token == "x _ { 1 }")
    x2_starts = sorted(s.start for s in spans if s.token == "x _ { 2 }")
    # Both subscripts occur multiple times and never share a span -> distinct
    # formula-symbol occurrences (concept identity is preserved, not collapsed).
    assert len(x1_starts) >= 2
    assert len(x2_starts) >= 2
    assert set(x1_starts).isdisjoint(x2_starts)


def test_convergence_latex_spaced_an_set_and_epsilon():
    spans = extract_symbol_index(CONV_LATEX_SPACED)
    by_token = {s.token: s for s in spans}
    tokens = [s.token for s in spans]
    # a _ { n } is a single variable token, not separate a + n occurrences.
    assert "a _ { n }" in tokens
    assert by_token["a _ { n }"].kind == "variable"
    assert "a" not in tokens
    # \mathbb { N } is one token, kind=set (not a bare N variable).
    assert "\\mathbb { N }" in tokens
    assert by_token["\\mathbb { N }"].kind == "set"
    # \epsilon is emitted on the LaTeX path.
    assert "\\epsilon" in tokens
    _assert_offsets_consistent(CONV_LATEX_SPACED)


def test_convergence_orig_spaced_emits_lunate_epsilon_and_an():
    spans = extract_symbol_index(CONV_ORIG_SPACED)
    tokens = [s.token for s in spans]
    # The lunate epsilon ϵ (U+03F5, "GREEK ... SYMBOL") is no longer dropped.
    assert "ϵ" in tokens
    assert sum(1 for t in tokens if t == "ϵ") == 2
    # The despaced subscript "a n" stays one token, not separate a + n.
    assert "a n" in tokens
    assert "a" not in tokens
    assert "L" in tokens
    assert "N" in tokens
    _assert_offsets_consistent(CONV_ORIG_SPACED)


def test_spaced_function_paren_classified_function():
    # "f (" with a space before the paren is still a function (issue #20).
    spans = {s.token: s for s in extract_symbol_index("f ( x )")}
    assert spans["f"].kind == "function"
