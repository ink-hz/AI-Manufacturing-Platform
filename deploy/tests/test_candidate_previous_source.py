"""Candidate upgrades can prove old-code compatibility without mounting production state."""
from contextlib import nullcontext
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).parents[1]))
import release


@pytest.mark.parametrize('mode', ['upgrade', 'initial'])
def test_candidate_previous_source_is_read_only_and_database_remains_disposable(tmp_path, monkeypatch, mode):
    old = 'a' * 40
    request = {'mode': mode, 'manufacturing_host': '/data/orbbec-agent-platform/manufacturing/releases/' + 'b' * 40,
               'manufacturing_commit': 'b' * 40, 'expected_old_manufacturing_commit': old,
               'target_image_id': 'sha256:new', 'data_host': '/data/orbbec-agent-platform/manufacturing/data'}
    pre = {'old': {'Id': 'running'}, 'expected_source': {}, 'expected_static': {}}
    (tmp_path / 'candidate_verify.py').write_text('pass')
    monkeypatch.setattr(release.ops, 'STAGE', tmp_path)
    monkeypatch.setattr(release.ops, 'Locks', lambda: nullcontext())
    monkeypatch.setattr(release.ops, 'read', lambda name: pre)
    monkeypatch.setattr(release.ops, 'inspect', lambda name: {'Id': 'running'})
    monkeypatch.setattr(release, 'unchanged', lambda *args: None)
    monkeypatch.setattr(release, 'check_images', lambda *args: None)
    monkeypatch.setattr(release.ops, 'digest', lambda path: 'd' * 64)
    monkeypatch.setattr(release.ops, 'write', lambda *args: None)
    calls = []
    monkeypatch.setattr(release.ops, 'run', lambda args, **kwargs: calls.append(args) or json.dumps({'passed': True}).encode())
    release.candidate(request)
    args = calls[0]
    mounts = [args[i + 1] for i, value in enumerate(args) if value == '--mount']
    assert all(value.endswith(',readonly') for value in mounts)
    assert len(mounts) == (2 if mode == 'upgrade' else 1)
    assert all('source=' + request['data_host'] + ',' not in value for value in mounts)
    assert 'PLATFORM_MANUFACTURING_DATABASE_PATH=/tmp/manufacturing-candidate.sqlite3' in args
    assert args[args.index('--network') + 1] == 'none'
    assert args[args.index('--user') + 1] == '10001:10001'
    assert '--read-only' in args
    previous_env = 'PLATFORM_MANUFACTURING_PREVIOUS_ROOT=/opt/manufacturing-previous'
    if mode == 'upgrade':
        assert previous_env in args
        assert 'PLATFORM_MANUFACTURING_PREVIOUS_RELEASE=' + old in args
        assert any('source=/data/orbbec-agent-platform/manufacturing/releases/' + old + ',target=/opt/manufacturing-previous,' in value for value in mounts)
    else:
        assert previous_env not in args
