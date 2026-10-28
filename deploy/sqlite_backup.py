"""Consistent private SQLite backup; never restore or checkpoint the live source."""
from pathlib import Path
from contextlib import closing
import hashlib
import json
import os
import sqlite3
import stat
import sys
import time
import uuid


def require(condition,reason):
    if not condition:raise ValueError(reason)


def safe_path(path):
    path=Path(path)
    require(path.is_absolute() and '..' not in path.parts,'unsafe_backup_path')
    require(not any(p.is_symlink() for p in [path,*path.parents]),'backup_symlink')
    return path


def backup_database(database_path,backup_parent,*,timeout_seconds=30,legacy=True):
    source=safe_path(database_path);parent=safe_path(backup_parent)
    require(source.is_file() and stat.S_ISREG(source.stat().st_mode),'missing_backup_source')
    require(source.stat().st_uid==os.getuid(),'backup_source_owner')
    require(parent==source.parent/'backups','backup_parent_location')
    require(0<timeout_seconds<=120,'backup_timeout_invalid')
    if not parent.exists():parent.mkdir(mode=0o700)
    info=parent.stat()
    require(parent.is_dir() and info.st_uid==os.getuid() and info.st_gid==os.getgid() and stat.S_IMODE(info.st_mode)==0o700,'backup_parent_metadata')
    folder=parent/uuid.uuid4().hex;folder.mkdir(mode=0o700)
    partial=folder/(source.name+'.partial');final=folder/source.name
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
            if legacy:require({'stage_records','tasks','task_operations'}<=names,'backup_legacy_schema')
        finally:destination.close()
    require(not final.exists(),'backup_destination_exists');partial.rename(final)
    require(stat.S_IMODE(final.stat().st_mode)==0o600,'backup_file_metadata')
    return {'path':str(final),'sha256':hashlib.sha256(final.read_bytes()).hexdigest(),
            'size_bytes':final.stat().st_size,'verified':True,'legacy_schema_present':legacy}


def backup_databases(paths):
    require(set(paths) in ({'legacy'},{'legacy','workflow','authority'}),'backup_file_inventory')
    paths={key:safe_path(path) for key,path in paths.items()}
    require(len(set(paths.values()))==len(paths),'backup_path_alias')
    require(len({p.parent for p in paths.values()})==1,'backup_parent_mismatch')
    existing=[p for p in paths.values() if p.exists()]
    require(all(p.is_file() and p.stat().st_uid==os.getuid() for p in existing),'backup_source_metadata')
    identities={(p.stat().st_dev,p.stat().st_ino) for p in existing}
    require(len(identities)==len(existing),'backup_inode_alias')
    require(paths['legacy'].is_file(),'missing_backup_source')
    files={}
    for key,path in paths.items():
        files[key]={'source':str(path),'present':path.exists()}
        if path.exists():files[key].update(backup_database(path,path.parent/'backups',legacy=key=='legacy'))
    return {'verified':True,'legacy_schema_present':True,'files':files,'cross_file_atomic':False,
            'consistency':'Each SQLite online backup is individually consistent; writes may occur between files.',
            'rollback':'Source only; never restore snapshots over current files or WAL.'}


if __name__=='__main__':
    os.umask(0o077)
    require(os.getuid()==10001 and os.getgid()==10001,'backup_application_uid_required')
    source=Path(os.environ['PLATFORM_MANUFACTURING_DATABASE_PATH'])
    require(source==Path('/app/data/manufacturing/workbench.sqlite3'),'backup_database_path')
    paths={'legacy':source}
    config=json.loads(sys.stdin.read() or '{}')
    require(set(config) in (set(),{'workflow','authority'}),'backup_input_keys')
    for key,value in config.items():
        path=safe_path(value)
        require(path.parent==source.parent and path.suffix=='.sqlite3','backup_workflow_path')
        paths[key]=path
    print(json.dumps(backup_databases(paths)))
