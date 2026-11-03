import pytest

from .support import MockRig


@pytest.fixture
def rig(tmp_path):
    return MockRig(tmp_path)


@pytest.fixture
def production_rig(tmp_path):
    return MockRig(tmp_path, mode="production")
