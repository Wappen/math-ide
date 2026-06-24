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
