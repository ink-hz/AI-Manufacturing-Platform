import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]))


def repo(tmp_path):
    root=tmp_path/'repo';root.mkdir()
    for name,value in [('src/manufacturing_platform/__init__.py','x=1\n'),('docs/manufacturing-system-handbook.md','# Published handbook\n'),('docs/workflows/manufacturing-process-overview.md','# Published workflow\n')]:
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
    for args in [['init','-q'],['config','user.name','Artifact Test'],['config','user.email','artifact@example.invalid'],['add','.'],['commit','-q','-m','published']]:subprocess.run(['git','-C',str(root),*args],check=True)
    sha=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD']).decode().strip()
    assets=tmp_path/'dist';assets.mkdir();(assets/'manufacturing.js').write_text('window.OrbbecManufacturing={};');(assets/'manufacturing.css').write_text('.mf-root{}')
    return root,sha,assets


def test_release_uses_exact_committed_markdown_and_complete_manifest(tmp_path):
    root,sha,assets=repo(tmp_path)
    (root/'docs/manufacturing-system-handbook.md').write_text('# Unsaved draft must stay local\n')
    target=tmp_path/'business'
    importlib.import_module('build_artifact').write_business_release(root,sha,assets,target)
    assert (target/'docs/manufacturing-system-handbook.md').read_text()=='# Published handbook\n'
    metadata=json.loads((target/'handbook-metadata.json').read_text())
    manifest=json.loads((target/'manifest.json').read_text())
    assert manifest['commit']==sha
    actual={p.relative_to(target).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in target.rglob('*') if p.is_file() and p.name!='manifest.json'}
    assert actual==manifest['files']
    assert metadata['files']['docs/manufacturing-system-handbook.md']['sha256']==actual['docs/manufacturing-system-handbook.md']
    from datetime import datetime,timedelta
    assert datetime.fromisoformat(metadata['files']['docs/manufacturing-system-handbook.md']['updated_at']).utcoffset()==timedelta(0)
    assert not any(p.suffix in {'.sqlite3','.env'} for p in target.rglob('*'))


def test_release_refuses_overwriting_existing_payload(tmp_path):
    root,sha,assets=repo(tmp_path);target=tmp_path/'business';target.mkdir();(target/'keep').write_text('keep')
    with pytest.raises(ValueError):importlib.import_module('build_artifact').write_business_release(root,sha,assets,target)
    assert (target/'keep').read_text()=='keep'


def test_handbook_only_release_keeps_valid_empty_backend_copy_context(tmp_path,monkeypatch):
    module=importlib.import_module('build_artifact')
    root,_,assets=repo(tmp_path)
    for name in module.TOOLS:
        path=root/'deploy'/name;path.parent.mkdir(exist_ok=True);path.write_text('# build fixture\n')
    subprocess.run(['git','-C',str(root),'add','.'],check=True)
    subprocess.run(['git','-C',str(root),'commit','-q','-m','release tools'],check=True)
    sha=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD']).decode().strip()
    for branch in ['main','master']:
        if subprocess.run(['git','-C',str(root),'show-ref','--verify','--quiet','refs/heads/'+branch]).returncode:
            subprocess.run(['git','-C',str(root),'branch',branch,sha],check=True)
    monkeypatch.setattr(module,'build_frontend',lambda *_:assets)
    baseline={'old_image_tag':'orbbec:baseline','old_image_id':'sha256:'+'a'*64,'chain_length':38,'old_platform_commit':sha,'old_manufacturing_commit':sha,'previous_manifest':'/private/future-maintenance.json','lock_tool':'/private/lock.py','lock_tool_sha256':'b'*64,'approved_backend_files':[]}
    output=tmp_path/'output'
    module.assemble(root,root,output,baseline,sha,sha,sha)
    request=json.loads((output/'payload/request-template.json').read_text())
    assert request['backend_hashes']==request['backend_base_hashes']=={}
    import tarfile
    with tarfile.open(output/'payload.tar.gz') as tar:
        assert any(member.isdir() and member.name=='build/backend' for member in tar.getmembers())
