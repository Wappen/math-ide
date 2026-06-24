"""Tests for Formula block construction + enrichment lifecycle (issue #5)."""

from __future__ import annotations

import json
from pathlib import Path

from math_ide.ingest import build_math_document
from math_ide.ingest.formula import (
    build_formula,
    mark_failed,
    upgrade_formula,
)
from math_ide.schema import BBox, Formula

FIXTURE = Path(__file__).parent / "fixtures" / "example_docling.json"

INJ_ORIG = "∀ x₁, x₂ ∈ X : f(x₁) = f(x₂) ⇒ x₁ = x₂"
INJ_LATEX = r"\forall x_1,x_2 \in X : f(x_1)=f(x_2) \Rightarrow x_1=x_2"


def _bbox():
    return BBox(l=150.0, t=558.0, r=445.0, b=540.0, page_no=1)


# ---------------------------------------------------------------------------
# build_formula
# ---------------------------------------------------------------------------


def test_pending_formula_keeps_orig_fallback_immediately():
    f = build_formula("doc#block/f", orig=INJ_ORIG, text="", source_bbox=_bbox())
    assert f.orig_fallback == INJ_ORIG
    assert f.enrichment_status == "pending"
    assert f.latex is None
    # canonical content falls back to orig; symbol index built against it
    assert f.canonical_content == INJ_ORIG
    assert any(s.token == "f" for s in f.symbol_index)


def test_formula_with_text_is_born_ready():
    f = build_formula("doc#block/f", orig=INJ_ORIG, text=INJ_LATEX)
    assert f.enrichment_status == "ready"
    assert f.latex == INJ_LATEX
    assert f.canonical_content == INJ_LATEX
    # offsets index the LaTeX string
    for s in f.symbol_index:
        assert f.latex[s.start : s.end] == s.token


# ---------------------------------------------------------------------------
# upgrade_formula
# ---------------------------------------------------------------------------


def test_upgrade_sets_latex_ready_and_rebuilds_index():
    f = build_formula("doc#block/f", orig=INJ_ORIG, text="", source_bbox=_bbox())
    before_tokens = [s.token for s in f.symbol_index]
    assert "x₁" in before_tokens  # unicode tokens while pending

    same = upgrade_formula(f, INJ_LATEX)
    assert same is f  # in-place
    assert f.enrichment_status == "ready"
    assert f.latex == INJ_LATEX
    assert f.canonical_content == INJ_LATEX

    # index rebuilt against LaTeX -> tokens now use LaTeX spelling, offsets too
    after_tokens = [s.token for s in f.symbol_index]
    assert "x_1" in after_tokens
    for s in f.symbol_index:
        assert f.latex[s.start : s.end] == s.token


def test_upgrade_preserves_orig_fallback_and_bbox():
    f = build_formula("doc#block/f", orig=INJ_ORIG, text="", source_bbox=_bbox())
    upgrade_formula(f, INJ_LATEX)
    assert f.orig_fallback == INJ_ORIG
    assert f.source_bbox == _bbox()


# ---------------------------------------------------------------------------
# mark_failed
# ---------------------------------------------------------------------------


def test_mark_failed_keeps_fallback_and_bbox():
    f = build_formula("doc#block/f", orig=INJ_ORIG, text="", source_bbox=_bbox())
    same = mark_failed(f)
    assert same is f
    assert f.enrichment_status == "failed"
    assert f.latex is None
    assert f.orig_fallback == INJ_ORIG
    assert f.source_bbox == _bbox()
    # canonical content falls back to orig; index still available
    assert f.canonical_content == INJ_ORIG
    assert any(s.token == "f" for s in f.symbol_index)


def test_failed_after_partial_latex_clears_latex():
    f = build_formula("doc#block/f", orig=INJ_ORIG, text=INJ_LATEX)
    assert f.enrichment_status == "ready"
    mark_failed(f)
    assert f.enrichment_status == "failed"
    assert f.latex is None
    assert f.canonical_content == INJ_ORIG


# ---------------------------------------------------------------------------
# Fixture acceptance
# ---------------------------------------------------------------------------


def test_fixture_formulas_are_pending_with_fallback():
    docling = json.loads(FIXTURE.read_text(encoding="utf-8"))
    doc = build_math_document(docling)
    formulas = []

    def collect(blocks):
        for b in blocks:
            if isinstance(b, Formula):
                formulas.append(b)
            if hasattr(b, "children"):
                collect(b.children)

    collect(doc.blocks)
    assert len(formulas) == 2
    for f in formulas:
        assert f.enrichment_status == "pending"
        assert f.orig_fallback
        assert f.latex is None
        assert f.symbol_index  # built against fallback immediately
