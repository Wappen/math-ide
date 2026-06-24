"""Tests for the command-line surface (issue #14 coverage).

Covers the two zero-coverage CLI modules, fully offline:

* :mod:`math_ide.__main__` — the subcommand *dispatcher*: usage/exit codes,
  unknown subcommands, and the lazy per-subcommand import (a target whose module
  is missing fails cleanly with exit code 2 rather than crashing the process).
* :mod:`math_ide.ingest.cli` — the ``ingest`` ``run()``: the ``.json`` fast path
  (no Docling, no network) producing a ``structure_ready`` document by default,
  a ``ready`` document with semantic relations under ``--wait``, and id
  namespacing via ``--document-id``.

All tests drive ``run()`` / ``main()`` with explicit ``argv`` lists (no
subprocess) and never touch the network or the heavy ``docling`` dependency:
the canonical fixture ``tests/fixtures/example_docling.json`` exercises the same
adapter code path a live conversion would feed in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from math_ide import __main__ as dispatcher
from math_ide.ingest import cli as ingest_cli

FIXTURE = Path(__file__).parent / "fixtures" / "example_docling.json"


# ---------------------------------------------------------------------------
# Dispatcher: math_ide.__main__.main
# ---------------------------------------------------------------------------


def test_dispatcher_no_args_prints_usage_and_returns_1(capsys) -> None:
    rc = dispatcher.main([])
    assert rc == 1
    err = capsys.readouterr().err
    assert "usage: python -m math_ide" in err
    # Every wired subcommand is advertised.
    for name in ("ingest", "render", "serve"):
        assert name in err


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_dispatcher_help_returns_0(flag: str, capsys) -> None:
    rc = dispatcher.main([flag])
    assert rc == 0
    assert "usage: python -m math_ide" in capsys.readouterr().err


def test_dispatcher_unknown_subcommand_returns_2(capsys) -> None:
    rc = dispatcher.main(["definitely-not-a-subcommand"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "Unknown subcommand: definitely-not-a-subcommand" in err
    assert "usage: python -m math_ide" in err


def test_dispatcher_lazy_import_of_missing_target_fails_cleanly(
    monkeypatch, capsys
) -> None:
    """A subcommand whose ``module:function`` target cannot be imported is
    reported cleanly (exit 2) instead of letting the ImportError escape — the
    lazy-per-subcommand contract that keeps an unbuilt sibling from breaking the
    others."""
    monkeypatch.setitem(
        dispatcher.SUBCOMMANDS,
        "ghost",
        "math_ide.ingest._does_not_exist:run",
    )
    rc = dispatcher.main(["ghost"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "Subcommand 'ghost' is unavailable" in err


def test_dispatcher_resolves_a_real_target() -> None:
    """The lazy resolver returns the actual callable for a wired subcommand."""
    func = dispatcher._resolve(dispatcher.SUBCOMMANDS["ingest"])
    assert func is ingest_cli.run


# ---------------------------------------------------------------------------
# ingest CLI: math_ide.ingest.cli.run (the .json fast path)
# ---------------------------------------------------------------------------


def _read_doc(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_ingest_default_writes_structure_ready_doc(tmp_path: Path) -> None:
    """Default (no --wait): stage 1 only -> a structure_ready math-doc JSON with
    occurrences + seeded concepts and NO semantic relations (no LLM ran)."""
    out = tmp_path / "doc.json"
    rc = ingest_cli.run([str(FIXTURE), "-o", str(out)])
    assert rc == 0

    doc = _read_doc(out)
    assert doc["ingestion_state"] == "structure_ready"
    assert doc["occurrences"], "stage 1 must produce occurrences"
    assert doc["concepts"], "stage 1 must seed concepts"
    # No resolver ran: only structural relations exist.
    assert doc["relations"]
    assert all(r["origin"] == "structural" for r in doc["relations"])
    assert not any(r["origin"] == "semantic" for r in doc["relations"])


def test_ingest_wait_writes_ready_doc_with_semantic_relations(
    tmp_path: Path,
) -> None:
    """--wait runs stage 2 (default mock resolver) -> a 'ready' doc carrying
    semantic relations."""
    out = tmp_path / "doc.json"
    rc = ingest_cli.run([str(FIXTURE), "-o", str(out), "--wait"])
    assert rc == 0

    doc = _read_doc(out)
    assert doc["ingestion_state"] == "ready"
    assert any(r["origin"] == "semantic" for r in doc["relations"]), (
        "the mock resolver must add semantic relations"
    )


def test_ingest_document_id_namespaces_all_ids(tmp_path: Path) -> None:
    """--document-id overrides the derived id and namespaces every minted id."""
    out = tmp_path / "doc.json"
    rc = ingest_cli.run(
        [str(FIXTURE), "-o", str(out), "--document-id", "custom-doc"]
    )
    assert rc == 0

    doc = _read_doc(out)
    assert doc["document_id"] == "custom-doc"
    # Blocks, concepts and occurrences are all minted under the namespace.
    for block in doc["blocks"]:
        assert block["id"].startswith("custom-doc#")
    for concept in doc["concepts"]:
        assert concept["id"].startswith("custom-doc#")
    for occ in doc["occurrences"]:
        assert occ["id"].startswith("custom-doc#")


def test_ingest_writes_to_stdout_when_no_output(capsys) -> None:
    """Without -o the document JSON is written to stdout (and is valid JSON)."""
    rc = ingest_cli.run([str(FIXTURE)])
    assert rc == 0
    out = capsys.readouterr().out
    doc = json.loads(out)  # must be parseable JSON
    assert doc["ingestion_state"] == "structure_ready"
    assert out.endswith("\n")  # newline-terminated for shell friendliness


def test_ingest_output_round_trips_through_schema(tmp_path: Path) -> None:
    """The written document validates against the canonical schema."""
    from math_ide.schema import MathDocument

    out = tmp_path / "doc.json"
    ingest_cli.run([str(FIXTURE), "-o", str(out)])
    MathDocument.model_validate(_read_doc(out))


def test_ingest_build_parser_defaults() -> None:
    """The parser exposes the documented defaults (mock resolver, no --wait)."""
    args = ingest_cli.build_parser().parse_args([str(FIXTURE)])
    assert args.source == str(FIXTURE)
    assert args.wait is False
    assert args.resolver == "mock"
    assert args.document_id is None
