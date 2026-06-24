---
title: Document title and page furniture become content blocks
labels: ingestion
---

## Summary

On the real `example.pdf` run, Docling labels the document title `Testskript: Einführung in die Analysis` as a `section_header` (level 1, identical to the real numbered headers), so the adapter turns it into a top-level `Section` peer to `1 …` / `2 …`, with the subtitle and date nested as `Paragraph` children. Separately, the Docling `page_footer` node carrying the page number `1` falls through the unknown-label branch and becomes a trailing content `Paragraph`. The fix is to filter non-content furniture (`page_footer` / `page_header`) out of the block tree and represent the title/subtitle/date distinctly rather than as a `Section`.

## Context

Live Docling export `docling_enriched.json` has 15 text nodes. `node[0]` is `label=section_header`, `level=1`, `content_layer=body`, text `"Testskript: Einf¨ uhrung in die Analysis"` — the same label and level as the real headers `node[3]` `"1 Grundbegriffe der Mengenlehre"` and `node[8]` `"2 Folgen und Grenzwerte"`. Because `blocks_from_docling` in `math_ide/ingest/docling_adapter.py` branches purely on `if label == "section_header"` (line 324), the title becomes a top-level `Section`; `node[1]` `"Test-Szenario f¨ ur Docling Pipeline"` and `node[2]` `"24. Juni 2026"` nest under it as `Paragraph` children. `mathdoc_enriched.json` confirms `"type": "Section", "title": "Testskript: Einführung in die Analysis"` with `para-1` and `para-2` as children, and the rendered IDE page makes it a peer section:

```html
<section class="block section" id="example#block/section-0-testskript-einfuehrung-in-die-analysis" data-block-id="example#block/section-0-testskript-einfuehrung-in-die-analysis"><h2 class="section-title">Testskript: Einführung in die Analysis</h2><p class="block paragraph" id="example#block/para-1-test-szenario-fuer-doclin" data-block-id="example#block/para-1-test-szenario-fuer-doclin">Test-Szenario für Docling Pipeline</p><p class="block paragraph" id="example#block/para-2-24-juni-2026" data-block-id="example#block/para-2-24-juni-2026">24. Juni 2026</p></section>
```

Separately, `node[14]` is `label=page_footer`, `content_layer=furniture`, text `"1"` (the page number). `_iter_body_nodes` (lines 240-259) walks `body.children` with no `content_layer` or furniture filtering, and since `page_footer` is neither `section_header` nor `formula` it falls through the `else` branch (lines 330-336) to a `Paragraph`, rendered as document content:

```html
<p class="block paragraph" id="example#block/para-14-1" data-block-id="example#block/para-14-1">1</p>
```

The `MathDocument` schema (`math_ide/schema.py` lines 396-413) carries only `document_id` / `source` / `blocks` / `occurrences` / `concepts` / `relations` / `ingestion_state` — there is no document-title or metadata field and no notion of furniture. The synthetic fixture `tests/fixtures/example_docling.json` masks both problems: it has no title node, no `page_footer` node, and every node has `content_layer=None`, so the structure tests never see a furniture node or a title-as-header. (The evidence above quotes the un-repaired Docling `orig` `"Einf¨ uhrung"`; the rendered HTML correctly shows the umlaut-repaired `"Einführung"` per **#18** — this does not weaken the claim.)

Relates to **#3** (Docling-to-MathDocument transformer) and **#4** (formal-block detection / preamble splitting).

## Scope

- In `blocks_from_docling` / `_iter_body_nodes` (`math_ide/ingest/docling_adapter.py`), skip non-content furniture nodes (`page_footer`, `page_header`, and page-number content) so they never become blocks — prefer filtering on Docling `content_layer == "furniture"` and/or the furniture labels.
- Stop modeling the document title as a top-level `Section`: detect the leading `section_header` that is the document title (distinct from the real numbered headers) and represent it distinctly — as document metadata on `MathDocument` (`math_ide/schema.py`) or a dedicated title block — with the subtitle (`node[1]`) and date (`node[2]`) attached to that, not nested as content `Paragraph`s under a `Section`.
- Update `tests/fixtures/example_docling.json` (or add a furniture-bearing fixture) so the structure tests exercise a `page_footer`/`content_layer=furniture` node and a title node, since the current fixture diverges from real Docling output and cannot catch this regression.

## Acceptance criteria

- [ ] On `example.pdf`, the `page_footer` `"1"` (`node[14]`) produces no block: no `<p class="block paragraph" … >1</p>` and no `para-14-1` id in the rendered HTML or `MathDocument.blocks`.
- [ ] On `example.pdf`, the top-level `Section` blocks are exactly `1 Grundbegriffe der Mengenlehre` and `2 Folgen und Grenzwerte` — the title `Testskript: Einführung in die Analysis` is not a `Section` peer.
- [ ] The title / subtitle / date are represented distinctly (document metadata or a dedicated title block), not as a `Section` containing `para-1` / `para-2` content paragraphs.
- [ ] A fixture-backed test covers furniture filtering and title handling without requiring live Docling.

## Out of scope

- Full front-matter modeling (authors, affiliations, abstract, multi-line title pages).
- Header/footer running-text capture or footnote handling beyond dropping page-number furniture.
- Upstream Docling label-quality fixes (title vs. header disambiguation belongs to the adapter here).
