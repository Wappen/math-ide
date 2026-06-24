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
    tmp_path: Path, monkeypatch
) -> None:
    """--wait runs stage 2 -> a 'ready' doc carrying semantic relations.

    With no API keys set the default ``auto`` resolver falls back to the
    offline mock (emitting a stderr warning), so this stays network-free.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = tmp_path / "doc.json"
    rc = ingest_cli.run([str(FIXTURE), "-o", str(out), "--wait"])
    assert rc == 0

    doc = _read_doc(out)
    assert doc["ingestion_state"] == "ready"
    assert any(r["origin"] == "semantic" for r in doc["relations"]), (
        "the resolver must add semantic relations"
    )


def test_ingest_wait_resolver_mock_writes_ready_doc(tmp_path: Path) -> None:
    """Pinning --resolver mock under --wait still produces a ready doc with
    semantic relations (the explicit, key-free path)."""
    out = tmp_path / "doc.json"
    rc = ingest_cli.run(
        [str(FIXTURE), "-o", str(out), "--wait", "--resolver", "mock"]
    )
    assert rc == 0

    doc = _read_doc(out)
    assert doc["ingestion_state"] == "ready"
    assert any(r["origin"] == "semantic" for r in doc["relations"])


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
    """The parser exposes the documented defaults.

    The parser-level ``--resolver`` default is now ``None`` (the effective name
    is computed in ``run()`` and depends on ``--wait``); ``--wait`` still
    defaults to ``False`` and ``--no-formula`` to ``False``.
    """
    args = ingest_cli.build_parser().parse_args([str(FIXTURE)])
    assert args.source == str(FIXTURE)
    assert args.wait is False
    assert args.resolver is None
    assert args.no_formula is False
    assert args.document_id is None


def test_effective_resolver_default_depends_on_wait() -> None:
    """With no explicit --resolver, --wait selects 'auto', else 'mock'."""
    assert ingest_cli._effective_resolver_name(None, wait=True) == "auto"
    assert ingest_cli._effective_resolver_name(None, wait=False) == "mock"


def test_effective_resolver_explicit_choice_wins() -> None:
    """An explicit --resolver always overrides the --wait-derived default."""
    assert ingest_cli._effective_resolver_name("openai", wait=True) == "openai"
    assert ingest_cli._effective_resolver_name("anthropic", wait=False) == (
        "anthropic"
    )
    assert ingest_cli._effective_resolver_name("mock", wait=True) == "mock"


def test_ingest_no_formula_parsing() -> None:
    """--no-formula parses to True when passed, False by default."""
    parser = ingest_cli.build_parser()
    assert parser.parse_args([str(FIXTURE)]).no_formula is False
    assert parser.parse_args([str(FIXTURE), "--no-formula"]).no_formula is True


def test_ingest_resolver_choices_include_openai_and_auto() -> None:
    """The new resolver choices are wired into the parser."""
    parser = ingest_cli.build_parser()
    # All four choices parse without error.
    for name in ("mock", "anthropic", "openai", "auto"):
        args = parser.parse_args([str(FIXTURE), "--resolver", name])
        assert args.resolver == name


def test_ingest_resolver_openai_fails_fast_without_key(monkeypatch) -> None:
    """--wait --resolver openai with no OPENAI_API_KEY fails fast (SystemExit),
    before any client construction or network call."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        ingest_cli.run([str(FIXTURE), "--wait", "--resolver", "openai"])
    assert excinfo.value.code == 2


