"""A release must load under PF's private namespace, without a canonical install."""

import subprocess
import sys
from pathlib import Path


def test_release_loads_without_canonical_package_on_pythonpath(tmp_path):
    package = Path(__file__).resolve().parents[2] / "src" / "manufacturing_platform"
    script = """
import importlib.util, sys
from pathlib import Path
package = Path(sys.argv[1])
name = '_platform_manufacturing_isolated_test'
spec = importlib.util.spec_from_file_location(name, package / '__init__.py', submodule_search_locations=[str(package)])
module = importlib.util.module_from_spec(spec)
sys.modules[name] = module
spec.loader.exec_module(module)
assert module.WORKFLOW_API_VERSION == 1
assert callable(module.build_router)
assert callable(module.build_workflow_router)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(package)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
