# Math IDE — planned issues

Issue bodies for the design captured in [`CONTEXT.md`](../../CONTEXT.md).

## Create on GitHub

After connecting a remote and installing [GitHub CLI](https://cli.github.com/):

```bash
./scripts/create-github-issues.sh
```

The script creates labels (if missing) and opens issues in dependency order. To preview without creating:

```bash
./scripts/create-github-issues.sh --dry-run
```

## Issue map

| # | Title | Labels | Blocked by |
| --- | --- | --- | --- |
| 1 | Define math document schema | `schema` | — |
| 2 | Record core architecture ADRs | `docs` | — |
| 3 | Build Docling → math document block transformer | `ingestion` | 1 |
| 4 | Detect formal blocks with preamble split | `ingestion` | 3 |
| 5 | Formula blocks with LaTeX enrichment and orig fallback | `ingestion` | 3 |
| 6 | Extract symbol index from formula content | `ingestion` | 5 |
| 7 | Extract occurrences and assign dual bboxes | `ingestion`, `ontology` | 4, 6 |
| 8 | Seed concepts and structural relations | `ontology` | 7 |
| 9 | Meaning resolution pipeline (async LLM) | `ontology`, `llm` | 8 |
| 10 | Render math document to structured view | `renderer` | 1, 7 |
| 11 | Assign render bboxes at layout time | `renderer` | 10 |
| 12 | Left click: go to definition | `ide` | 8, 11 |
| 13 | Right click: concept card with neighbourhood | `ide` | 9, 12 |
| 14 | Staged ingestion orchestration | `ingestion` | 8, 9 |
| 15 | End-to-end acceptance tests (example PDF) | `testing` | 13, 14 |
| 16 | Default formula enrichment on for live PDF ingest | `ingestion` | 5 |
| 17 | Bump Docling and verify German umlaut text quality | `ingestion` | 3 [^17] |
| 18 | Adapter normalize decomposed umlauts (fallback) | `ingestion` | 17 [^18] |
| 19 | OpenAI resolver and auto LLM provider selection | `ontology`, `llm` | 9 |
| 20 | Symbol index extraction breaks on Docling's spaced LaTeX | `ingestion` | — [^e2e] |
| 21 | Offline MockResolver coreference no-ops on real example.pdf | `ontology`, `llm` | 20 [^e2e] |
| 22 | Document title and page furniture become content blocks | `ingestion` | — [^e2e] |
| 23 | Inline math in prose yields no occurrences | `ingestion`, `ontology` | — [^e2e] |
| 24 | Acceptance suite only exercises the synthetic fixture | `testing` | — [^e2e] |
| 25 | Record #17 umlaut verification (Docling 2.107.0 still decomposed) | `ingestion` | — [^e2e] |
| 26 | `openai` core dep absent; `--resolver openai` degrades silently | `llm` | — [^e2e] |

[^e2e]: **Found by a live end-to-end run.** Issues #20–#26 came from actually
    installing Docling (2.107.0), converting `example.pdf`, and running the full
    pipeline (ingest → seed_ontology → MockResolver → render) — the first time the
    real PDF (not the hand-authored `tests/fixtures/example_docling.json`) went
    through the live path. The synthetic fixture diverges from real Docling output,
    so the green suite (276 tests) masked these. #24 is the meta-issue; #20/#21/#23
    are the highest-severity pipeline breaks. See each issue file for the exact
    observed artifacts.

[^17]: **FAIL at `docling 2.107.0`.** The floor was bumped to `>=2.7.0` and a
    live re-conversion of `example.pdf` was run with `docling 2.107.0`; decomposed
    diaeresis **persists** upstream (`Einf¨ uhrung`, `f¨ ur`, `Injektivit¨ at`, …),
    so the upstream-first fix did not work. See the "Verification outcome" section
    in [`17-bump-docling-verify-german-text.md`](17-bump-docling-verify-german-text.md).

[^18]: **LOAD-BEARING / required.** Because Docling 2.107.0 still emits decomposed
    umlauts (#17 FAIL), #18 performs the real repair downstream — e.g.
    `Injektivit¨ at` → `Injektivität` via `_DECOMPOSED_DIAERESIS_RE` /
    `normalize_text` in `math_ide/ingest/docling_adapter.py`. It is not
    redundant-but-harmless; without it the formal labels and concept names would
    slug from the decomposed text.