def test_ingest_resolver_anthropic_fails_fast_without_key(monkeypatch) -> None:
    """--wait --resolver anthropic with no ANTHROPIC_API_KEY fails fast."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        ingest_cli.run([str(FIXTURE), "--wait", "--resolver", "anthropic"])
    assert excinfo.value.code == 2


# ---------------------------------------------------------------------------
# Fail-fast on a missing provider SDK for an EXPLICITLY pinned live resolver
# (issue #26). The lazy-import contract is preserved: the importability probe
# fires only for pinned anthropic/openai, never for mock/auto.
# ---------------------------------------------------------------------------


def _block_sdk(monkeypatch, module: str) -> None:
    """Make ``import <module>`` fail by shadowing it in ``sys.modules``.

    A ``None`` entry in ``sys.modules`` makes both ``import`` and
    ``importlib.util.find_spec`` report the module as unavailable, simulating an
    uninstalled SDK without actually uninstalling it from the test environment.
    """
    import sys

    monkeypatch.setitem(sys.modules, module, None)


def test_ingest_resolver_openai_fails_fast_when_sdk_missing(monkeypatch) -> None:
    """--resolver openai with OPENAI_API_KEY set but the openai SDK unimportable
    fails fast (exit 2) with a message naming the package — instead of building
    a resolver that degrades into a partial 'resolving' doc."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _block_sdk(monkeypatch, "openai")

    with pytest.raises(SystemExit) as excinfo:
        ingest_cli._make_resolver("openai")
    assert excinfo.value.code == 2


def test_ingest_resolver_openai_sdk_missing_message_names_package(
    monkeypatch, capsys
) -> None:
    """The missing-SDK fail-fast names the 'openai' package on stderr."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    _block_sdk(monkeypatch, "openai")

    with pytest.raises(SystemExit):
        ingest_cli._make_resolver("openai")
    err = capsys.readouterr().err
    assert "openai" in err
    assert "--resolver openai" in err


def test_ingest_resolver_anthropic_fails_fast_when_sdk_missing(
    monkeypatch,
) -> None:
    """--resolver anthropic with ANTHROPIC_API_KEY set but the anthropic SDK
    unimportable fails fast (exit 2) the same way as the openai case."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _block_sdk(monkeypatch, "anthropic")

    with pytest.raises(SystemExit) as excinfo:
        ingest_cli._make_resolver("anthropic")
    assert excinfo.value.code == 2


def test_ingest_resolver_anthropic_sdk_missing_message_names_package(
    monkeypatch, capsys
) -> None:
    """The missing-SDK fail-fast names the 'anthropic' package on stderr."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    _block_sdk(monkeypatch, "anthropic")

    with pytest.raises(SystemExit):
        ingest_cli._make_resolver("anthropic")
    err = capsys.readouterr().err
    assert "anthropic" in err
    assert "--resolver anthropic" in err


def test_ingest_resolver_mock_does_not_probe_sdks(monkeypatch) -> None:
    """mock never triggers the importability probe — even with BOTH SDKs absent
    it constructs a resolver offline (the lazy-import contract)."""
    _block_sdk(monkeypatch, "openai")
    _block_sdk(monkeypatch, "anthropic")

    resolver = ingest_cli._make_resolver("mock")
    from math_ide.ontology import MockResolver

    assert isinstance(resolver, MockResolver)


def test_ingest_resolver_auto_does_not_probe_sdks_without_keys(
    monkeypatch, capsys
) -> None:
    """auto with no keys and both SDKs absent must NOT hard-fail: it falls back
    to the offline MockResolver (preserving auto's documented semantics)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _block_sdk(monkeypatch, "openai")
    _block_sdk(monkeypatch, "anthropic")

    resolver = ingest_cli._make_resolver("auto")
    from math_ide.ontology import MockResolver

    assert isinstance(resolver, MockResolver)
    assert "MockResolver" in capsys.readouterr().err


def test_ingest_resolver_auto_does_not_probe_sdk_with_key(monkeypatch) -> None:
    """auto with a key set but the SELECTED SDK absent must NOT hard-fail in
    _make_resolver: auto constructs the live resolver lazily (no SDK probe), so
    construction stays offline and any failure is deferred to call time."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _block_sdk(monkeypatch, "openai")

    resolver = ingest_cli._make_resolver("auto")
    from math_ide.ontology import OpenAIResolver

    assert isinstance(resolver, OpenAIResolver)


def test_ingest_resolver_openai_constructs_when_sdk_present(monkeypatch) -> None:
    """With the openai SDK present and a key set, the pinned resolver builds
    normally (the fail-fast only fires when the SDK truly can't import)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")

    resolver = ingest_cli._make_resolver("openai")
    from math_ide.ontology import OpenAIResolver

    assert isinstance(resolver, OpenAIResolver)
