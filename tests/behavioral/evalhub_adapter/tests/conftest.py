"""Shared fixtures for evalhub_adapter tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point _FIXTURES_DIR to a temporary directory for YAML-based tests."""
    import evalhub_adapter.benchmarks as bm_module

    monkeypatch.setattr(bm_module, "_FIXTURES_DIR", tmp_path)
    return tmp_path
