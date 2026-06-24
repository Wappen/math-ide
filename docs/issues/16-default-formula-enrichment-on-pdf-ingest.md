---
title: Default formula enrichment on for live PDF ingest
labels: ingestion
---

## Summary

Enable Docling `do_formula_enrichment` **by default** on the live PDF ingest path so formula blocks are born `ready` with LaTeX and KaTeX can typeset them. Add `--no-formula` as an explicit opt-out for fast/debug runs.

## Context

KaTeX only typesets formulas when `enrichment_status: "ready"` and `latex` is set. Today `python -m math_ide ingest example.pdf` skips enrichment unless the user passes `--formula`, because the CLI flag is `store_true` (default `False`). `docling_runner.run_docling()` defaults `formula=True`, but the CLI always passes `args.formula`, overriding that default.

Live Docling output on the example corpus shows formula nodes with empty `"text": ""` and `enrichment_status: "pending"` in the resulting math document — formulas render as unicode `orig_fallback`, not LaTeX.

Related: **#5**, **#10**.

## Scope

- Flip `math_ide ingest` to default `do_formula_enrichment=True` for live PDF/URL conversion
- Replace `--formula` with `--no-formula` (or equivalent) so the default is on and users opt out explicitly
- Align `pdf_to_docling.py` the same way (today `--formula` is opt-in there too)
- Keep the JSON ingest path unchanged (pre-converted Docling dict is read as-is)
- Update `README.md`, `docs/ingestion.md`, and `docs/pipeline.md` CLI tables

## Acceptance criteria

- [ ] `python -m math_ide ingest example.pdf` produces formula blocks with `enrichment_status: "ready"` and non-empty `latex` when Docling enrichment succeeds
- [ ] `--no-formula` disables enrichment and formulas stay `pending` with `orig_fallback` only
- [ ] `pdf_to_docling.py` matches the default-on / opt-out behaviour
- [ ] Tests cover default-on and `--no-formula` CLI wiring

## Out of scope

- Fixing Docling when enrichment returns empty `text` despite `do_formula_enrichment=True` (see **#17**)
- KaTeX renderer changes (**#10** — already implemented; this issue unblocks it)
