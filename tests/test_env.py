"""Tests for :mod:`math_ide.env` — ``.env`` file loading."""

from __future__ import annotations

import os

import pytest

from math_ide.env import load_env


def test_load_env_reads_file(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert load_env(dotenv_path=env_file) is True
    assert os.environ["ANTHROPIC_API_KEY"] == "from-dotenv"


def test_load_env_does_not_override_existing(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-shell")

    assert load_env(dotenv_path=env_file) is True
    assert os.environ["ANTHROPIC_API_KEY"] == "from-shell"


def test_load_env_missing_file_returns_false(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    missing = tmp_path / "no-such.env"
    assert load_env(dotenv_path=missing) is False
    assert "ANTHROPIC_API_KEY" not in os.environ
