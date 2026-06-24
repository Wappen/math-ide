# Math IDE test suite

The default suite is **offline, deterministic, and network/GPU-free**. Two
subsets self-gate so they never run in CI by accident: a browser test and the
live-LLM acceptance tests.

## Run the default offline suite

From the repo root (`/home/deni/math-ide`):

```bash
.venv/bin/python -m pytest -q
```

This runs everything: schema, ingestion, ontology, navigation, renderer,
pipeline, and the end-to-end acceptance loop
(`test_acceptance_e2e.py`). It needs only `pydantic` + `pytest`. The browser test
and the live-LLM tests are skipped automatically (see below), so a clean run
reports the offline tests as **passed** with those two subsets **skipped**.

## The end-to-end acceptance loop (`test_acceptance_e2e.py`)

Issue #15 covers the full Math IDE loop through the **public** pipeline /
navigation API: structure → occurrences → resolution → navigation → concept card
→ dual bboxes. Seven scenarios, plus a *staged* test (data usable at
`structure_ready` before resolution) and a *formula-upgrade* test (re-entrant
enrichment without full re-ingest). Resolution uses the deterministic
`MockResolver`; nothing touches the network.

### Why a synthetic Docling-JSON fixture stands in for the example PDF

The acceptance tests ingest `fixtures/example_docling.json`, **not** a real PDF.

Ingestion consumes a Docling-style `export_to_dict()` mapping; the heavy
`docling` PDF→JSON model is isolated behind a lazy import and never runs in
tests. A hand-authored JSON dict therefore drives the **exact same code path** a
live conversion would feed in, while staying:

* **offline & GPU-free** — `docling`/`torch` are not installed and not needed;
* **deterministic** — no model variance, so assertions can be exact;
* **fast** — the whole acceptance suite runs in well under a second.

The fixture encodes the canonical German analysis corpus (two sections; three
definitions — *Menge*, *Injektivität* with a preamble, *Konvergenz*; a
`Definition 1.1` citation; an injectivity formula and a convergence formula),
which is precisely what the downstream issues need to hit their acceptance
criteria.

## Synthetic vs. real fixtures (issues #20–#24)

There are **two** committed Docling-JSON inputs, serving different lanes:

* **`fixtures/example_docling.json` — synthetic / idealized.** Hand-authored,
  *tight* input for the fast deterministic offline lane
  (`test_acceptance_e2e.py`). Its idealized spellings let assertions be exact:
  the ASCII name `Injektivitaet`, the unicode tokens `ε` / `a_n` / `x₁`, an ℝ
  convergence domain, and a `Nach Definition 1.1 …` **citation** paragraph. We
  **keep** it as the fast offline lane.
* **`fixtures/example_docling_real.json` — a captured real Docling 2.107.0
  export of `example.pdf`** (formula enrichment on). This is exactly what the
  live model emits, used by the offline *real-shaped* tests:
  `test_structure_real.py` (#22, title/footer/sections),
  `test_resolution_real.py` (#21, divergent-spelling resolution),
  `test_inline_occurrences.py` (#23, inline-prose `inline_symbol` occurrences),
  and `test_acceptance_real.py` (#24, a single end-to-end full-loop pass +
  citation-absence). See `fixtures/README.md` for the full divergence table.

The synthetic fixture **diverges from real Docling output** by design: it is a
*tight* input, not a snapshot. The real fixture captures what actually happens —
real section titles (`1 Grundbegriffe der Mengenlehre` / `2 Folgen und
Grenzwerte`), the umlaut name `Injektivität`, LaTeX tokens (`\epsilon`,
`a _ { n }`, `x _ { 1 }`), a ℕ (`\mathbb { N }`) convergence domain, and inline
prose notation.

### Citation divergence (the heart of #24)

`example.pdf` contains **no numbered cross-reference**, so the real pipeline
yields **zero `citation` occurrences** — that is correct, not a bug. The
synthetic fixture's `Nach Definition 1.1 …` paragraph is **idealized input** that
exists solely to exercise the citation code path (deterministic
`definition_target` to the *Menge* block) which the real PDF does not contain.
`test_acceptance_real.py` and the gated live test both assert this absence
explicitly.

## Gated live Docling test (`test_acceptance_e2e_live.py`)

Re-runs the **live** `docling` PDF→JSON conversion of `example.pdf` (instead of
feeding a pre-converted dict) and asserts the same real behaviour end-to-end —
section titles, the three defined names, no page-footer block, **zero citation
occurrences**, real formula tokens, and go-to-definition navigation after
`MockResolver`. It is the live companion to the offline `test_acceptance_real.py`
and catches drift between the committed `example_docling_real.json` snapshot and
what Docling actually emits.

The whole module is **skipped unless both** hold (and `example.pdf` is present):

* `RUN_DOCLING_TESTS=1` — explicit opt-in (absent in CI; the conversion is slow,
  ~30–90 s, and downloads/uses GPU-capable models);
* the `docling` package importable — via `pytest.importorskip`.

Run locally with:

```bash
RUN_DOCLING_TESTS=1 .venv/bin/python -m pytest -q tests/test_acceptance_e2e_live.py
```

Because the Docling formula model is not perfectly deterministic, its assertions
are **presence/contains** wherever the symbol vocabulary could vary; the
structural invariants #20–#24 fix (section titles, defined names, dropped
furniture, zero citations) are asserted exactly.

## Gated browser test (`test_ide_browser.py`)

Drives the *rendered document* in a real browser (Playwright/Chromium) to cover
the layout/browser-time half of the loop the offline suite cannot:
**render-bbox measurement** (`#11`, the `render_bbox`-populated-post-layout half
of scenario 7) and **click navigation** (`#12`/`#13`). The offline acceptance
suite asserts `render_bbox` stays `None` and cross-references this test for its
population.

It **self-skips** unless Playwright *and* a Chromium binary are available
(via `pytest.importorskip` + a guarded `chromium.launch()`), so the default run
stays green. To run it:

```bash
.venv/bin/pip install playwright
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q tests/test_ide_browser.py
```

## Gated live-LLM tests (`test_acceptance_llm.py`)

Mirror the RESOLUTION assertions of the offline suite, but against the real
`AnthropicResolver` instead of `MockResolver`. Assertions are structural and
tolerant (the LLM is non-deterministic): formal meaning is never overwritten,
the document reaches `ready` or a sane partial, and epsilon coreference +
semantic relations appear when resolution succeeds.

The whole module is **skipped unless both** of these hold (and the `anthropic`
SDK is importable):

* `RUN_LLM_TESTS=1` — explicit opt-in (absent in CI);
* `ANTHROPIC_API_KEY` — present in the environment (or in a project `.env` file,
  which pytest loads via `conftest.py`).

Run locally with:

```bash
cp .env.example .env   # add ANTHROPIC_API_KEY=sk-...
RUN_LLM_TESTS=1 .venv/bin/python -m pytest -q tests/test_acceptance_llm.py
```

Or export the key in the shell:

```bash
RUN_LLM_TESTS=1 ANTHROPIC_API_KEY=sk-... \
    .venv/bin/python -m pytest -q tests/test_acceptance_llm.py
```

## Markers

Registered in `pytest.ini` (with `--strict-markers`, so an unknown marker is an
error rather than a warning):

* `llm` — tags the live-Anthropic tests.
* `browser` — reserved for browser-driven tests.

Shared fixtures live in `conftest.py`: `docling_dict` (the parsed fixture),
`structure_ready_doc` (stage-1), `resolved_doc` / `resolved_doc_readonly`
(stage-2 via `MockResolver`).
