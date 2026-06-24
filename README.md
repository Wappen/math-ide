# Math IDE

A system that ingests mathematical PDFs and makes their content **navigable**: users explore a
rebuilt, structured view of the document — clicking symbols, formulas, and defined concepts to jump
between definitions and the places those concepts are used.

The domain language lives in [`CONTEXT.md`](CONTEXT.md); the hard-to-reverse design decisions are
recorded as ADRs in [`docs/adr/`](docs/adr/).

## What it does

Ingestion runs in **stages** so the document is usable before the slow parts finish:

```
PDF ──(Docling)──▶ Docling JSON ──▶ math document ──▶ ontology ──▶ rendered IDE
                                    (blocks)          (occurrences/         (HTML + KaTeX,
                                                       concepts/relations)    click navigation)
   └─────────── stage 1: structure + occurrences + concept seeds (synchronous, fast) ───────────┘
                          └──── stage 2: LLM meaning resolution (async) ────┘
```

- **Ingestion** turns a Docling document into a canonical **math document**: a tree of typed blocks
  (`Section`, `Paragraph`, `Definition`, `Theorem`, `Lemma`, …, `Formula`). Formal environments are
  detected from text (with preamble splitting); formulas keep a linearized `orig` fallback immediately
  and upgrade to LaTeX in place when enrichment completes; each formula carries a **symbol index**.
