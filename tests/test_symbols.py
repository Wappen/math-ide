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
