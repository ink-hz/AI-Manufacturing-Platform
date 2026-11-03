import pytest

from .support import MockRig


@pytest.fixture
def rig(tmp_path):
    return MockRig(tmp_path)


@pytest.fixture
def production_rig(tmp_path):
    return MockRig(tmp_path, mode="production")


@pytest.fixture
def network_rig(tmp_path):
    value = MockRig(tmp_path, network=True)
    value.grant(
        [
            "project_owner",
            "engineering",
            "planner",
            "quality",
            "production",
            "supply",
            "warehouse",
        ],
        ["inspection", "disposition", "quality_release", "readiness_verification"],
    )
    return value