- **Ontology** indexes the document: **occurrences** (every surface appearance of notation, with dual
  *source*/*render* bounding boxes), **concepts** (the mathematical objects notation denotes, seeded
  from formal blocks), and **relations** (deterministic structural edges plus LLM-inferred semantic
  edges). **Meaning resolution** runs an LLM asynchronously to assign symbols to concepts and infer
  meaning — but **formal meaning is authoritative and never overridden**.
- **Renderer + IDE** rebuilds the document as interactive HTML (KaTeX for formulas), with **left-click
  go-to-definition** and **right-click concept cards**. Navigation logic is precomputed in Python so it
  is testable without a browser; the JavaScript layer is thin.

## Requirements

- Python 3.10+
- Core runtime is lightweight: `pydantic`, `anthropic`, `openai`, `python-dotenv` (see `requirements.txt`).
- **Optional** heavy extras, installed only when you need them:
  - Live PDF → Docling JSON conversion: `requirements-ingest.txt` (Docling + PyTorch + models).
  - Browser interaction tests: `pip install playwright && playwright install chromium`.

## Setup

```bash
cd ~/math-ide
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt          # core: pydantic, anthropic, openai
pip install -r requirements-dev.txt       # tests: pytest
# optional, only for live PDF ingestion (large download):
# pip install -r requirements-ingest.txt
```

## Quickstart (offline, no GPU, no API key)

The repo ships a synthetic Docling-JSON fixture (`tests/fixtures/example_docling.json`) so you can run
the whole loop without converting a PDF.

```bash
# Stage 1 only — fast, returns at 'structure_ready' (citations + formal navigation already work)
python -m math_ide ingest tests/fixtures/example_docling.json --document-id demo -o math-doc.json

# Full pipeline — runs stage 2 (meaning resolution) to 'ready' using the deterministic mock resolver
python -m math_ide ingest tests/fixtures/example_docling.json --document-id demo --wait -o math-doc.json

# Render the math document to a standalone interactive HTML page
python -m math_ide render math-doc.json -o math-ide.html

# Or serve it (math document + assets) over HTTP
python -m math_ide serve math-doc.json
```

Open `math-ide.html` in a browser: formulas render with KaTeX, **left-click** an identifier or citation
to go to its definition, **right-click** to open its concept card. Symbols not yet linked by meaning
resolution show a "resolving…" state.

### Live PDF ingestion

With the optional Docling extra installed, point `ingest` at a PDF or URL instead of a JSON file:

```bash
pip install -r requirements-ingest.txt
python -m math_ide ingest paper.pdf --wait -o math-doc.json
```

Docling formula enrichment (LaTeX) is **on by default**; pass `--no-formula` to disable it. `--ocr`
enables OCR for scanned PDFs.

### Live LLM meaning resolution

Without `--wait` the document stops at `structure_ready` and no resolver runs. With `--wait` the
default resolver is `auto`, which reads the environment: `ANTHROPIC_API_KEY` → Anthropic, else
`OPENAI_API_KEY` → OpenAI, else the deterministic offline mock (with a one-line warning to stderr).
Both SDKs are already core dependencies. Set a key via the environment or a
project ``.env`` file (see below):

```bash
# Option A: project .env (gitignored) — loaded automatically by the CLI
cp .env.example .env
# edit .env and add ANTHROPIC_API_KEY=sk-... or OPENAI_API_KEY=sk-...
python -m math_ide ingest tests/fixtures/example_docling.json --wait -o math-doc.json

# Option B: export in the shell
export ANTHROPIC_API_KEY=sk-...
python -m math_ide ingest tests/fixtures/example_docling.json --wait -o math-doc.json

# or pin a provider explicitly
export OPENAI_API_KEY=sk-...
python -m math_ide ingest tests/fixtures/example_docling.json --wait --resolver openai -o math-doc.json
```

With ``--wait``, ``auto`` picks Anthropic if ``ANTHROPIC_API_KEY`` is set, else
OpenAI if ``OPENAI_API_KEY`` is set, else the offline mock. Shell exports take
precedence over ``.env`` when both define the same variable.

The Anthropic resolver (model `claude-sonnet-4-6` by default) and the OpenAI resolver (model `gpt-4o`
by default, overridable via `OPENAI_MODEL`) are failure-tolerant: on API/parse errors they retry, then
return partial results rather than crashing the pipeline. Pinning `--resolver anthropic` or
`--resolver openai` without the matching key fails fast (exit code 2) before any network call.

## Pipeline states

`ingesting → structure_ready → resolving → ready`

- **structure_ready** — blocks, occurrences, concept seeds, and all *structural* relations exist;
  citation and formal-block navigation work. The IDE can open the document here.
- **resolving / ready** — meaning resolution links symbols to concepts and adds *semantic* relations.
  Each mutation bumps a monotonic `version`/`etag` so a live renderer can refresh only what changed.
  `resolving` is also the terminal state when stage 2 fails (stage-1 results are preserved).

See [`docs/pipeline.md`](docs/pipeline.md) for the orchestration API and the in-place formula-upgrade
reflow path.

## CLI reference

| Command | Purpose |
| --- | --- |
| `python -m math_ide ingest <source>` | Ingest a Docling `.json` **or** a PDF/URL into a math document. Flags: `-o`, `--document-id`, `--wait`, `--resolver {mock,anthropic,openai,auto}` (default `auto` with `--wait`, else `mock`), `--no-formula`, `--ocr`. |
| `python -m math_ide render <math-doc.json>` | Render a math document JSON to a standalone HTML page (`-o`). |
| `python -m math_ide serve <math-doc.json>` | Serve the rendered page plus assets over HTTP. |
| `python pdf_to_docling.py <pdf>` | **Legacy** thin Docling CLI (markdown/JSON/LaTeX export). Superseded by `math_ide ingest` for the math document; kept for raw Docling output. |

## Project layout

```
math_ide/
├── schema.py            # canonical math-document schema (Pydantic v2) — source of truth
├── ingest/              # Docling JSON → block tree: formal-block detection, formulas, symbol index
├── ontology/            # occurrences, concept seeding + structural relations, LLM meaning resolution
├── renderer/            # math document → interactive HTML; navigation precompute; app.js / styles.css
├── pipeline.py          # staged ingestion orchestration (state machine, versioning, formula upgrade)
└── __main__.py          # `python -m math_ide` subcommand dispatcher
tests/                   # offline suite (default), gated browser + LLM suites; fixtures/
docs/                    # adr/, math-document-schema.md, ingestion/ontology/renderer/ide/pipeline.md
pdf_to_docling.py        # legacy Docling CLI
```

## Testing

```bash
# Default offline suite — no GPU, no network, no browser
.venv/bin/python -m pytest -q

# Browser interaction tests (render bboxes + clicks): install Playwright first
pip install playwright && playwright install chromium && .venv/bin/python -m pytest -q tests/test_ide_browser.py

# Live LLM resolution tests (skipped by default)
RUN_LLM_TESTS=1 ANTHROPIC_API_KEY=sk-... .venv/bin/python -m pytest -q tests/test_acceptance_llm.py
```

The browser and LLM suites skip cleanly when their dependencies/credentials are absent. See
[`tests/README.md`](tests/README.md) for details and the offline-fixture-vs-PDF rationale.

## Documentation

- [`CONTEXT.md`](CONTEXT.md) — domain glossary (the project's shared language).
- [`docs/adr/`](docs/adr/) — architecture decision records.
- [`docs/math-document-schema.md`](docs/math-document-schema.md) — block types and indices.
- [`docs/ingestion.md`](docs/ingestion.md), [`docs/ontology.md`](docs/ontology.md),
  [`docs/renderer.md`](docs/renderer.md), [`docs/ide.md`](docs/ide.md),
  [`docs/pipeline.md`](docs/pipeline.md) — per-stage design docs.

## License

Docling is MIT-licensed. See the [Docling repository](https://github.com/docling-project/docling) for
details.
