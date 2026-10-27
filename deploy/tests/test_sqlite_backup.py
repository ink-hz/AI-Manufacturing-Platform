import hashlib
import importlib
import os
from pathlib import Path
import sqlite3
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]))


def source_database(path):
    db=sqlite3.connect(path)
    db.execute('PRAGMA journal_mode=WAL')
    for name in ['stage_records','tasks','task_operations']:db.execute(f'CREATE TABLE {name}(body TEXT)')
    db.execute('INSERT INTO stage_records VALUES (?)',('committed-in-wal',));db.commit()
    return db


def test_online_backup_contains_committed_wal_and_has_private_permissions(tmp_path):
    source=tmp_path/'workbench.sqlite3';db=source_database(source)
    try:
        before=source.stat().st_mtime_ns
        assert Path(str(source)+'-wal').stat().st_size>0
        result=importlib.import_module('sqlite_backup').backup_database(source,tmp_path/'backups')
        backup=Path(result['path']);assert backup.is_file()
        assert backup.stat().st_mode&0o777==0o600
        assert backup.parent.stat().st_mode&0o777==0o700
        assert result['sha256']==hashlib.sha256(backup.read_bytes()).hexdigest()
        assert result['verified'] and result['legacy_schema_present']
        check=sqlite3.connect(backup)
        try:
            assert check.execute('SELECT body FROM stage_records').fetchall()==[('committed-in-wal',)]
            assert check.execute('PRAGMA quick_check').fetchone()==('ok',)
        finally:check.close()
        assert source.stat().st_mtime_ns==before
        assert db.execute('PRAGMA journal_mode').fetchone()==('wal',)
    finally:db.close()


def test_backup_rejects_symlink_destination_without_changing_source(tmp_path):
    source=tmp_path/'workbench.sqlite3';db=source_database(source)
    outside=tmp_path/'outside';outside.mkdir();parent=tmp_path/'backups';parent.symlink_to(outside,target_is_directory=True)
    try:
        with pytest.raises(ValueError):importlib.import_module('sqlite_backup').backup_database(source,parent)
        assert not list(outside.iterdir())
        assert db.execute('SELECT count(*) FROM stage_records').fetchone()==(1,)
    finally:db.close()


def test_backup_rejects_missing_source_without_creating_database(tmp_path):
    source=tmp_path/'absent.sqlite3'
    with pytest.raises(ValueError):importlib.import_module('sqlite_backup').backup_database(source,tmp_path/'backups')
    assert not source.exists()
