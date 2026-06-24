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

[^17]: The Docling floor was bumped to `>=2.7.0`, but the umlaut re-verification
    could not be run in the offline dev environment (Docling not installed,
    `example.pdf` gitignored), so the upstream fix is **inconclusive** here. See
    the "Verification outcome" section in
    [`17-bump-docling-verify-german-text.md`](17-bump-docling-verify-german-text.md).

[^18]: **ACTIVE / proceeding.** Because #17 could not verify the upstream fix in
    this environment, its gate falls through to the deterministic fallback, so
    #18 is in effect (not merely blocked-by-17). It is a no-op on already-correct
    text, so it stays harmless if a real-hardware Docling bump later fixes umlauts
    upstream.
