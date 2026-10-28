import json
from pathlib import Path
import sqlite3
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]))
import sqlite_backup
from test_sqlite_backup import source_database


def test_backups_cover_each_existing_file_and_record_initial_absence(tmp_path):
    legacy=tmp_path/'workbench.sqlite3';db=source_database(legacy);db.close()
    domain=tmp_path/'workflow.sqlite3';authority=tmp_path/'authority.sqlite3'
    with sqlite3.connect(domain) as c:c.execute('CREATE TABLE dataset_metadata(id,mode,label)');c.execute("INSERT INTO dataset_metadata VALUES ('d','demo','Demo')")
    result=sqlite_backup.backup_databases({'legacy':legacy,'workflow':domain,'authority':authority})
    assert result['verified'] and result['legacy_schema_present']
    assert result['files']['authority']=={'source':str(authority),'present':False}
    assert not authority.exists()
    assert result['files']['workflow']['verified']
    assert result['cross_file_atomic'] is False
    with sqlite3.connect(domain) as c:c.execute("INSERT INTO dataset_metadata VALUES ('post-cutover-write','demo','Demo')")
    assert sqlite3.connect(domain).execute('select count(*) from dataset_metadata').fetchone()==(2,)


def test_multi_backup_checks_all_aliases_before_creating_backup(tmp_path):
    legacy=tmp_path/'workbench.sqlite3';db=source_database(legacy);db.close()
    authority=tmp_path/'authority.sqlite3';authority.symlink_to(legacy)
    with pytest.raises(ValueError):sqlite_backup.backup_databases({'legacy':legacy,'workflow':tmp_path/'absent.sqlite3','authority':authority})
    assert not (tmp_path/'backups').exists()


def test_readiness_initializes_only_schema_and_dataset_then_preserves_rows(tmp_path,monkeypatch,capsys):
    import os
    from types import SimpleNamespace
    import release
    mf=Path(__file__).parents[2]
    sys.path.insert(0,str(mf/'src'))
    env={'PLATFORM_MANUFACTURING_ROOT':str(mf),'PLATFORM_MANUFACTURING_DATABASE_PATH':str(tmp_path/'legacy.sqlite3'),'PLATFORM_MANUFACTURING_WORKFLOW_DATABASE_PATH':str(tmp_path/'workflow.sqlite3'),'PLATFORM_MANUFACTURING_AUTHORITY_DATABASE_PATH':str(tmp_path/'authority.sqlite3'),'PLATFORM_MANUFACTURING_DATASET_ID':'readiness-demo','PLATFORM_MANUFACTURING_DATASET_MODE':'demo','PLATFORM_MANUFACTURING_DATASET_LABEL':'Demo'}
    for k,v in env.items():monkeypatch.setenv(k,v)
    monkeypatch.setattr(os,'getuid',lambda:10001);monkeypatch.setattr(os,'statvfs',lambda _:SimpleNamespace(f_flag=os.ST_RDONLY))
    exec(release.READINESS_CODE,{})
    result=json.loads(capsys.readouterr().out)
    assert result['workflow']['schema_ready'] and result['workflow']['authority_ready']
    with sqlite3.connect(env['PLATFORM_MANUFACTURING_WORKFLOW_DATABASE_PATH']) as c:
        assert c.execute('select id,mode,label from dataset_metadata').fetchall()==[('readiness-demo','demo','Demo')]
        assert c.execute('select count(*) from projects').fetchone()==(0,)
    with sqlite3.connect(env['PLATFORM_MANUFACTURING_AUTHORITY_DATABASE_PATH']) as c:
        assert c.execute('select count(*) from inventory').fetchone()==(0,)
    exec(release.READINESS_CODE,{})
    assert json.loads(capsys.readouterr().out)['business_records_written']==0


def test_readiness_production_never_imports_or_initializes_mock_authority(tmp_path,monkeypatch,capsys):
    import builtins
    import os
    from types import SimpleNamespace
    import release
    mf=Path(__file__).parents[2];sys.path.insert(0,str(mf/'src'))
    for k,v in {'ROOT':str(mf),'DATABASE_PATH':str(tmp_path/'legacy.sqlite3'),'WORKFLOW_DATABASE_PATH':str(tmp_path/'workflow.sqlite3'),'AUTHORITY_DATABASE_PATH':str(tmp_path/'authority.sqlite3'),'DATASET_ID':'production-v1','DATASET_MODE':'production','DATASET_LABEL':'Production'}.items():monkeypatch.setenv('PLATFORM_MANUFACTURING_'+k,v)
    monkeypatch.setattr(os,'getuid',lambda:10001);monkeypatch.setattr(os,'statvfs',lambda _:SimpleNamespace(f_flag=os.ST_RDONLY))
    original=builtins.__import__
    def guarded(name,*args,**kwargs):
        assert 'mock' not in name
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',guarded)
    exec(release.READINESS_CODE,{})
    result=json.loads(capsys.readouterr().out)
    assert result['workflow']['authority_ready'] is False
    assert result['workflow']['authority_status']=='external_adapter_unverified'
    assert not (tmp_path/'authority.sqlite3').exists()
