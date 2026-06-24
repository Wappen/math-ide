"""``ingest`` subcommand: Docling JSON / PDF -> math-document JSON.

Accepts either a pre-converted Docling JSON dict (``*.json``) or a live source
(``*.pdf`` / URL). Live conversion goes through :mod:`docling_runner`, whose
Docling import is lazy, so the JSON path never needs Docling installed.

By default the command runs **stage 1 only** and returns a document at
``structure_ready`` — fast, deterministic, and immediately usable by the IDE
(citations + formal-block navigation already work). Pass ``--wait`` to also run
stage 2 (meaning resolution) to ``ready`` before writing output;
``--resolver {mock,anthropic,openai,auto}`` selects the resolver. The default
depends on ``--wait``: with ``--wait`` it is ``auto`` (which reads the
environment — ``ANTHROPIC_API_KEY`` -> Anthropic, else ``OPENAI_API_KEY`` ->
OpenAI, else the offline mock with a stderr warning); without ``--wait`` it is
``mock``. The ``anthropic`` / ``openai`` SDKs are imported lazily, only when a
live resolver actually calls the API.

On the live PDF path, Docling formula enrichment (LaTeX) is **on by default**;
pass ``--no-formula`` to opt out.

Output is the :class:`MathDocument` serialized via ``model_dump_json(indent=2)``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

__all__ = ["run", "build_parser"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="math_ide ingest",
        description="Ingest a Docling JSON dict or a PDF into a math document.",
    )
    parser.add_argument(
        "source",
        help="Path to a Docling JSON file (.json) OR a PDF path/URL.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write the math document JSON here instead of stdout.",
    )
    parser.add_argument(
        "--document-id",
        dest="document_id",
        default=None,
        help="Override the derived document id (used to namespace all ids).",
    )
    parser.add_argument(
        "--no-formula",
        action="store_true",
        dest="no_formula",
        default=False,
        help=(
            "Disable Docling formula enrichment (LaTeX) on the live PDF path. "
            "Enrichment is ON by default; pass this to opt out."
        ),
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Enable OCR on the live PDF path (slower).",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help=(
            "Run stage 2 (meaning resolution) to 'ready' before writing. "
            "Default is stage 1 only ('structure_ready', fast)."
        ),
    )
    parser.add_argument(
        "--resolver",
        choices=("mock", "anthropic", "openai", "auto"),
        default=None,
        help=(
            "Stage-2 resolver used with --wait. The default depends on --wait: "
            "'auto' when --wait is passed, else 'mock'. 'auto' reads the "
            "environment (ANTHROPIC_API_KEY -> anthropic, else OPENAI_API_KEY "
            "-> openai, else mock). 'anthropic' reads ANTHROPIC_API_KEY; "
            "'openai' reads OPENAI_API_KEY."
        ),
    )
    return parser


def _effective_resolver_name(resolver: str | None, wait: bool) -> str:
    """Resolve the effective resolver name from the parsed args.

    The CLI default is ``None`` so it can depend on ``--wait``: with ``--wait``
    the default is ``"auto"`` (environment-driven), otherwise ``"mock"``. An
    explicit ``--resolver`` always wins.
    """
    return resolver or ("auto" if wait else "mock")


def _require_sdk(provider: str, module: str) -> None:
    """Fail fast (exit code 2) if a pinned live resolver's SDK is missing.

    The live resolvers import their provider SDK lazily inside ``_complete``, so
    a missing package would otherwise surface only as a swallowed retry inside
    ``resolve_via_completion`` (partial doc, ``ingestion_state="resolving"``,
    exit 0). When a provider is *explicitly* pinned we instead probe the import
    up front and, if it is unavailable, write a clear message naming the missing
    package and ``raise SystemExit(2)`` — mirroring the API-key check. This runs
    ONLY for the explicitly pinned ``anthropic`` / ``openai`` resolvers, never
    for ``mock`` / ``auto``, so the lazy-import contract (offline suite, ``auto``
    fallback with no SDK) stays intact.
    """
    import importlib.util

    try:
        found = importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        # A ``None`` entry in ``sys.modules`` (a shadowed/blocked import) makes
        # ``find_spec`` raise; treat that as "not importable" too.
        found = False
    if not found:
        sys.stderr.write(
            f"error: --resolver {provider} requires the '{module}' package, "
            f"which is not installed. Install it with: pip install '{module}'.\n"
        )
        raise SystemExit(2)


def _make_resolver(name: str):
    """Construct the requested resolver, importing live SDKs only on demand.

    ``mock`` / ``auto`` never need a key (``auto`` falls back to the mock with a
    stderr warning). ``anthropic`` / ``openai`` **fail fast** (exit code 2) if
    their API key is absent OR their provider SDK is not importable, before any
    client is constructed, so an unkeyed request never silently hits the network
    and a missing SDK never silently degrades to a partial ``resolving`` doc. The
    live resolvers import their SDKs lazily inside ``_complete``, so construction
    here stays offline; the SDK importability probe runs only for the explicitly
    pinned live resolvers (never ``mock`` / ``auto``).
    """
    if name == "anthropic":
        import os

        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.stderr.write(
                "error: --resolver anthropic requires ANTHROPIC_API_KEY to be "
                "set.\n"
            )
            raise SystemExit(2)
        _require_sdk("anthropic", "anthropic")
        from math_ide.ontology import AnthropicResolver

        return AnthropicResolver()
    if name == "openai":
        import os

        if not os.environ.get("OPENAI_API_KEY"):
            sys.stderr.write(
                "error: --resolver openai requires OPENAI_API_KEY to be set.\n"
            )
            raise SystemExit(2)
        _require_sdk("openai", "openai")
        from math_ide.ontology import OpenAIResolver

        return OpenAIResolver()
    if name == "auto":
        from math_ide.ontology import auto_resolver

        return auto_resolver()
    from math_ide.ontology import MockResolver

    return MockResolver()


def _load_docling_dict(source: str, *, ocr: bool, formula: bool) -> dict[str, Any]:
    """Return a Docling dict from ``source``.

    A ``.json`` path is read directly; anything else (``.pdf`` / URL) is
    converted live via the lazily-imported Docling runner.
    """
    is_url = source.startswith(("http://", "https://"))
    if not is_url and source.lower().endswith(".json"):
        return json.loads(Path(source).read_text(encoding="utf-8"))

    from math_ide.ingest.docling_runner import run_docling

    return run_docling(source, ocr=ocr, formula=formula)


def run(argv: list[str]) -> int:
    """Entry point for ``python -m math_ide ingest <args>``.

    Fast by default: runs the staged pipeline to ``structure_ready`` and writes
    that. With ``--wait`` it also runs stage 2 before writing; the resolver is
    the ``--resolver``-selected one, defaulting to ``auto`` under ``--wait`` and
    ``mock`` otherwise (see :func:`_effective_resolver_name`).
    """
    from math_ide.env import load_env

    load_env()

    args = build_parser().parse_args(argv)

    # Lazy import keeps the dispatcher cheap and avoids a cycle at module load.
    from math_ide.pipeline import ingest_structure, run_full

    docling = _load_docling_dict(
        args.source, ocr=args.ocr, formula=not args.no_formula
    )
    doc = ingest_structure(docling, document_id=args.document_id)
    if args.wait:
        resolver_name = _effective_resolver_name(args.resolver, args.wait)
        resolver = _make_resolver(resolver_name)
        doc = run_full(doc, resolver=resolver, wait=True)
    payload = doc.model_dump_json(indent=2)

    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
        if not payload.endswith("\n"):
            sys.stdout.write("\n")
    return 0
