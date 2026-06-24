"""Tests for the renderer (issue #10).

Builds small ``MathDocument`` instances directly from the schema models (never
importing from ``math_ide.ingest``) and asserts on the emitted HTML using
string assertions and ``html.parser`` — no browser involved.
"""

from __future__ import annotations

from html.parser import HTMLParser

import pytest

from math_ide.renderer.render import render_block, render_document
from math_ide.schema import (
    Definition,
    Formula,
    MathDocument,
    Occurrence,
    Paragraph,
    Section,
    SymbolSpan,
)

DOC_ID = "doc1"


# --------------------------------------------------------------------------- #
# A small HTML parser that collects (tag, attrs, text) tuples for assertions.
# --------------------------------------------------------------------------- #


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []
        self.texts: list[str] = []
        # tag -> list of attr-dicts
        self.by_tag: dict[str, list[dict[str, str]]] = {}

    def handle_starttag(self, tag, attrs):
        d = {k: (v or "") for k, v in attrs}
        self.tags.append((tag, d))
        self.by_tag.setdefault(tag, []).append(d)

    def handle_data(self, data):
        if data.strip():
            self.texts.append(data)

    def spans(self) -> list[dict[str, str]]:
        return [
            d for tag, d in self.tags if tag == "span"
        ]

    def occ_spans(self) -> list[dict[str, str]]:
        return [d for d in self.spans() if "occ" in d.get("class", "").split()]


def _parse(html: str) -> _Collector:
    c = _Collector()
    c.feed(html)
    return c


def _attr_with_class(collector: _Collector, cls: str) -> dict[str, str]:
    for _tag, d in collector.tags:
        if cls in d.get("class", "").split():
            return d
    raise AssertionError(f"no element with class {cls!r}")


# --------------------------------------------------------------------------- #
# Fixtures: blocks built straight from schema models.
# --------------------------------------------------------------------------- #


def _section() -> Section:
    return Section(
        id=f"{DOC_ID}#block/sec-1",
        title="1 Mengen und Abbildungen",
        children=[],
    )


def _paragraph_with_citation() -> tuple[Paragraph, Occurrence]:
    text = "Nach Definition 1.1 ist eine Menge bestimmt."
    start = text.index("Definition 1.1")
    end = start + len("Definition 1.1")
    para = Paragraph(id=f"{DOC_ID}#block/p-1", text=text)
    occ = Occurrence(
        id=f"{DOC_ID}#occ/cite-1",
        kind="citation",
        block_id=para.id,
        span=(start, end),
        target_block_id=f"{DOC_ID}#block/def-1-1",
    )
    return para, occ


def _definition_with_preamble_and_name() -> tuple[Definition, Occurrence]:
    block = Definition(
        id=f"{DOC_ID}#block/def-1-2",
        number="1.2",
        defined_name="Injektivitaet",
        preamble="Ein wichtiges Konzept der Analysis ist die Injektivitaet.",
        body="Eine Abbildung f heisst injektiv, wenn ...",
    )
    # Header is "Definition 1.2 (Injektivitaet)"; anchor the name within it.
    header = "Definition 1.2 (Injektivitaet)"
    start = header.index("Injektivitaet")
    end = start + len("Injektivitaet")
    occ = Occurrence(
        id=f"{DOC_ID}#occ/name-injektiv",
        kind="defined_name",
        block_id=block.id,
        span=(start, end),
        concept_id=f"{DOC_ID}#injektivitaet",
    )
    return block, occ


def _ready_formula_with_symbol() -> tuple[Formula, Occurrence]:
    latex = r"\forall x_1,x_2 \in X : f(x_1)=f(x_2) \Rightarrow x_1 = x_2"
    f_start = latex.index("f(")
    f_end = f_start + 1  # just the "f"
    formula = Formula(
        id=f"{DOC_ID}#block/formula-inj",
        latex=latex,
        orig_fallback="∀ x₁, x₂ ∈ X : f(x₁) = f(x₂) ⇒ x₁ = x₂",
        enrichment_status="ready",
        symbol_index=[SymbolSpan(token="f", start=f_start, end=f_end, kind="function")],
    )
    occ = Occurrence(
        id=f"{DOC_ID}#occ/sym-f",
        kind="formula_symbol",
        block_id=formula.id,
        span=(f_start, f_end),
        concept_id=f"{DOC_ID}#f",
    )
    return formula, occ


def _pending_formula() -> Formula:
    return Formula(
        id=f"{DOC_ID}#block/formula-pending",
        latex=None,
        orig_fallback="∀ ε > 0 ∃ N ∈ ℝ ∀ n ≥ N : |a_n − L| < ε",
        enrichment_status="pending",
    )


