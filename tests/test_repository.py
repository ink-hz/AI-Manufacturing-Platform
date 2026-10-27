from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from manufacturing_platform.models import RecordWrite, TaskCreate, TaskWrite
from manufacturing_platform.repository import Conflict, NotFound, Repository


def record(practice='', version=0, **kwargs):
    return RecordWrite(expected_version=version, practice=practice, participants=[], handoffs=[], systems=[], **kwargs)


def test_records_empty_save_reopen_and_isolation(tmp_path):
    path = tmp_path / 'nested' / 'workbench.sqlite3'
    repo = Repository(str(path))
    empty = repo.read_stage('cameras', 'S1')
    assert empty == {'record': {'practice': '', 'participants': [], 'handoffs': [], 'systems': [], 'version': 0, 'updated_at': None, 'updated_by': None}, 'tasks': []}
    saved = repo.save_record('cameras', 'S1', record('现场待核实'), 'Alice')
    assert saved['version'] == 1 and saved['updated_by'] == 'Alice'
    assert Repository(str(path)).read_stage('cameras', 'S1')['record'] == saved
    assert repo.read_stage('oem', 'S1') == empty
    assert repo.read_stage('cameras', 'S2') == empty
    assert repo.overview('cameras')['S1'] == {'recorded': True, 'open_tasks': 0}
    repo.save_record('cameras', 'S1', record('  ', 1), 'Alice')
    assert repo.overview('cameras')['S1']['recorded'] is False


def test_compare_and_swap_across_independent_connections(tmp_path):
    path = str(tmp_path / 'workbench.sqlite3')
    repo = Repository(path)
    repo.read_stage('cameras', 'S1')
    def save(value):
        try:
            return Repository(path).save_record('cameras', 'S1', record(value), value)['version']
        except Conflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ['one', 'two']))
    assert sorted(results, key=str) == [1, 'conflict']
    with pytest.raises(Conflict):
        repo.save_record('cameras', 'S1', record('stale'), 'Alice')


def test_task_idempotency_reopen_actor_scope_and_version(tmp_path):
    path = str(tmp_path / 'workbench.sqlite3')
    repo = Repository(path)
    create = TaskCreate(title='  确认 BOM 版本  ', operation_id=uuid4())
    first = repo.create_task('cameras', 'S1', create, 'actor-1', 'Alice')
    assert first['title'] == '确认 BOM 版本'
    assert first['version'] == 1 and first['completed'] is False
    assert Repository(path).create_task('cameras', 'S1', create, 'actor-1', 'Alice') == first
    for line, stage, actor, title in [('oem','S1','actor-1',create.title), ('cameras','S2','actor-1',create.title), ('cameras','S1','actor-2',create.title), ('cameras','S1','actor-1','changed')]:
        with pytest.raises(Conflict):
            repo.create_task(line, stage, TaskCreate(title=title, operation_id=create.operation_id), actor, 'Alice')
    with pytest.raises(NotFound):
        repo.update_task('oem','S1',first['id'],TaskWrite(title='x',completed=True,expected_version=1),'Alice')
    done = repo.update_task('cameras','S1',first['id'],TaskWrite(title='已核对',completed=True,expected_version=1),'Bob')
    assert done['completed'] is True and done['version'] == 2 and done['updated_by'] == 'Bob'
    with pytest.raises(Conflict):
        repo.update_task('cameras','S1',first['id'],TaskWrite(title='x',completed=False,expected_version=1),'Alice')
    reopened = repo.update_task('cameras','S1',first['id'],TaskWrite(title='复核',completed=False,expected_version=2),'Alice')
    assert Repository(path).read_stage('cameras','S1')['tasks'] == [reopened]
    assert repo.create_task('cameras','S1',create,'actor-1','Alice') == first
    assert repo.overview('cameras')['S1'] == {'recorded': False, 'open_tasks': 1}


@pytest.mark.parametrize('path', ['', ':memory:'])
def test_database_requires_explicit_persistent_path(path):
    with pytest.raises(ValueError):
        Repository(path)


def test_independent_connections_race_task_creation_without_duplicates(tmp_path):
    import sqlite3
    path = str(tmp_path / 'workbench.sqlite3')
    repo = Repository(path)
    repo.health()
    create = TaskCreate(title='同一操作', operation_id=uuid4())
    def submit(_):
        return Repository(path).create_task('oem', 'S4', create, 'actor', 'Actor')
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(submit, range(2))
    assert first == second
    assert repo.read_stage('oem', 'S4')['tasks'] == [first]
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        assert db.execute('SELECT count(*) FROM task_operations').fetchone()[0] == 1
