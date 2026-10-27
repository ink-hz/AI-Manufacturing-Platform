import importlib
import io
from pathlib import Path
import sys
import tarfile
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]))


def archive(path,names):
    with tarfile.open(path,'w:gz') as tar:
        for name in names:
            entry=tarfile.TarInfo(name);data=b'content';entry.size=len(data);tar.addfile(entry,io.BytesIO(data))


def test_payload_extraction_never_writes_outside_private_stage(tmp_path):
    packed=tmp_path/'payload.tar.gz';archive(packed,['build/Dockerfile','../escaped'])
    stage=tmp_path/'stage';stage.mkdir()
    with pytest.raises(ValueError):importlib.import_module('install_payload').extract_payload(packed,stage)
    assert not (tmp_path/'escaped').exists() and not list(stage.iterdir())


def test_payload_rejects_duplicates_and_does_not_overwrite_existing_controller(tmp_path):
    packed=tmp_path/'payload.tar.gz';archive(packed,['release.py','release.py'])
    stage=tmp_path/'stage';stage.mkdir()
    with pytest.raises(ValueError):importlib.import_module('install_payload').extract_payload(packed,stage)
    archive(packed,['release.py']);(stage/'release.py').write_text('keep')
    with pytest.raises(ValueError):importlib.import_module('install_payload').extract_payload(packed,stage)
    assert (stage/'release.py').read_text()=='keep'


def test_regular_payload_is_extracted_with_build_paths(tmp_path):
    packed=tmp_path/'payload.tar.gz';archive(packed,['build/Dockerfile','business/manifest.json','release.py'])
    stage=tmp_path/'stage';stage.mkdir()
    importlib.import_module('install_payload').extract_payload(packed,stage)
    assert (stage/'build/Dockerfile').read_bytes()==b'content'
