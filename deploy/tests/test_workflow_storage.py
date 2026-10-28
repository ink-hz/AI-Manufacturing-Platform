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


def test_readiness_production_cold_process_never_activates_mock_authority(tmp_path):
    import os
    import subprocess
    mf=Path(__file__).parents[2]
    code=r"""
import json,os,sqlite3,sys
from pathlib import Path
from types import SimpleNamespace
root=Path(sys.argv[1]);mf=Path(sys.argv[2])
sys.path[:0]=[str(mf/'deploy'),str(mf/'src')]
import release
assert not any(name.startswith('manufacturing_platform') for name in sys.modules)
mock_modules={'manufacturing_platform.workflow.adapters.mock','manufacturing_platform.workflow.adapters.mock_store'}
constructor_calls=[];opened=[]
def guard(frame,event,arg):
    if event=='call' and frame.f_globals.get('__name__') in mock_modules and frame.f_code.co_name in {'__init__','transaction'}:
        constructor_calls.append(frame.f_code.co_name)
        raise AssertionError('production activated mock authority')
original_connect=sqlite3.connect
ast=Path(root/'authority.sqlite3')
def connect(database,*args,**kwargs):
    opened.append(str(database))
    assert str(ast) not in str(database),'production opened authority database'
    return original_connect(database,*args,**kwargs)
sqlite3.connect=connect
for key,value in {'ROOT':str(mf),'DATABASE_PATH':str(root/'legacy.sqlite3'),'WORKFLOW_DATABASE_PATH':str(root/'workflow.sqlite3'),'AUTHORITY_DATABASE_PATH':str(ast),'DATASET_ID':'production-v1','DATASET_MODE':'production','DATASET_LABEL':'Production'}.items():
    os.environ['PLATFORM_MANUFACTURING_'+key]=value
os.getuid=lambda:10001
os.statvfs=lambda _:SimpleNamespace(f_flag=os.ST_RDONLY)
sys.setprofile(guard)
exec(release.READINESS_CODE,{})
sys.setprofile(None)
assert not constructor_calls and not ast.exists()
assert opened and any('workflow.sqlite3' in path for path in opened)
# Definition imports are permitted; only construction/opening is forbidden.
"""
    env={k:v for k,v in os.environ.items() if not k.startswith('PLATFORM_')}
    result=subprocess.run([sys.executable,'-B','-c',code,str(tmp_path),str(mf)],env=env,capture_output=True,text=True,check=True)
    readiness=json.loads(result.stdout)
    assert readiness['business_records_written']==0
    assert readiness['workflow']['authority_ready'] is False
    assert readiness['workflow']['authority_status']=='external_adapter_unverified'
    assert not (tmp_path/'authority.sqlite3').exists()
