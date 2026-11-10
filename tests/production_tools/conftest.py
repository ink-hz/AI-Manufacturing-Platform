"""Reuse the trusted workflow harness without changing its default behavior."""

import importlib.util
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "production_workflow_harness",
    Path(__file__).parents[1] / "workflow" / "conftest.py",
)
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)


@pytest.fixture
def workflow(tmp_path):
    harness = _module.WorkflowHarness(tmp_path)
    yield harness
    harness._client.close()