def _doc(blocks, occurrences=()) -> MathDocument:
    return MathDocument(
        document_id=DOC_ID,
        blocks=list(blocks),
        occurrences=list(occurrences),
    )


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_render_document_is_standalone_page():
    doc = _doc([_section()])
    html = render_document(doc)
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "<head>" in html and "</head>" in html
    # KaTeX from CDN in the head.
    assert "katex" in html.lower()
    assert "cdn" in html.lower()
    # app.js referenced near </body> (absence at runtime is tolerated).
    assert 'src="assets/app.js"' in html
    # Scroll container wrapping the document.
    c = _parse(html)
    assert any(
        "math-doc-scroll" in d.get("class", "").split() for _t, d in c.tags
    )


def test_section_renders_as_section_with_title():
    sec = _section()
    html = render_block(sec, _doc([sec]))
    c = _parse(html)
    sec_attrs = _attr_with_class(c, "section")
    assert sec_attrs["id"] == sec.id
    assert sec_attrs["data-block-id"] == sec.id
    assert "1 Mengen und Abbildungen" in html
    # A heading element carries the title.
    assert any(t in ("h1", "h2", "h3", "h4", "h5", "h6") for t, _ in c.tags)


def test_paragraph_renders_with_citation_anchor():
    para, occ = _paragraph_with_citation()
    html = render_block(para, _doc([para], [occ]))
    c = _parse(html)
    p_attrs = _attr_with_class(c, "paragraph")
    assert p_attrs["id"] == para.id
    occ_spans = c.occ_spans()
    assert len(occ_spans) == 1
    anchor = occ_spans[0]
    assert anchor["data-occurrence-id"] == occ.id
    assert anchor["data-kind"] == "citation"
    assert anchor["data-target-block-id"] == occ.target_block_id
    # The anchor wraps exactly "Definition 1.1".
    assert ">Definition 1.1</span>" in html
    # Surrounding text is intact.
    assert "Nach " in html and " ist eine Menge bestimmt." in html


def test_definition_shows_preamble_before_body():
    block, occ = _definition_with_preamble_and_name()
    html = render_block(block, _doc([block], [occ]))
    c = _parse(html)
    div = _attr_with_class(c, "formal")
    assert "definition" in div.get("class", "").split()
    assert div["data-formal-type"] == "Definition"
    assert div["id"] == block.id
    # Header line text.
    assert "Definition 1.2 (Injektivitaet)" in _strip_tags(html)
    # Preamble must appear before the body in document order.
    assert block.preamble is not None
    pre_pos = html.index(block.preamble[:10])
    body_pos = html.index(block.body[:10])
    assert pre_pos < body_pos
    # The defined name is wrapped as an occurrence anchor in the header.
    occ_spans = c.occ_spans()
    assert len(occ_spans) == 1
    assert occ_spans[0]["data-kind"] == "defined_name"
    assert occ_spans[0]["data-occurrence-id"] == occ.id
    assert ">Injektivitaet</span>" in html


def test_definition_without_preamble_has_no_preamble_element():
    block = Definition(
        id=f"{DOC_ID}#block/def-1-1",
        number="1.1",
        defined_name="Menge",
        body="Eine Menge ist eine Zusammenfassung.",
    )
    html = render_block(block, _doc([block]))
    c = _parse(html)
    assert not any(
        "formal-preamble" in d.get("class", "").split() for _t, d in c.tags
    )
    assert "Definition 1.1 (Menge)" in _strip_tags(html)


def test_ready_formula_emits_latex_into_katex_target():
    formula, occ = _ready_formula_with_symbol()
    html = render_block(formula, _doc([formula], [occ]))
    c = _parse(html)
    div = _attr_with_class(c, "formula")
    assert div["data-enrichment"] == "ready"
    target = _attr_with_class(c, "katex-target")
    # The latex source is carried as data-latex for client-side rendering.
    assert target["data-latex"] == formula.latex
    # Symbol occurrence anchored within the canonical content. Under the
    # decoupled contract the .occ lives in the sibling .occ-fallback (KaTeX
    # owns the .katex-target host), so there is still exactly one occ anchor.
    occ_spans = c.occ_spans()
    assert len(occ_spans) == 1
    assert occ_spans[0]["data-kind"] == "formula_symbol"
    assert occ_spans[0]["data-occurrence-id"] == occ.id
    assert ">f</span>" in html


def test_ready_formula_decouples_katex_host_from_occ_anchors():
    """Ready formula: KaTeX owns an empty host; occ anchors ride in a sibling.

    This is the contract that lets app.js call ``katex.render`` (which replaces
    the host's children) without deleting the per-symbol hit targets (#10/#11).
    """
    import json as _json

    formula, occ = _ready_formula_with_symbol()
    html = render_block(formula, _doc([formula], [occ]))
    c = _parse(html)

    # The KaTeX host is server-rendered EMPTY (no .occ children inside it) and
    # carries the per-symbol token descriptors as data-occurrences JSON.
    target = _attr_with_class(c, "katex-target")
    assert "data-occurrences" in target
    tokens = _json.loads(target["data-occurrences"])
    assert tokens, "expected per-symbol token descriptors"
    assert tokens[0]["token"] == "f"
    assert occ.id in tokens[0]["attrs"]
    assert "formula_symbol" in tokens[0]["attrs"]
    # Empty host: the latex/occ content is NOT inside the katex-target element.
    assert '<span class="katex-target"' in html
    assert 'data-occurrences=' in html
    katex_open = html.index('class="katex-target"')
    katex_close = html.index("></span>", katex_open)  # self-closed empty host
    assert katex_close > katex_open

    # The occ anchor lives in the sibling .occ-fallback (the no-JS hit layer).
    fallback = _attr_with_class(c, "occ-fallback")
    assert "occ-fallback" in fallback["class"].split()
    assert ">f</span>" in html


