---
title: OpenAI resolver and auto LLM provider selection
labels: ontology, llm
---

## Summary

Add an `OpenAIResolver`, an `auto` resolver that picks a live provider from environment keys, and shared module-level functions for the common LLM meaning-resolution logic. Make `auto` the default when `--wait` is passed.

## Context

Today only `MockResolver` and `AnthropicResolver` exist. The CLI offers `--resolver mock|anthropic` (default `mock`). Users without `ANTHROPIC_API_KEY` cannot run live meaning resolution without code changes.

**Decisions from design review:**

- `--wait` defaults to `auto`: try `ANTHROPIC_API_KEY` → `OPENAI_API_KEY` → `mock` with a **stderr warning**
- `--resolver anthropic` / `--resolver openai` pin a provider and **fail fast** if that key is missing (no silent fallback)
- `--resolver mock` forces offline resolution
- `OpenAIResolver` default model: `gpt-4o`; overridable via `OPENAI_MODEL` env or constructor arg
- Refactor: extract shared `build_prompt`, `parse_response`, and the retry/`MeaningDelta.apply` loop as **module-level functions** in `meaning.py`; keep thin `AnthropicResolver` and `OpenAIResolver` classes that only differ in `_complete()`

Blocked by: **#9**.

## Scope

- Shared functions in `math_ide/ontology/meaning.py` used by both live resolvers
- `OpenAIResolver` implementing the existing `Resolver` protocol (lazy `openai` SDK import)
- `resolve_auto_resolver()` or equivalent factory: Anthropic → OpenAI → mock + warning
- CLI: extend `--resolver` choices to `mock|anthropic|openai|auto`; default `auto` when `--wait`, else `mock`
- Add `openai` to `requirements.txt` (lazy import; same pattern as `anthropic`)
- Unit tests with stubbed OpenAI client (mirror `test_meaning.py` Anthropic stubs)
- Optional: gated live test module `tests/test_acceptance_llm_openai.py` (`RUN_LLM_TESTS=1` + `OPENAI_API_KEY`)
- Update `docs/ontology.md`, `README.md`, `docs/pipeline.md`

## Acceptance criteria

- [ ] `OpenAIResolver` satisfies the `Resolver` protocol; default model `gpt-4o`
- [ ] `auto` with `OPENAI_API_KEY` only uses OpenAI; with both keys prefers Anthropic
- [ ] `auto` with no keys prints a stderr warning and uses `MockResolver`
- [ ] `--resolver anthropic` without `ANTHROPIC_API_KEY` fails fast (clear error, no silent OpenAI fallback)
- [ ] `--resolver openai` without `OPENAI_API_KEY` fails fast
- [ ] Shared prompt/parse/retry logic is not duplicated between Anthropic and OpenAI resolvers
- [ ] Offline test suite passes without `openai` installed (lazy import)

## Out of scope

- Additional providers (Gemini, local models)
- Changing the meaning-resolution prompt or JSON schema
- Making `--wait` implicit without a flag (users must still pass `--wait` for stage 2)
