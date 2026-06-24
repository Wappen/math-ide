"""Structure tests against the *real* Docling export of ``example.pdf`` (issue #22).

The synthetic fixture (``example_docling.json``) has no document-title heading
and no page furniture, so it cannot catch the two regressions #22 fixes:

* the document title ``"Testskript: Einführung in die Analysis"`` is a
  ``section_header`` (level 1, identical to the real numbered headers) — it must
  become document *metadata*, not a top-level ``Section`` peer; and
* the ``page_footer`` ``"1"`` (``content_layer == "furniture"``) is a page
  number — it must be dropped, not turned into a content paragraph.

The committed ``example_docling_real.json`` is the live Docling output, so these
assertions exercise the real code path without requiring a live conversion.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from math_ide.ingest import build_math_document
from math_ide.ontology.occurrences import iter_blocks
from math_ide.schema import Section

REAL_FIXTURE = Path(__file__).parent / "fixtures" / "example_docling_real.json"


@pytest.fixture()
def real_docling() -> dict:
    return json.loads(REAL_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture()
def real_doc(real_docling):
    return build_math_document(real_docling)


def _block_text(block) -> str:
    """Whatever surface string a block carries (title / text / body)."""
    return (
        getattr(block, "title", None)
        or getattr(block, "text", None)
        or getattr(block, "body", None)
        or ""
    )


def test_page_footer_page_number_is_dropped(real_doc):
    """#22: the ``page_footer`` ``"1"`` (node[14], content_layer=furniture)
    produces no block at all — neither a title/text of ``"1"`` anywhere in the
    tree, nor a ``para-14-1`` id."""
    blocks = list(iter_blocks(real_doc.blocks))
    assert all(_block_text(b) != "1" for b in blocks), "page-number footer leaked"
    assert all("para-14-1" not in b.id for b in blocks)


def test_top_level_sections_are_exactly_the_two_numbered_headers(real_doc):
    """#22: the only top-level ``Section`` blocks are the real numbered headers —
    the document title is NOT a ``Section`` peer."""
    sections = [b for b in real_doc.blocks if isinstance(b, Section)]
    assert [s.title for s in sections] == [
        "1 Grundbegriffe der Mengenlehre",
        "2 Folgen und Grenzwerte",
    ]
    # The title text must not appear as a Section title anywhere in the tree.
    all_sections = [b for b in iter_blocks(real_doc.blocks) if isinstance(b, Section)]
    assert all(
        s.title != "Testskript: Einführung in die Analysis" for s in all_sections
    )


def test_document_title_subtitle_date_are_metadata_not_blocks(real_doc):
    """#22: title/subtitle/date are document metadata (umlaut-repaired), and none
    of those strings appear as a content block."""
    assert real_doc.title == "Testskript: Einführung in die Analysis"
    assert real_doc.subtitle == "Test-Szenario für Docling Pipeline"
    assert real_doc.date == "24. Juni 2026"

    front_matter = {real_doc.title, real_doc.subtitle, real_doc.date}
    block_texts = {_block_text(b) for b in iter_blocks(real_doc.blocks)}
    assert front_matter.isdisjoint(block_texts), "front matter leaked into blocks"
