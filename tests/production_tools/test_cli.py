"""Trusted CLI uses the same native compiler with a real one-row capture bound."""

import importlib.util
import json
from pathlib import Path

import pytest

from manufacturing_platform.production_tools.contracts import ProductionToolsConfig

from .test_queries import binding
from .test_source import row, source


def cli():
    path = Path(__file__).parents[2] / "scripts/verify_production_tools.py"
    spec = importlib.util.spec_from_file_location("verify_production_tools", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_default_caps_native_select_and_prints_only_summary(tmp_path, capsys):
    module = cli()
    src = source([row(id=5, secret="NEVER PRINT"), row(id=4)])
    scope = binding()
    config = ProductionToolsConfig(
        src, {scope.project_id: scope}, str(tmp_path / "snapshot.db")
    )
    module.build_native_config = lambda *args: config
    code = module.main(
        [
            "--config",
            str(tmp_path / "private.json"),
            "--dataset-id",
            scope.dataset_id,
            "--project",
            str(scope.project_id),
            "--transport",
            "mysql",
        ]
    )
    output = json.loads(capsys.readouterr().out)
    assert code == 0 and src.mysql.calls[0].max_rows == 2
    assert output["row_count"] == 1 and output["complete"] is False
    assert set(output) == {
        "transport",
        "query_kind",
        "success",
        "elapsed_ms",
        "row_count",
        "complete",
        "error_code",
    }
    assert "NEVER" not in str(output)


def test_cli_oss_requires_verified_log_id_before_config_or_io(capsys):
    module = cli()
    module.build_native_config = lambda *args: pytest.fail("must not open config")
    with pytest.raises(SystemExit):
        module.main(
            [
                "--config",
                "/private.json",
                "--dataset-id",
                "test",
                "--project",
                str(binding().project_id),
                "--transport",
                "oss",
            ]
        )


def test_cli_sanitizes_source_errors(tmp_path, capsys):
    module = cli()

    def fail(*args):
        raise RuntimeError("SECRET URL password")

    module.build_native_config = fail
    assert (
        module.main(
            [
                "--config",
                "/private.json",
                "--dataset-id",
                "test",
                "--project",
                str(binding().project_id),
                "--transport",
                "mysql",
            ]
        )
        == 1
    )
    output = capsys.readouterr().out
    assert json.loads(output)["error_code"] == "VERIFICATION_UNAVAILABLE"
    assert "SECRET" not in output
