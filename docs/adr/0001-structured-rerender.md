# 0001 — Structured re-render over PDF overlay

Status: Accepted

## Context

The Math IDE must let users click symbols, formulas, and defined concepts and navigate between definitions and their uses. Two interaction substrates are possible: keep the original PDF pages on screen and paint invisible hit-target overlays at the coordinates of each interactive element, or rebuild the document from parsed content and render it ourselves. Hit targets need stable coordinates, formulas need to be selectable down to individual identifiers, and the layout must adapt as asynchronous enrichment upgrades formulas and as meaning resolution attaches concepts to occurrences.

## Decision

The Math IDE renders the *rendered document* from the structured *math document* tree (typed blocks, formulas as LaTeX, occurrence anchors), not from PDF page images with overlays. Formulas render through KaTeX, occurrences become real DOM anchors, and the canonical *render bbox* is measured in the rendered document's own coordinate space; the *source bbox* in PDF coordinates is retained only for provenance and validation.

## Why

Rendering from structure makes every interactive element a first-class node we own, so identifier-level hit targets, go-to-definition, and concept cards fall out of the DOM instead of from coordinate math against a raster page. It also lets the view evolve in place — pending formulas upgrade when LaTeX enrichment lands and occurrences light up as meaning resolution completes — which an overlay pinned to fixed PDF coordinates cannot do gracefully. Provenance to the source PDF is not lost: it is preserved as source bboxes rather than as the primary interaction surface.

## Considered options

- **PDF page rendering with hit-target overlays** — rejected: brittle coordinate tracking, no sub-formula selection, and no clean way to reflow when enrichment or resolution changes content after the page is painted.
- **Structured re-render from the math document** — chosen.