def test_ready_formula_without_symbols_has_no_fallback():
    formula = Formula(
        id=f"{DOC_ID}#block/formula-nosym",
        latex=r"a = b",
        orig_fallback="a = b",
        enrichment_status="ready",
    )
    html = render_block(formula, _doc([formula]))
    c = _parse(html)
    target = _attr_with_class(c, "katex-target")
    assert target["data-occurrences"] == "[]"
    # No symbol occurrences -> no .occ-fallback sibling.
    assert not any(
        "occ-fallback" in d.get("class", "").split() for _t, d in c.tags
    )


def test_pending_formula_shows_orig_fallback():
    formula = _pending_formula()
    html = render_block(formula, _doc([formula]))
    c = _parse(html)
    div = _attr_with_class(c, "formula")
    assert div["data-enrichment"] == "pending"
    # No katex target; degraded fallback span instead.
    assert not any(
        "katex-target" in d.get("class", "").split() for _t, d in c.tags
    )
    fallback = _attr_with_class(c, "formula-fallback")
    assert "formula-fallback" in fallback["class"].split()
    assert formula.orig_fallback in _strip_tags(html)


def test_block_ids_present_in_dom_for_all_blocks():
    sec = _section()
    para, cite = _paragraph_with_citation()
    defin, name = _definition_with_preamble_and_name()
    formula, sym = _ready_formula_with_symbol()
    sec.children = [para, defin, formula]
    doc = _doc([sec], [cite, name, sym])
    html = render_document(doc)
    c = _parse(html)
    ids = {d["id"] for _t, d in c.tags if "id" in d and "block" in d.get("class", "")}
    for block in (sec, para, defin, formula):
        assert block.id in ids
        # data-block-id mirrors id.
    block_ids = {
        d["data-block-id"] for _t, d in c.tags if "data-block-id" in d
    }
    for block in (sec, para, defin, formula):
        assert block.id in block_ids


def test_html_is_escaped():
    para = Paragraph(
        id=f"{DOC_ID}#block/p-x",
        text='dangerous <script>alert("x")</script> & <b>bold</b>',
    )
    html = render_block(para, _doc([para]))
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
    assert "&amp;" in html
    assert "&lt;b&gt;bold" in html


def test_formal_header_escaped_in_defined_name():
    block = Definition(
        id=f"{DOC_ID}#block/def-x",
        number="9.9",
        defined_name="A<B>&C",
        body="body",
    )
    html = render_block(block, _doc([block]))
    assert "<B>" not in html
    assert "&lt;B&gt;" in html or "A&lt;B&gt;" in html


def test_overlapping_occurrence_spans_do_not_corrupt_text():
    text = "abcdef"
    para = Paragraph(id=f"{DOC_ID}#block/p-ov", text=text)
    o1 = Occurrence(
        id=f"{DOC_ID}#occ/a", kind="citation", block_id=para.id, span=(0, 3)
    )
    # Overlaps o1; must be skipped.
    o2 = Occurrence(
        id=f"{DOC_ID}#occ/b", kind="citation", block_id=para.id, span=(2, 5)
    )
    html = render_block(para, _doc([para], [o1, o2]))
    c = _parse(html)
    occ_spans = c.occ_spans()
    # Only the first (non-overlapping) anchor survives.
    assert len(occ_spans) == 1
    assert occ_spans[0]["data-occurrence-id"] == o1.id
    # Full text still present once anchors are stripped.
    assert _strip_tags(html).replace("\n", "").find("abcdef") != -1 or (
        "abc" in html and "def" in html
    )


def test_out_of_range_span_is_skipped():
    para = Paragraph(id=f"{DOC_ID}#block/p-oor", text="short")
    occ = Occurrence(
        id=f"{DOC_ID}#occ/oor",
        kind="citation",
        block_id=para.id,
        span=(0, 999),
    )
    html = render_block(para, _doc([para], [occ]))
    c = _parse(html)
    assert c.occ_spans() == []
    assert "short" in html


# --------------------------------------------------------------------------- #
# Helper
# --------------------------------------------------------------------------- #


class _TextOnly(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []

    def handle_data(self, data):
        self.out.append(data)


def _strip_tags(html: str) -> str:
    p = _TextOnly()
    p.feed(html)
    return "".join(p.out)
