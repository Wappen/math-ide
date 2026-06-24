"""``python -m math_ide`` subcommand dispatcher.

Maps each subcommand to a ``"module:function"`` target imported LAZILY, so a
missing sibling module (e.g. the renderer, authored in a parallel wave) never
breaks an unrelated subcommand. Each target ``func(argv)`` parses its own
remaining ``sys.argv[2:]`` and returns an exit code.
"""

from __future__ import annotations

import importlib
import sys
from typing import Callable

SUBCOMMANDS: dict[str, str] = {
    "ingest": "math_ide.ingest.cli:run",
    "render": "math_ide.renderer.cli:run",
    "serve": "math_ide.renderer.cli:serve",
}


def _resolve(target: str) -> Callable[[list[str]], int]:
    module_name, func_name = target.split(":", 1)
    module = importlib.import_module(module_name)  # lazy: per-subcommand only
    return getattr(module, func_name)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        _print_usage()
        return 0 if argv else 1

    name = argv[0]
    target = SUBCOMMANDS.get(name)
    if target is None:
        sys.stderr.write(f"Unknown subcommand: {name}\n")
        _print_usage()
        return 2

    try:
        func = _resolve(target)
    except ImportError as exc:
        sys.stderr.write(
            f"Subcommand '{name}' is unavailable: {exc}\n"
            "(its module may not be built yet).\n"
        )
        return 2

    return func(sys.argv[2:])


def _print_usage() -> None:
    sys.stderr.write(
        "usage: python -m math_ide <subcommand> [args]\n"
        "subcommands: " + ", ".join(SUBCOMMANDS) + "\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
