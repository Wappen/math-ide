---
title: openai core dependency absent; --resolver openai degrades silently
labels: llm
---

## Summary

`README.md` and `requirements.txt` advertise `openai>=1.0` as a core dependency, but `openai` is not importable in the committed `.venv` (only `anthropic` is installed). Because the SDK is imported lazily inside `OpenAIResolver._complete` and `resolve_via_completion` swallows the import error as a retryable failure, pinning `--resolver openai --wait` with `OPENAI_API_KEY` set but the package missing produces an unresolved document at `ingestion_state="resolving"` and exits 0 — no clear error. Make the environment match the docs (install `openai` or reclassify it as an optional extra) and, when a live resolver is explicitly pinned, fail fast if its SDK cannot be imported.

## Context

This was confirmed by a real run against the committed virtualenv. `.venv/bin/python -c 'import openai'` raises `ModuleNotFoundError: No module named 'openai'`, while `import anthropic` succeeds (`anthropic 0.111.0`). Yet `requirements.txt` lists `openai>=1.0` and `README.md` line 95 literally reads "Both SDKs are already core dependencies."

Reproducing the documented "pin a provider explicitly" recipe with `OPENAI_API_KEY=sk-fake` set, `ANTHROPIC_API_KEY` cleared, and the package absent:

```
$ python -m math_ide ingest tests/fixtures/example_docling.json --wait --resolver openai -o out.json
resolve attempt 1/3 failed: No module named 'openai'
resolve attempt 2/3 failed: No module named 'openai'
resolve attempt 3/3 failed: No module named 'openai'
resolve exhausted 3 attempts; returning partial doc (No module named 'openai')
$ echo $?
0
```

The written document is left at `"ingestion_state": "resolving"` with **0** `origin="semantic"` relations and **10** concepts still `pending`. The only **3** concepts marked `resolved` are the formally-defined `Menge` / `Injektivitaet` / `Konvergenz`, which were already resolved at seed time — the failed resolver contributed nothing (no coreference, no inferred meaning, no semantic relation).

Two source seams produce the silent degradation:

- `math_ide/ingest/cli.py` `_make_resolver("openai")` (lines 125–135) guards only on `os.environ.get("OPENAI_API_KEY")`; a present key bypasses the sole fail-fast check, and the `openai` import never happens here because the SDK is imported lazily inside `_complete`.
- `math_ide/ontology/meaning.py` `resolve_via_completion` (lines 500–542) catches `except Exception` per attempt, logs three `warning`s plus one `error`, and returns the partial document. Its closing comment is explicit: `# PARTIAL: state stays "resolving", no exception propagated.` The `ModuleNotFoundError` from `OpenAIResolver._complete` (`import openai`, line 700) is caught by exactly this path.

The README's "fail fast (exit code 2)" promise (line 120) is scoped to a missing API **key**, not a missing **SDK** — so this is not a broken promise but a gap: no check covers the missing-package case. The degradation is silent at the exit-code level (exit 0, document written), even though stderr emits retry warnings and the non-`ready` `ingestion_state` is detectable downstream. This is the `--resolver openai` path added in **#19** (which also added `openai` to `requirements.txt`); the lazy-import contract is the one documented in `meaning.py` and exercised by **#9**. The synthetic fixture `tests/fixtures/example_docling.json` does not exercise this because the offline test suite uses `MockResolver` and the live OpenAI path is gated behind `RUN_LLM_TESTS=1` + a real key, so no test installs or imports `openai`.

## Scope

- Decide whether `openai` is core or optional and make `README.md` / `requirements.txt` internally consistent: either install `openai>=1.0` into the environment so it matches the "core dependency" wording, or move it to an optional extra and correct the README line 95 wording and the `auto_resolver` / `--resolver` documentation accordingly.
- In `math_ide/ingest/cli.py` `_make_resolver`, when a live resolver is explicitly pinned (`anthropic` / `openai`), verify the provider SDK is importable in addition to the API-key check, and `raise SystemExit(2)` with a clear message (mirroring the existing key-missing branch) instead of constructing a resolver that will degrade inside `resolve_via_completion`.
- Keep the lazy-import contract from **#9**/**#19** intact for the offline path: the importability probe must run only for the explicitly pinned live resolvers in `_make_resolver`, not at module import and not for `mock` / `auto`.

## Acceptance criteria

- [ ] `--resolver openai --wait` with `OPENAI_API_KEY` set but the `openai` package not installed exits non-zero (2) with a clear stderr message naming the missing SDK, and writes no `resolving`-state document.
- [ ] `--resolver anthropic --wait` with `ANTHROPIC_API_KEY` set but the `anthropic` package not installed fails the same way.
- [ ] After the dependency decision, `python -c 'import openai'` succeeds in the project environment **or** `README.md` and `requirements.txt` consistently describe `openai` as an optional extra (no remaining "Both SDKs are already core dependencies" claim that contradicts the environment).
- [ ] The offline test suite still passes without `openai` installed (the importability check does not fire for `mock` / `auto`, preserving the lazy-import contract).

## Out of scope

- Changing the `auto` resolver fallback semantics (auto with no keys still warns and uses `MockResolver`; auto must not start hard-failing on a missing SDK).
- Changing `resolve_via_completion`'s partial-result tolerance for genuine API/parse failures at runtime (a transient network error must still return a partial document rather than crash).
- Adding new providers or changing the resolution prompt/JSON schema.
