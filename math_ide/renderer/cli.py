"""CLI for the renderer: render a math document to HTML, and serve it.

``run(argv)`` reads a :class:`~math_ide.schema.MathDocument` JSON file and
writes a standalone HTML page. ``serve(argv)`` renders the same and starts a
stdlib HTTP server exposing the page plus the ``assets/`` directory (so KaTeX,
``styles.css`` and ``app.js`` resolve).

Both follow the project CLI style (stdlib ``argparse``, lazy/minimal imports).
"""

from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import sys
import tempfile
from pathlib import Path
from typing import Optional, Sequence

from math_ide.renderer.render import render_document
from math_ide.schema import MathDocument

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def _load_document(path: Path) -> MathDocument:
    """Load and validate a MathDocument from a JSON file."""
    return MathDocument.model_validate_json(path.read_text(encoding="utf-8"))


def _build_run_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="math-ide render",
        description="Render a math document JSON file to a standalone HTML page.",
    )
    parser.add_argument(
        "document",
        type=Path,
        help="Path to a MathDocument JSON file.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write HTML here instead of stdout.",
    )
    return parser


def run(argv: Optional[Sequence[str]] = None) -> int:
    """Render a MathDocument JSON file to HTML (``-o`` file, else stdout)."""
    args = _build_run_parser().parse_args(argv)
    doc = _load_document(args.document)
    html = render_document(doc)
    if args.output is not None:
        args.output.write_text(html, encoding="utf-8")
    else:
        sys.stdout.write(html)
    return 0


def _build_serve_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="math-ide serve",
        description="Render a math document and serve it over HTTP with assets.",
    )
    parser.add_argument(
        "document",
        type=Path,
        help="Path to a MathDocument JSON file.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Interface to bind (default: 127.0.0.1).",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=8000,
        help="Port to listen on (default: 8000).",
    )
    return parser


def _prepare_site(doc: MathDocument, root: Path) -> None:
    """Materialise the rendered page + assets under ``root`` for serving."""
    (root / "index.html").write_text(render_document(doc), encoding="utf-8")
    assets_link = root / "assets"
    # Symlink when possible, else point the handler at a copy-free directory.
    try:
        assets_link.symlink_to(_ASSETS_DIR, target_is_directory=True)
    except (OSError, NotImplementedError):
        import shutil

        shutil.copytree(_ASSETS_DIR, assets_link, dirs_exist_ok=True)


def serve(argv: Optional[Sequence[str]] = None) -> int:
    """Render the document and serve it (plus assets) over HTTP."""
    args = _build_serve_parser().parse_args(argv)
    doc = _load_document(args.document)

    site = Path(tempfile.mkdtemp(prefix="math-ide-site-"))
    _prepare_site(doc, site)

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(site)
    )

    class _Server(socketserver.TCPServer):
        allow_reuse_address = True

    with _Server((args.host, args.port), handler) as httpd:
        url = f"http://{args.host}:{args.port}/"
        print(f"Serving rendered document at {url} (Ctrl-C to stop)", file=sys.stderr)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
