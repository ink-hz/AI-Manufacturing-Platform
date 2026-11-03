"""Reviewed bind-option mapping for baseline replay.

The runtime-dashboard platform overlay added a production bind with
``propagation: rprivate``; the previous mapper failed closed on any bind
option beyond ``create_host_path``. These tests pin the narrow extension:
``rprivate`` (the engine default, byte-identical effective semantics) maps
into the HostConfig mount spec and is compared, every other propagation or
option combination still fails closed, and the create_host_path shorthand is
unchanged.
"""

import pytest

from release_support import bind_mount_spec


def test_plain_bind_maps_to_mount_spec():
    assert bind_mount_spec({}, "/src", "/dst", False) == {
        "Type": "bind",
        "Source": "/src",
        "Target": "/dst",
        "BindOptions": {},
    }


def test_readonly_bind_sets_readonly():
    spec = bind_mount_spec({}, "/src", "/dst", True)
    assert spec["ReadOnly"] is True and spec["BindOptions"] == {}


def test_create_host_path_uses_binds_entry():
    assert bind_mount_spec({"create_host_path": True}, "/s", "/d", False) is None


def test_create_host_path_false_is_mount_spec():
    assert bind_mount_spec({"create_host_path": False}, "/s", "/d", False)[
        "BindOptions"
    ] == {}


def test_rprivate_propagation_compared_in_bind_options():
    spec = bind_mount_spec({"propagation": "rprivate"}, "/s", "/d", False)
    assert spec["BindOptions"] == {"Propagation": "rprivate"}


def test_other_propagation_fails_closed():
    for value in ("rshared", "shared", "slave", "rslave", "private", ""):
        with pytest.raises(ValueError, match="replay_bind_propagation_unsupported"):
            bind_mount_spec({"propagation": value}, "/s", "/d", False)


def test_create_host_path_with_propagation_fails_closed():
    with pytest.raises(ValueError, match="replay_bind_options_unsupported"):
        bind_mount_spec(
            {"create_host_path": True, "propagation": "rprivate"}, "/s", "/d", False
        )


def test_unknown_option_fails_closed():
    with pytest.raises(ValueError, match="replay_bind_options_unsupported"):
        bind_mount_spec({"selinux": "z"}, "/s", "/d", False)
