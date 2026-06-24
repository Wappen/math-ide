# 0003 — Two-layer occurrence + concept ontology with staged LLM meaning resolution

Status: Accepted

## Context

Across a document the same mathematical object appears many times — `f`, `L`, `ε` recur in formulas, labels, and prose — and the IDE must connect each surface appearance to the object it denotes so that go-to-definition and show-references work. Some meaning is stated authoritatively in numbered definitions and theorems; the rest must be inferred from context and coreference, which is an LLM-shaped task that is slow, non-deterministic, and not always available. We need a representation that separates "where notation appears" from "what it means", lets structure be usable immediately, and never lets a guess overwrite a stated definition.

## Decision

The ontology has two layers. *Occurrences* are surface appearances of notation at a document location (formula symbol, defined name, or citation), each with its own render and source bbox, resolving to exactly one *concept*; concepts are the canonical objects that carry *formal meaning* and/or *inferred meaning*. Structure, occurrences, and deterministic citation links are produced synchronously at ingestion, while a staged async *meaning resolution* step runs an LLM (behind a `Resolver` interface with a deterministic `MockResolver` for tests) to assign occurrences to concepts and propagate inferred meaning. Formal meaning seeded by formal blocks is authoritative: the resolver may fill gaps and add inferred meaning and semantic relations, but it can never override formal meaning, and it flips touched concepts and occurrences from `pending` to `resolved`.

## Why

Splitting surface from meaning lets the renderer open at `structure_ready` with working occurrences, citations, and source provenance the instant ingestion finishes, while the expensive, fallible LLM work proceeds in the background and upgrades the document in place. Making formal meaning authoritative encodes the project's trust ordering — a numbered definition outranks an inference — directly in the resolution contract, and routing all LLM work through a `Resolver` protocol keeps the system testable offline and deterministic while leaving room for a real `AnthropicResolver` in production.

## Considered options

- **Single flat layer of meaning-bearing tokens** — rejected: conflates location with identity, cannot represent two occurrences denoting one concept, and has no clean seam for staged resolution.
- **Synchronous, LLM-required resolution at ingestion** — rejected: blocks the IDE on slow, non-deterministic, possibly-unavailable inference and makes tests non-hermetic.
- **Two-layer occurrence + concept ontology with staged async resolution and authoritative formal meaning** — chosen.
