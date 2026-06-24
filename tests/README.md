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
