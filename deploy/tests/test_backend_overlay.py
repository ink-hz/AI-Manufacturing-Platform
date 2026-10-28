import hashlib
from pathlib import Path
import subprocess
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]))
import build_artifact as builder
import release


def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args]).decode().strip()

def fixture(tmp_path):
    root=tmp_path/'repo';root.mkdir();git(root,'init','-q');git(root,'config','user.name','test');git(root,'config','user.email','test@example.invalid')
    p=root/'backend/app';p.mkdir(parents=True);(p/'main.py').write_text('old')
    git(root,'add','.');git(root,'commit','-qm','base');base=git(root,'rev-parse','HEAD')
    (p/'main.py').write_text('new');(p/'manufacturing_security.py').write_text('new security')
    git(root,'add','.');git(root,'commit','-qm','target');target=git(root,'rev-parse','HEAD')
    return root,base,target

def test_added_source_requires_explicit_review_and_records_absence(tmp_path):
    root,base,target=fixture(tmp_path);out=tmp_path/'out'
    old,new=builder.backend_overlay(root,base,target,out,['main.py','manufacturing_security.py'],['manufacturing_security.py'])
    assert old=={'main.py':hashlib.sha256(b'old').hexdigest(),'manufacturing_security.py':None}
    assert new['manufacturing_security.py']==hashlib.sha256(b'new security').hexdigest()
    assert (out/'main.py').read_text()=='new'
    with pytest.raises(ValueError):builder.backend_overlay(root,base,target,tmp_path/'other',['main.py','manufacturing_security.py'],[])

@pytest.mark.parametrize('change',['symlink','deletion','unreviewed','traversal'])
def test_overlay_refuses_unreviewed_and_nonregular_paths(tmp_path,change):
    root,base,target=fixture(tmp_path)
    p=root/'backend/app/main.py'
    if change=='symlink':p.unlink();p.symlink_to('manufacturing_security.py')
    if change=='deletion':p.unlink()
    if change in {'symlink','deletion'}:
        git(root,'add','.');git(root,'commit','-qm',change);target=git(root,'rev-parse','HEAD')
    approved=['main.py','manufacturing_security.py'] if change!='unreviewed' else ['main.py']
    if change=='traversal':approved+=['../secret']
    with pytest.raises(ValueError):builder.backend_overlay(root,base,target,tmp_path/'out',approved,['manufacturing_security.py'])

def test_manifest_absence_cannot_hide_existing_or_unreviewed_creation():
    e={'backend_hashes':{'main.py':'a'*64,'manufacturing_security.py':'b'*64},'backend_base_hashes':{'main.py':'c'*64,'manufacturing_security.py':None},'backend_added_files':['manufacturing_security.py']}
    release.validate_backend_manifest(e)
    release.validate_backend_baseline(e,{'main.py':'c'*64})
    with pytest.raises(ValueError):release.validate_backend_baseline(e,{'main.py':'c'*64,'manufacturing_security.py':'b'*64})
    with pytest.raises(ValueError):release.validate_backend_manifest({**e,'backend_added_files':[]})
    with pytest.raises(ValueError):release.validate_backend_manifest({**e,'backend_hashes':{**e['backend_hashes'],'../secret':'a'*64}})
