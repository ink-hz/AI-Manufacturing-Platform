"""Alias-guard regression for the mock-system store path validation.

Real trace (captured twice in React HTTP journeys, startup-error.log): read
endpoints returned 503 because the previous exists()/is_file()/stat() triple
raced SQLite's -wal/-shm lifecycle and observed a stale anomalous link count,
raising ``ValueError("aliased source database")`` for a healthy store. These
tests pin the corrected semantics: one atomic lstat per entry, transient
sidecar churn tolerated on immediate re-observation, while every stable alias
(symlink or extra hard link, sidecar or main database) still rejects and no
business operation is ever retried.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from manufacturing_platform.workflow.integrations import store as store_module
from manufacturing_platform.workflow.integrations.store import SystemStore


def make(tmp_path: Path) -> SystemStore:
    return SystemStore(
        tmp_path,
        "guard-ds-1",
        "mes",
        clock=lambda: datetime(2026, 11, 3, tzinfo=UTC),
    )


def prepared(tmp_path: Path) -> SystemStore:
    s = make(tmp_path)
    s.path.parent.mkdir(parents=True, exist_ok=True)
    s.path.touch()
    return s


def test_missing_database_and_sidecars_pass(tmp_path):
    make(tmp_path)._validate_path()


def test_plain_database_without_sidecars_passes(tmp_path):
    prepared(tmp_path)._validate_path()


def test_stable_hardlinked_sidecar_rejected(tmp_path):
    s = prepared(tmp_path)
    wal = Path(str(s.path) + "-wal")
    wal.touch()
    os.link(wal, tmp_path / "wal-alias")
    with pytest.raises(ValueError, match="aliased source database"):
        s._validate_path()


def test_symlinked_sidecar_rejected(tmp_path):
    s = prepared(tmp_path)
    target = tmp_path / "elsewhere"
    target.touch()
    Path(str(s.path) + "-shm").symlink_to(target)
    with pytest.raises(ValueError, match="aliased source database"):
        s._validate_path()


def test_hardlinked_main_database_rejected(tmp_path):
    s = prepared(tmp_path)
    os.link(s.path, tmp_path / "db-alias")
    with pytest.raises(ValueError, match="aliased source database"):
        s._validate_path()


def test_transient_sidecar_churn_tolerated(tmp_path, monkeypatch):
    """A stale anomalous observation that disappears on re-observation passes."""
    s = prepared(tmp_path)
    wal = Path(str(s.path) + "-wal")
    wal.touch()
    real = os.lstat
    calls = {"wal": 0}

    def flaky(path, *args, **kwargs):
        st = real(path, *args, **kwargs)
        if str(path) == str(wal):
            calls["wal"] += 1
            if calls["wal"] == 1:
                values = list(st)
                values[3] = 2  # st_nlink: stale extra-link observation
                return os.stat_result(tuple(values))
        return st

    monkeypatch.setattr(store_module.os, "lstat", flaky)
    s._validate_path()
    assert calls["wal"] >= 2


def test_sidecar_vanishing_mid_check_tolerated(tmp_path, monkeypatch):
    """SQLite deleting a sidecar between observations is lifecycle churn."""
    s = prepared(tmp_path)
    wal = Path(str(s.path) + "-wal")
    wal.touch()
    real = os.lstat

    def vanishing(path, *args, **kwargs):
        if str(path) == str(wal):
            raise FileNotFoundError(path)
        return real(path, *args, **kwargs)

    monkeypatch.setattr(store_module.os, "lstat", vanishing)
    s._validate_path()


def test_stable_anomaly_still_rejected_after_reobservation(tmp_path, monkeypatch):
    """Tolerance is bounded: a persistent anomalous sidecar never passes."""
    s = prepared(tmp_path)
    wal = Path(str(s.path) + "-wal")
    wal.touch()
    real = os.lstat
    calls = {"wal": 0}

    def stuck(path, *args, **kwargs):
        st = real(path, *args, **kwargs)
        if str(path) == str(wal):
            calls["wal"] += 1
            values = list(st)
            values[3] = 2
            return os.stat_result(tuple(values))
        return st

    monkeypatch.setattr(store_module.os, "lstat", stuck)
    with pytest.raises(ValueError, match="aliased source database"):
        s._validate_path()
    assert calls["wal"] == 3
