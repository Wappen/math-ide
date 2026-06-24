"""Tests for the Docling -> math-document adapter (issue #3).

Covers bbox/provenance mapping, section detection and reading-order nesting, the
char-span subdivision helper, and the end-to-end ``build_math_document``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from math_ide.ingest import build_math_document
from math_ide.ingest.docling_adapter import (
    bbox_from_prov,
    blocks_from_docling,
    source_provenance,
    subdivide_bbox,
)
from math_ide.schema import BBox, Definition, Formula, Paragraph, Section

FIXTURE = Path(__file__).parent / "fixtures" / "example_docling.json"


@pytest.fixture()
def docling() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture()
def doc(docling):
    return build_math_document(docling)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_source_provenance_marks_docling_json(docling):
    prov = source_provenance(docling)
    assert prov.origin == "docling_json"
    assert prov.filename == "analysis_skript.pdf"
    assert prov.mimetype == "application/pdf"
    assert prov.binary_hash.startswith("0123456789")


def test_source_provenance_coerces_integer_binary_hash():
    prov = source_provenance(
        {"origin": {"binary_hash": 11714210736799704244, "mimetype": "application/pdf"}}
    )
    assert prov.binary_hash == "11714210736799704244"


def test_default_document_id_from_name(docling):
    doc = build_math_document(docling)
    assert doc.document_id == "analysis-skript"


def test_document_id_override(docling):
    doc = build_math_document(docling, document_id="custom-id")
    assert doc.document_id == "custom-id"
    # ids are namespaced under the document id
    assert all(b.id.startswith("custom-id#") for b in doc.blocks)


# ---------------------------------------------------------------------------
# Bbox mapping
# ---------------------------------------------------------------------------


def test_bbox_from_prov_carries_page_and_coords():
    prov = {
        "page_no": 3,
        "bbox": {"l": 1.0, "t": 9.0, "r": 5.0, "b": 2.0, "coord_origin": "BOTTOMLEFT"},
    }
    bbox = bbox_from_prov(prov)
    assert (bbox.l, bbox.t, bbox.r, bbox.b) == (1.0, 9.0, 5.0, 2.0)
    assert bbox.coord_origin == "BOTTOMLEFT"
    assert bbox.page_no == 3


def test_bbox_from_prov_missing_bbox_returns_none():
    assert bbox_from_prov({"page_no": 1}) is None


def test_section_bbox_matches_fixture_prov(doc, docling):
    sec1 = doc.blocks[0]
    assert isinstance(sec1, Section)
    expected = docling["texts"][0]["prov"][0]["bbox"]
    assert sec1.source_bbox.l == expected["l"]
    assert sec1.source_bbox.t == expected["t"]
    assert sec1.source_bbox.r == expected["r"]
    assert sec1.source_bbox.b == expected["b"]
    assert sec1.page_no == 1


def test_clean_definition_bbox_is_full_node_bbox(doc, docling):
    # Definition 1.1 starts at offset 0 of its node, so its estimated bbox is
    # the whole node bbox.
    menge = doc.blocks[0].children[0]
    expected = docling["texts"][1]["prov"][0]["bbox"]
    assert menge.source_bbox.l == expected["l"]
    assert menge.source_bbox.r == expected["r"]


def test_formula_bbox_matches_fixture_prov(doc, docling):
    formula = doc.blocks[0].children[3]
    assert isinstance(formula, Formula)
    expected = docling["texts"][4]["prov"][0]["bbox"]
    assert formula.source_bbox.l == expected["l"]
    assert formula.source_bbox.b == expected["b"]
    assert formula.page_no == 1


# ---------------------------------------------------------------------------
# Section detection + nesting
# ---------------------------------------------------------------------------


def test_two_sections_detected_at_top_level(doc):
    assert [type(b).__name__ for b in doc.blocks] == ["Section", "Section"]
    assert doc.blocks[0].title == "1 Mengen und Abbildungen"
    assert doc.blocks[1].title == "2 Folgen und Konvergenz"


def test_blocks_nest_under_preceding_section(doc):
    sec1, sec2 = doc.blocks
    # section 1 holds the Menge/Injektivitaet defs, the citation paragraph and
    # the injectivity formula.
    assert [type(b).__name__ for b in sec1.children] == [
        "Definition",
        "Paragraph",
        "Definition",
        "Formula",
    ]
    # section 2 holds Konvergenz def + convergence formula.
    assert [type(b).__name__ for b in sec2.children] == ["Definition", "Formula"]


def test_blocks_before_first_section_stay_at_root():
    docling = {
        "origin": {},
        "body": {"children": [{"$ref": "#/texts/0"}, {"$ref": "#/texts/1"}]},
        "texts": [
            {"label": "text", "text": "Loose intro.", "orig": "Loose intro.",
             "prov": [{"page_no": 1, "bbox": {"l": 0, "t": 1, "r": 1, "b": 0}, "charspan": [0, 12]}]},
            {"label": "section_header", "level": 1, "text": "1 Start", "orig": "1 Start",
             "prov": [{"page_no": 1, "bbox": {"l": 0, "t": 2, "r": 1, "b": 1}, "charspan": [0, 7]}]},
        ],
    }
    blocks = blocks_from_docling(docling, "d")
    assert isinstance(blocks[0], Paragraph)
    assert isinstance(blocks[1], Section)


def test_state_is_structure_ready_and_indices_empty(doc):
    assert doc.ingestion_state == "structure_ready"
    assert doc.occurrences == []
    assert doc.concepts == []
    assert doc.relations == []


# ---------------------------------------------------------------------------
# Char-span subdivision helper
# ---------------------------------------------------------------------------


def test_subdivide_bbox_linear_interpolation():
    bbox = BBox(l=100.0, t=10.0, r=200.0, b=0.0, page_no=1)
    # node charspan [0, 10); take the middle half [2, 7)
    sub = subdivide_bbox(bbox, [0, 10], 2, 7)
    assert sub.l == pytest.approx(120.0)
    assert sub.r == pytest.approx(170.0)
    # t/b/page preserved
    assert (sub.t, sub.b, sub.page_no) == (10.0, 0.0, 1)


def test_subdivide_bbox_full_span_is_identity_width():
    bbox = BBox(l=50.0, t=5.0, r=150.0, b=0.0)
    sub = subdivide_bbox(bbox, [0, 20], 0, 20)
    assert sub.l == pytest.approx(50.0)
    assert sub.r == pytest.approx(150.0)


def test_subdivide_bbox_clamps_out_of_range():
    bbox = BBox(l=0.0, t=1.0, r=100.0, b=0.0)
    # requesting beyond the charspan clamps to the box edges
    sub = subdivide_bbox(bbox, [0, 10], -5, 999)
    assert sub.l == pytest.approx(0.0)
    assert sub.r == pytest.approx(100.0)


def test_subdivide_bbox_none_inputs():
    assert subdivide_bbox(None, [0, 5], 0, 1) is None
    bbox = BBox(l=0.0, t=1.0, r=10.0, b=0.0)
    assert subdivide_bbox(bbox, None, 0, 1) is None
