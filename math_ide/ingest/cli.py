"""``ingest`` subcommand: Docling JSON / PDF -> math-document JSON.

Accepts either a pre-converted Docling JSON dict (``*.json``) or a live source
(``*.pdf`` / URL). Live conversion goes through :mod:`docling_runner`, whose
Docling import is lazy, so the JSON path never needs Docling installed.

By default the command runs **stage 1 only** and returns a document at
``structure_ready`` — fast, deterministic, and immediately usable by the IDE
(citations + formal-block navigation already work). Pass ``--wait`` to also run
stage 2 (meaning resolution) to ``ready`` before writing output;
``--resolver mock|anthropic`` selects the resolver (the Anthropic SDK is
imported lazily, only when ``--resolver anthropic --wait`` is used).

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
        "--formula",
        action="store_true",
        help="Enable Docling formula enrichment (LaTeX) on the live PDF path.",
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
        choices=("mock", "anthropic"),
        default="mock",
        help=(
            "Stage-2 resolver used with --wait (default: mock). "
            "'anthropic' calls the API and reads ANTHROPIC_API_KEY."
        ),
    )
    return parser


def _make_resolver(name: str):
    """Construct the requested resolver, importing Anthropic only on demand."""
    if name == "anthropic":
        from math_ide.ontology import AnthropicResolver

        return AnthropicResolver()
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
    that. With ``--wait`` it also runs stage 2 (the ``--resolver``-selected
    resolver, default ``mock``) to ``ready`` before writing.
    """
    args = build_parser().parse_args(argv)

    # Lazy import keeps the dispatcher cheap and avoids a cycle at module load.
    from math_ide.pipeline import ingest_structure, run_full

    docling = _load_docling_dict(args.source, ocr=args.ocr, formula=args.formula)
    doc = ingest_structure(docling, document_id=args.document_id)
    if args.wait:
        resolver = _make_resolver(args.resolver)
        doc = run_full(doc, resolver=resolver, wait=True)
    payload = doc.model_dump_json(indent=2)

    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
        if not payload.endswith("\n"):
            sys.stdout.write("\n")
    return 0
