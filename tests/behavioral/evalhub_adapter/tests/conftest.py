"""Shared fixtures for evalhub_adapter tests."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: ensure ``evalhub`` is importable even when the real package is
# not installed.  ``evalhub_adapter.adapter`` performs a top-level
# ``from evalhub.adapter import ...``, which is triggered transitively when
# Python initialises the ``evalhub_adapter`` package.  Seeding sys.modules
# with a lightweight stub lets the rest of the test suite import cleanly.
#
# This MUST live in conftest.py (not a test module) so it runs before any
# test file imports ``evalhub_adapter.*``, regardless of which files are
# selected or collection order.
# ---------------------------------------------------------------------------
if "evalhub" not in sys.modules:
    _need_stub = True
    try:
        import importlib.util

        _need_stub = importlib.util.find_spec("evalhub") is None
    except (ImportError, ValueError):
        pass

    if _need_stub:  # pragma: no cover – only when evalhub truly absent
        from dataclasses import dataclass, field
        from typing import Any as _Any

        _eh = ModuleType("evalhub")
        _eh_adapter = ModuleType("evalhub.adapter")

        @dataclass
        class _EvaluationResult:
            metric_name: str
            metric_value: float
            metric_type: str
            num_samples: int
            metadata: dict[str, _Any] = field(default_factory=dict)

        for _name in (
            "DefaultCallbacks", "ErrorInfo", "FrameworkAdapter",
            "JobCallbacks", "JobPhase", "JobResults", "JobSpec",
            "JobStatus", "JobStatusUpdate", "MessageInfo",
        ):
            setattr(_eh_adapter, _name, MagicMock())

        _eh_adapter.EvaluationResult = _EvaluationResult  # type: ignore[attr-defined]
        _eh.adapter = _eh_adapter  # type: ignore[attr-defined]
        sys.modules.setdefault("evalhub", _eh)
        sys.modules.setdefault("evalhub.adapter", _eh_adapter)


@pytest.fixture
def fixtures_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point _FIXTURES_DIR to a temporary directory for YAML-based tests."""
    import evalhub_adapter.benchmarks as bm_module

    monkeypatch.setattr(bm_module, "_FIXTURES_DIR", tmp_path)
    return tmp_path
