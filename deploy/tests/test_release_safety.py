import copy
import importlib.util
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import release


def test_image_default_change_is_rejected_before_override_candidate():
    before={'Config':{'Cmd':['uvicorn'],'Entrypoint':None,'User':'10001','Env':['KEEP=value'],'WorkingDir':'/app','Healthcheck':{'Test':['CMD','true']},'Labels':{}}}
    for key,value in [('Cmd',['wrong']),('Entrypoint',['sh']),('User','0'),('Env',['KEEP=changed']),('Healthcheck',None),('Labels',{'unexpected':'yes'})]:
        after=copy.deepcopy(before);after['Config'][key]=value
        with pytest.raises(ValueError,match='image_defaults_changed'):
            release.validate_image_defaults(before,after)
    release.validate_image_defaults(before,copy.deepcopy(before))


def test_rollback_tag_must_resolve_to_current_baseline(monkeypatch):
    monkeypatch.setattr(release.ops,'run',lambda args:b'[{"Id":"sha256:other"}]')
    with pytest.raises(ValueError,match='rollback_tag_drift'):
        release.check_rollback_image({'Config':{'Image':'old:live'},'Image':'sha256:baseline'})


def test_only_exact_approved_manufacturing_paths_are_accepted():
    e={'manufacturing_commit':'a'*40,'manufacturing_host':'/data/orbbec-agent-platform/manufacturing/releases/'+'a'*40,'data_host':'/data/orbbec-agent-platform/manufacturing/data'}
    release.validate_paths(e)
    for field,value in [('data_host','/etc'),('data_host','/data/orbbec-agent-platform/manufacturing/../data'),('manufacturing_host','/tmp/release')]:
        altered={**e,field:value}
        with pytest.raises(ValueError,match='unapproved_manufacturing_path'):
            release.validate_paths(altered)


def test_failed_success_publication_leaves_no_success_receipt(tmp_path,monkeypatch):
    monkeypatch.setattr(release.ops,'STAGE',tmp_path)
    calls=[]
    def write(name,value):
        calls.append(name)
        if name=='cutover.json':raise OSError('full disk')
        (tmp_path/name).write_text('{}')
    monkeypatch.setattr(release.ops,'write',write)
    with pytest.raises(OSError):release.publish_success({'status':'healthy'},{'image':'candidate'})
    assert calls==['future-maintenance.json','cutover.json']
    assert not (tmp_path/'cutover.json').exists()
    assert not (tmp_path/'future-maintenance.json').exists()


def test_metadata_rejects_mutable_or_untrusted_release(tmp_path,monkeypatch):
    from types import SimpleNamespace
    root=tmp_path/'release';root.mkdir();(root/'src').mkdir();(root/'src'/'code.py').write_text('x=1')
    for p in [root,root/'src']:p.chmod(0o555)
    (root/'src'/'code.py').chmod(0o444)
    # Independent validation uses lstat, never silently omits special files.
    monkeypatch.setattr(release,'trusted_stat',lambda p:SimpleNamespace(st_uid=0,st_gid=0,st_mode=p.lstat().st_mode))
    release.validate_release_metadata(root)
    (root/'src'/'code.py').chmod(0o644)
    with pytest.raises(ValueError,match='business_file_metadata'):
        release.validate_release_metadata(root)
