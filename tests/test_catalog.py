import json
from copy import deepcopy
from pathlib import Path

import pytest

from manufacturing_platform.catalog import Catalog, load_catalog


def test_default_catalog_has_stable_lines_stages_and_reference_only_content():
    data = load_catalog().public()
    assert [g['id'] for g in data['groups']] == ['internal', 'external']
    assert [line['id'] for line in data['lines']] == ['cameras', '3d-printers', 'oem']
    assert data['lines'][0]['name'] == '自研相机'
    assert data['lines'][0]['description'] == '含数采相机'
    assert [s['id'] for s in data['stages']] == [f'S{i}' for i in range(1, 10)]
    for stage in data['stages']:
        assert len(stage['prompts']) in (2, 3)
        assert '参考' in stage['help']
        for field in ('reference_participants', 'reference_handoffs', 'reference_systems'):
            assert stage[field]
            assert all('建议' in item['name'] or '参考' in item['name'] for item in stage[field])


def test_catalog_rename_reorder_and_disable_are_configuration_not_record_keys(tmp_path):
    data = load_catalog().definition.model_dump()
    data['lines'][0].update(name='新名称', order=99, group_id='external')
    data['lines'][1]['enabled'] = False
    data['stages'][0]['enabled'] = False
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    catalog = load_catalog(path)
    assert catalog.line('cameras')['name'] == '新名称'
    assert catalog.public()['lines'][-1]['id'] == 'cameras'
    for line, stage in [('3d-printers', None), ('cameras', 'S1'), ('missing', None)]:
        with pytest.raises(KeyError):
            catalog.line(line) if stage is None else catalog.stage(line, stage)


@pytest.mark.parametrize('change', ['duplicate', 'group', 'stage', 'duplicate_stage', 'unknown_field'])
def test_invalid_catalog_fails_explicitly(change):
    data = deepcopy(load_catalog().definition.model_dump())
    if change == 'duplicate':
        data['lines'].append(data['lines'][0])
    elif change == 'group':
        data['lines'][0]['group_id'] = 'missing'
    elif change == 'stage':
        data['lines'][0]['stage_ids'] = ['missing']
    elif change == 'duplicate_stage':
        data['lines'][0]['stage_ids'] = ['S1', 'S1']
    else:
        data['lines'][0]['typo'] = 'not allowed'
    with pytest.raises(ValueError):
        Catalog(data)
