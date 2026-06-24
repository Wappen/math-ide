# Architecture Decision Records

Each ADR records one hard-to-reverse design decision for the Math IDE in a short, fixed shape: **Context** (the forces and constraints at play), **Decision** (what we chose, stated as a directive), and **Why** (the rationale that makes the choice durable), with an optional **Considered options** list when the alternatives are illuminating. Each section is at most one paragraph; ADRs are append-only records of decisions already made, not living design docs, and they deliberately avoid duplicating the terminology owned by `CONTEXT.md`.

## Index

- [0001 — Structured re-render over PDF overlay](0001-structured-rerender.md): the Math IDE renders from the math document, not from PDF pages with hit-target overlays.
- [0002 — Custom math document schema with Docling as ingestion adapter](0002-math-document-schema.md): a project-owned math document is canonical; Docling is one replaceable ingestion source.
- [0003 — Two-layer occurrence + concept ontology with staged LLM meaning resolution](0003-occurrence-concept-ontology.md): occurrences index surface notation, concepts carry meaning, and an async LLM stage resolves the two without ever overriding formal meaning.
