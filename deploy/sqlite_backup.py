"""Consistent private SQLite backup; never restore or checkpoint the live source."""
from pathlib import Path
from contextlib import closing
import hashlib
import json
import os
import sqlite3
import stat
import time
import uuid


def require(condition,reason):
    if not condition:raise ValueError(reason)


def safe_path(path):
    path=Path(path)
    require(path.is_absolute() and '..' not in path.parts,'unsafe_backup_path')
    require(not any(p.is_symlink() for p in [path,*path.parents]),'backup_symlink')
    return path


def backup_database(database_path,backup_parent,*,timeout_seconds=30):
    source=safe_path(database_path);parent=safe_path(backup_parent)
    require(source.is_file() and stat.S_ISREG(source.stat().st_mode),'missing_backup_source')
    require(source.stat().st_uid==os.getuid(),'backup_source_owner')
    require(parent==source.parent/'backups','backup_parent_location')
    require(0<timeout_seconds<=120,'backup_timeout_invalid')
    if not parent.exists():parent.mkdir(mode=0o700)
    info=parent.stat()
    require(parent.is_dir() and info.st_uid==os.getuid() and info.st_gid==os.getgid() and stat.S_IMODE(info.st_mode)==0o700,'backup_parent_metadata')
    folder=parent/uuid.uuid4().hex;folder.mkdir(mode=0o700)
    partial=folder/'workbench.sqlite3.partial';final=folder/'workbench.sqlite3'
    fd=os.open(partial,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
    started=time.monotonic()
    def progress(*_):
        if time.monotonic()-started>timeout_seconds:raise TimeoutError('sqlite_backup_timeout')
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=5)) as live:
        live.execute('PRAGMA query_only=ON')
        destination=sqlite3.connect(partial)
        try:
            live.backup(destination,pages=128,progress=progress,sleep=0.05)
            require(destination.execute('PRAGMA journal_mode=DELETE').fetchone()==('delete',),'backup_destination_journal')
            require(destination.execute('PRAGMA quick_check').fetchall()==[('ok',)],'backup_integrity')
            names={r[0] for r in destination.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            require({'stage_records','tasks','task_operations'}<=names,'backup_legacy_schema')
        finally:destination.close()
    require(not final.exists(),'backup_destination_exists');partial.rename(final)
    require(stat.S_IMODE(final.stat().st_mode)==0o600,'backup_file_metadata')
    return {'path':str(final),'sha256':hashlib.sha256(final.read_bytes()).hexdigest(),
            'size_bytes':final.stat().st_size,'verified':True,'legacy_schema_present':True}


if __name__=='__main__':
    os.umask(0o077)
    require(os.getuid()==10001 and os.getgid()==10001,'backup_application_uid_required')
    source=Path(os.environ['PLATFORM_MANUFACTURING_DATABASE_PATH'])
    require(source==Path('/app/data/manufacturing/workbench.sqlite3'),'backup_database_path')
    print(json.dumps(backup_database(source,source.parent/'backups')))
