"""Schema round-trip and fixture-shape tests (issue #1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import math_ide
from math_ide.schema import (
    BBox,
    Concept,
    Definition,
    Formula,
    MathDocument,
    Occurrence,
    Paragraph,
    Relation,
    Section,
    SourceProvenance,
    SymbolSpan,
    Theorem,
    mint_id,
    slugify,
)

FIXTURE = Path(__file__).parent / "fixtures" / "example_docling.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_doc() -> MathDocument:
    """A small but representative hand-built math document."""
    doc_id = "doc-test"
    definition = Definition(
        id=mint_id(doc_id, "block", "Definition 1.1"),
        number="1.1",
        defined_name="Menge",
        body="Eine Menge ist eine Zusammenfassung von Objekten.",
        source_bbox=BBox(l=72.0, t=720.0, r=523.0, b=686.0, page_no=1),
        page_no=1,
    )
    formula = Formula(
        id=mint_id(doc_id, "block", "formula-conv"),
        orig_fallback="∀ ε > 0 ∃ N ∈ ℝ ∀ n ≥ N : |a_n − L| < ε",
        enrichment_status="pending",
        symbol_index=[SymbolSpan(token="ε", start=2, end=3, kind="variable")],
        source_bbox=BBox(l=150.0, t=674.0, r=460.0, b=656.0, page_no=2),
        page_no=2,
    )
    paragraph = Paragraph(
        id=mint_id(doc_id, "block", "para-1"),
        text="Nach Definition 1.1 ist eine Menge bestimmt.",
        page_no=1,
    )
    theorem = Theorem(
        id=mint_id(doc_id, "block", "Satz 2.1"),
        number="2.1",
        defined_name="Vollstaendigkeit",
        body="Jede beschraenkte Folge hat eine konvergente Teilfolge.",
        page_no=2,
    )
    section = Section(
        id=mint_id(doc_id, "block", "Section 1"),
        title="1 Mengen und Abbildungen",
        children=[definition, paragraph, formula, theorem],
        page_no=1,
    )

    occ_defined = Occurrence(
        id=mint_id(doc_id, "occ", "menge-name"),
        kind="defined_name",
        block_id=definition.id,
        span=(16, 21),
        source_bbox=BBox(l=120.0, t=720.0, r=160.0, b=706.0, page_no=1),
    )
    occ_citation = Occurrence(
        id=mint_id(doc_id, "occ", "cite-1-1"),
        kind="citation",
        block_id=paragraph.id,
        span=(5, 19),
        target_block_id=definition.id,
    )
    occ_symbol = Occurrence(
        id=mint_id(doc_id, "occ", "eps"),
        kind="formula_symbol",
        block_id=formula.id,
        span=(2, 3),
    )

    concept = Concept(
        id=mint_id(doc_id, "concept", "Menge"),
        name="Menge",
        formal_meaning="Eine Zusammenfassung von Objekten.",
        resolution_status="resolved",
        defining_occurrence_id=occ_defined.id,
        seeded_by_block_id=definition.id,
    )
    relation_seeded = Relation(
        source_concept_id=concept.id,
        target_concept_id=definition.id,
        kind="seeded_by",
        origin="structural",
        target_is_block=True,
    )

    return MathDocument(
        document_id=doc_id,
        source=SourceProvenance(
            origin="pdf",
            filename="analysis_skript.pdf",
            mimetype="application/pdf",
            binary_hash="deadbeef",
        ),
        blocks=[section],
        occurrences=[occ_defined, occ_citation, occ_symbol],
        concepts=[concept],
        relations=[relation_seeded],
        ingestion_state="structure_ready",
    )


# ---------------------------------------------------------------------------
# Id helpers
# ---------------------------------------------------------------------------


def test_slugify_folds_german_chars():
    assert slugify("Injektivität") == "injektivitaet"
    assert slugify("Definition 1.1") == "definition-1-1"
    assert slugify("Maß") == "mass"


def test_mint_id_is_document_namespaced():
    out = mint_id("doc-9", "concept", "Menge")
    assert out == "doc-9#concept/menge"
    assert out.startswith("doc-9#")


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_json_round_trip_validates_and_preserves_classes():
    doc = build_doc()

    raw = doc.model_dump_json()
    # Reload via JSON string -> validates schema constraints.
    reloaded = MathDocument.model_validate_json(raw)

    assert reloaded == doc

    # The tagged union must reload blocks to their *specific* classes.
    section = reloaded.blocks[0]
    assert isinstance(section, Section)
    kids = section.children
    assert isinstance(kids[0], Definition)
    assert isinstance(kids[1], Paragraph)
    assert isinstance(kids[2], Formula)
    assert isinstance(kids[3], Theorem)

    # And NOT a generic / wrong class.
    assert type(kids[0]) is Definition
    assert type(kids[3]) is Theorem
    assert kids[0].defined_name == "Menge"
    assert kids[2].canonical_content.startswith("∀ ε")


def test_round_trip_through_plain_dict():
    doc = build_doc()
    as_dict = doc.model_dump(mode="json")
    # Ensure it's plain-JSON serializable (tuples -> lists etc.).
    json.dumps(as_dict)
    reloaded = MathDocument.model_validate(as_dict)
    assert reloaded == doc
    assert isinstance(reloaded.blocks[0].children[2], Formula)


def test_indices_and_relations_round_trip():
    doc = build_doc()
    reloaded = MathDocument.model_validate_json(doc.model_dump_json())
    assert [o.kind for o in reloaded.occurrences] == [
        "defined_name",
        "citation",
        "formula_symbol",
    ]
    cite = next(o for o in reloaded.occurrences if o.kind == "citation")
    assert cite.target_block_id == reloaded.blocks[0].children[0].id
    rel = reloaded.relations[0]
    assert rel.kind == "seeded_by"
    assert rel.origin == "structural"
    assert rel.target_is_block is True


def test_render_bbox_defaults_none_source_bbox_set():
    doc = build_doc()
    occ = next(o for o in doc.occurrences if o.kind == "defined_name")
    assert occ.render_bbox is None
    assert occ.source_bbox is not None


def test_extra_fields_rejected():
    with pytest.raises(Exception):
        Definition.model_validate(
            {"id": "x#block/d", "type": "Definition", "bogus_field": 1}
        )


def test_model_json_schema_exposed():
    schema = MathDocument.model_json_schema()
    assert schema["title"] == "MathDocument"
    assert "ingestion_state" in schema["properties"]
    assert "blocks" in schema["properties"]


def test_package_reexports():
    assert math_ide.__version__
    assert math_ide.MathDocument is MathDocument
    assert math_ide.Definition is Definition


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


def test_fixture_parses_as_json_with_expected_nodes():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert data["schema_name"] == "DoclingDocument"
    texts = data["texts"]
    assert len(texts) == 8

    # Every node has provenance with a bbox + charspan.
    for node in texts:
        assert node["prov"], f"missing prov on {node['self_ref']}"
        prov = node["prov"][0]
        assert "page_no" in prov
        assert "charspan" in prov
        bbox = prov["bbox"]
        assert set(bbox) >= {"l", "t", "r", "b", "coord_origin"}
        assert bbox["coord_origin"] == "BOTTOMLEFT"

    labels = [n["label"] for n in texts]
    assert labels.count("section_header") == 2
    assert labels.count("formula") == 2

    headers = [n["text"] for n in texts if n["label"] == "section_header"]
    assert "1 Mengen und Abbildungen" in headers
    assert "2 Folgen und Konvergenz" in headers


def test_fixture_has_clean_definition_and_citation():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    texts = {n["self_ref"]: n for n in data["texts"]}

    # Definition 1.1 (Menge) clean block, no merged preamble.
    menge = texts["#/texts/1"]
    assert menge["text"].startswith("Definition 1.1 (Menge):")

    # Citation paragraph references Definition 1.1.
    cite_para = texts["#/texts/2"]
    assert "Definition 1.1" in cite_para["text"]
    assert not cite_para["text"].startswith("Definition")  # it's prose, not a block


def test_fixture_merged_preamble_node():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    node = next(n for n in data["texts"] if n["self_ref"] == "#/texts/3")
    # Leading prose merged into the SAME node as the Definition 1.2 label.
    assert node["text"].startswith("Ein wichtiges Konzept")
    assert "Definition 1.2 (Injektivitaet):" in node["text"]


def test_fixture_formulas_have_orig_and_empty_text():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    formulas = [n for n in data["texts"] if n["label"] == "formula"]
    assert len(formulas) == 2
    for f in formulas:
        assert f["text"] == ""  # enrichment pending
        assert f["orig"]  # linearized fallback present

    inj, conv = formulas
    assert "f(x₁) = f(x₂)" in inj["orig"]
    # Convergence formula carries ε, a_n, L, N, ℝ for the symbol index.
    for token in ("ε", "a_n", "L", "N", "ℝ"):
        assert token in conv["orig"]


def test_fixture_loads_into_formula_block_via_schema():
    """The fixture's formula orig can seed a pending Formula block."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    conv = next(
        n for n in data["texts"] if n["label"] == "formula" and "ε" in n["orig"]
    )
    prov = conv["prov"][0]
    formula = Formula(
        id="doc#block/f",
        orig_fallback=conv["orig"],
        enrichment_status="pending",
        source_bbox=BBox(**prov["bbox"], page_no=prov["page_no"]),
        page_no=prov["page_no"],
    )
    assert formula.canonical_content == conv["orig"]

    # Pending -> ready upgrade swaps the canonical content to LaTeX.
    formula.latex = (
        r"\forall \varepsilon>0 \, \exists N \in \mathbb{R} "
        r"\, \forall n \ge N : |a_n - L| < \varepsilon"
    )
    formula.enrichment_status = "ready"
    assert formula.canonical_content == formula.latex
