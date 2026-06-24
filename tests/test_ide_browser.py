"""Browser test for the IDE interactions (issues #11, #12, #13).

This test drives the *rendered document* in a real browser via Playwright to
exercise:

* #11 render-bbox measurement (``window.mathIDE.renderBboxes()``) and the
  symbol-smaller-than-formula invariant;
* #11 re-layout-on-upgrade: a formula starting pending (fallback) is mutated to
  ready + KaTeX content, and the symbol bbox changes after the debounced
  remeasure; ready formulas are visually typeset (a ``.katex`` element appears)
  and a per-symbol hit target is smaller than the formula box (#10/#11);
* #12 left-click go-to-definition (scroll + highlight) and the disabled
  "resolving…" cue for unresolved occurrences.

It MUST degrade cleanly: if Playwright (or its browser) is unavailable the whole
module is skipped, so the default offline suite stays green without browsers.
The KaTeX-dependent assertions skip if KaTeX (loaded from a CDN) is unreachable.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from socketserver import TCPServer

import pytest

# Skip the entire module unless Playwright (the Python package) is importable.
pytest.importorskip("playwright", reason="playwright not installed")
pytest.importorskip(
    "playwright.sync_api", reason="playwright sync API not installed"
)

from playwright.sync_api import sync_playwright  # noqa: E402

from math_ide.ingest import build_math_document  # noqa: E402
from math_ide.ontology import MockResolver, seed_ontology  # noqa: E402
from math_ide.renderer.render import render_document  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "example_docling.json"
_ASSETS = Path(__file__).resolve().parents[1] / "math_ide" / "renderer" / "assets"


def _resolved_html() -> str:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    doc = build_math_document(raw)
    seed_ontology(doc)
    MockResolver().resolve(doc)
    return render_document(doc)


def _ready_formula_html() -> str:
    """A standalone page with one READY formula carrying a symbol occurrence.

    Built directly from schema models (no fixture) so the page exercises the
    decoupled ready-formula DOM contract: an empty .katex-target host KaTeX
    typesets, plus a sibling .occ-fallback with the per-symbol hit target.
    """
    from math_ide.schema import Formula, MathDocument, Occurrence, SymbolSpan

    latex = r"f(x) = x"
    f_start = latex.index("f")
    f_end = f_start + 1
    formula = Formula(
        id="rdy#block/formula",
        latex=latex,
        orig_fallback="f(x) = x",
        enrichment_status="ready",
        symbol_index=[
            SymbolSpan(token="f", start=f_start, end=f_end, kind="function")
        ],
    )
    occ = Occurrence(
        id="rdy#occ/sym-f",
        kind="formula_symbol",
        block_id=formula.id,
        span=(f_start, f_end),
    )
    doc = MathDocument(
        document_id="rdy", blocks=[formula], occurrences=[occ]
    )
    return render_document(doc)


@contextmanager
def _served_site(tmp_path: Path, html: str | None = None):
    """Materialise index.html + assets/ under tmp_path and serve over HTTP."""
    (tmp_path / "index.html").write_text(
        html if html is not None else _resolved_html(), encoding="utf-8"
    )
    assets = tmp_path / "assets"
    assets.mkdir()
    for name in ("app.js", "styles.css"):
        (assets / name).write_text(
            (_ASSETS / name).read_text(encoding="utf-8"), encoding="utf-8"
        )

    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = TCPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/index.html"
    finally:
        server.shutdown()
        server.server_close()


@contextmanager
def _browser_page(url: str):
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - no browser binary installed
            pytest.skip(f"no Playwright browser available: {exc}")
        try:
            page = browser.new_page()
            page.goto(url, wait_until="load")
            page.wait_for_function("window.mathIDE !== undefined")
            yield page
        finally:
            browser.close()


def test_render_bboxes_and_symbol_smaller_than_formula(tmp_path):
    with _served_site(tmp_path) as url, _browser_page(url) as page:
        bboxes = page.evaluate("window.mathIDE.renderBboxes()")
        assert bboxes, "expected at least one measured occurrence bbox"
        # Every measured occurrence has a positive-area render bbox.
        for occ_id, box in bboxes.items():
            assert box["width"] > 0 and box["height"] > 0, occ_id

        # A formula symbol's hit target is smaller than its formula block box.
        smaller = page.evaluate(
            """() => {
              const occ = document.querySelector('.occ[data-kind="formula_symbol"]');
              if (!occ) return null;
              const formula = occ.closest('.formula');
              const o = occ.getBoundingClientRect();
              const f = formula.getBoundingClientRect();
              return (o.width * o.height) < (f.width * f.height);
            }"""
        )
        assert smaller is True


def test_left_click_citation_scrolls_and_highlights(tmp_path):
    with _served_site(tmp_path) as url, _browser_page(url) as page:
        # Click the citation occurrence; its target block gets the highlight.
        page.click('.occ[data-kind="citation"]')
        page.wait_for_selector(".definition-highlight", timeout=2000)
        highlighted = page.evaluate(
            "document.querySelector('.definition-highlight').id"
        )
        assert highlighted.endswith("menge")


def test_unresolved_occurrence_shows_resolving_cue(tmp_path):
    with _served_site(tmp_path) as url, _browser_page(url) as page:
        # An unresolved symbol carries data-resolvable="false" and clicking it
        # does NOT navigate (no highlight ring appears).
        has_unresolvable = page.evaluate(
            "!!document.querySelector('.occ[data-resolvable=\"false\"]')"
        )
        assert has_unresolvable
        page.click('.occ[data-resolvable="false"]')
        # Give any (erroneous) navigation a moment; assert none happened.
        page.wait_for_timeout(300)
        count = page.evaluate(
            "document.querySelectorAll('.definition-highlight').length"
        )
        assert count == 0


def test_right_click_opens_concept_card(tmp_path):
    with _served_site(tmp_path) as url, _browser_page(url) as page:
        # Right-click the Konvergenz defined-name occurrence -> card opens with
        # formal meaning and a references section.
        page.click(
            '.occ[data-kind="defined_name"][data-concept-id*="konvergenz"]',
            button="right",
        )
        page.wait_for_selector("#concept-panel:not([hidden])", timeout=2000)
        title = page.text_content(".card-title")
        assert title == "Konvergenz"
        assert page.query_selector(".card-formal") is not None
        assert page.query_selector(".card-references") is not None


def _katex_loaded(page) -> bool:
    """Whether KaTeX (loaded from a CDN) is available in the page."""
    return bool(page.evaluate("typeof katex !== 'undefined'"))


def test_ready_formula_is_typeset_and_symbol_smaller_than_box(tmp_path):
    """#10/#11: a ready formula is visually typeset (a .katex element appears)
    and a per-symbol hit target survives + is smaller than the formula box."""
    with _served_site(tmp_path, html=_ready_formula_html()) as url, _browser_page(
        url
    ) as page:
        if not _katex_loaded(page):
            pytest.skip("KaTeX CDN unreachable in this environment")
        # KaTeX typeset the data-latex host into a .katex element.
        page.wait_for_selector(".katex-target .katex", timeout=3000)
        assert page.query_selector(".katex-target .katex") is not None

        # A per-symbol .occ hit target exists and is smaller than the formula.
        smaller = page.evaluate(
            """() => {
              const occ = document.querySelector('.occ[data-kind="formula_symbol"]:not([hidden])');
              if (!occ) return null;
              const formula = occ.closest('.formula');
              const o = occ.getBoundingClientRect();
              const f = formula.getBoundingClientRect();
              if (o.width <= 0 || o.height <= 0) return null;
              return (o.width * o.height) < (f.width * f.height);
            }"""
        )
        assert smaller is True


def test_formula_relayout_on_upgrade(tmp_path):
    """#11: a formula starting pending (fallback) is upgraded to ready + KaTeX
    content; the symbol bbox changes after the debounced remeasure."""
    with _served_site(tmp_path) as url, _browser_page(url) as page:
        if not _katex_loaded(page):
            pytest.skip("KaTeX CDN unreachable in this environment")

        # Pick a pending formula that carries at least one symbol occurrence.
        prep = page.evaluate(
            """() => {
              const formulas = document.querySelectorAll(
                '.formula[data-enrichment="pending"]'
              );
              for (const f of formulas) {
                const occ = f.querySelector('.occ[data-kind="formula_symbol"]');
                if (occ) return {
                  blockId: f.getAttribute('data-block-id'),
                  occId: occ.getAttribute('data-occurrence-id'),
                };
              }
              return null;
            }"""
        )
        assert prep is not None, "fixture must have a pending formula with a symbol"
        occ_id = prep["occId"]

        # Baseline bbox of the symbol while the formula is still a fallback.
        before = page.evaluate(
            "(id) => window.mathIDE.renderBboxes()[id]", occ_id
        )
        assert before and before["width"] > 0 and before["height"] > 0

        # Upgrade the formula IN PLACE to ready + a KaTeX-typesettable host that
        # carries the SAME occurrence id (the decoupled ready DOM contract), so
        # the MutationObserver typesets it and re-measures.
        page.evaluate(
            """(args) => {
              const f = document.querySelector(
                '[data-block-id="' + args.blockId + '"]'
              );
              const attrs = 'data-occurrence-id=\\"' + args.occId +
                '\\" data-kind=\\"formula_symbol\\" class=\\"occ\\" tabindex=\\"0\\"';
              const tokens = JSON.stringify([{ token: 'a', attrs: attrs }]);
              f.setAttribute('data-enrichment', 'ready');
              f.innerHTML =
                '<span class="katex-target" data-latex="\\\\sum_{n=1}^{\\\\infty} a_n" ' +
                "data-occurrences='" + tokens + "'></span>" +
                '<span class="occ-fallback"><span ' + attrs + '>a</span></span>';
            }""",
            prep,
        )

        # Wait for KaTeX to typeset the upgraded formula and the debounced
        # remeasure to run.
        page.wait_for_selector(
            '[data-block-id="' + prep["blockId"] + '"] .katex', timeout=3000
        )
        page.wait_for_timeout(300)
        page.evaluate("window.mathIDE.remeasure()")

        after = page.evaluate(
            "(id) => window.mathIDE.renderBboxes()[id]", occ_id
        )
        assert after and after["width"] > 0 and after["height"] > 0
        # The box changed: the symbol re-laid-out from monospace fallback text to
        # a typeset KaTeX glyph (position and/or size differ).
        changed = (
            abs(after["width"] - before["width"]) > 0.5
            or abs(after["height"] - before["height"]) > 0.5
            or abs(after["x"] - before["x"]) > 0.5
            or abs(after["y"] - before["y"]) > 0.5
        )
        assert changed, (before, after)

        # The measured box was also written back into the live payload (#11).
        payload_box = page.evaluate(
            "(id) => window.mathIDE.data.occurrences[id].render_bbox", occ_id
        )
        assert payload_box is not None
        assert payload_box["width"] == after["width"]
