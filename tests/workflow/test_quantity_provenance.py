from copy import deepcopy

import pytest
from pydantic import ValidationError

from manufacturing_platform.workflow.quantity_provenance import (
    ProvenancedQuantity, quantity, source_from_ref, source_modes,
)


def ref(mode='manual', **changes):
    data = dict(system='sap', object_type='plan', external_id='plan-1', version=1,
                mode=mode, occurred_at='2026-11-01T00:00:00Z',
                collected_at='2026-11-01T00:00:01Z', evidence='evidence')
    data.update(changes)
    return data


def source(raw, reference='p/r/1', **kwargs):
    return source_from_ref(raw, reference=reference, project_id='p', object_kind='requirement',
                           object_id='r', value='20.001', unit='kg', meaning='required', **kwargs)


def test_mixed_inputs_preserve_identity_precision_and_deduplicate():
    raw = ref()
    before = deepcopy(raw)
    manual = source(raw, environment='production', trusted=True)
    mock = source(ref('mock'), 'p/r/2')
    result = quantity('20.0010000000000000001', 'kg', 'required', [mock, manual, mock])
    assert raw == before
    assert result.value == '20.0010000000000000001'
    assert result.origins == ['manual', 'mock']
    assert result.environments == ['mock', 'production']
    assert result.input_refs == [s.reference for s in result.source_refs]
    assert len(result.source_refs) == 2
    assert result.fact_role == 'confirmed'
    assert source_modes([result]) == ['manual', 'mock']
    assert ProvenancedQuantity.model_validate_json(result.model_dump_json()) == result


def test_mock_identity_survives_platform_confirmation_and_broken_metadata():
    mock = source(ref('mock', occurred_at='broken', system=''))
    result = quantity('20.001', 'kg', 'required', [mock])
    assert result.origins == ['mock'] and result.environments == ['mock']
    assert result.observed_at is None and result.coverage == 'unknown'


def test_trust_and_missing_identity_are_conservative():
    assert source(ref('api'), environment='production').origin == 'unknown'
    assert source(ref('api'), environment='production').environment == 'unknown'
    trusted = source(ref('api'), environment='production', trusted=True)
    assert trusted.origin == 'native' and trusted.environment == 'production'
    assert source_modes([quantity('1', 'kg', 'x', [trusted])]) == ['api']
    assert source(ref('manual', external_id='')).origin == 'unknown'
    assert source(ref('manual'), environment='unexpected', trusted=True).environment == 'unknown'


@pytest.mark.parametrize('field', ['system', 'object_type', 'external_id'])
@pytest.mark.parametrize('mode', ['manual', 'file', 'api'])
def test_oversized_identity_fields_do_not_grant_provenance(field, mode):
    result = source(ref(mode, **{field: 'x' * 201}), trusted=True, environment='production')
    assert result.origin == 'unknown' and result.coverage == 'unknown'


def test_oversized_mock_identity_remains_recognizable():
    result = source(ref('mock', external_id='x' * 201), environment='production', trusted=True)
    assert result.origin == 'mock' and result.environment == 'mock'
    assert result.coverage == 'unknown'


def test_missing_sources_and_time_do_not_fabricate_values():
    empty = quantity(None, 'kg', 'required', [])
    assert empty.value is None and empty.coverage == 'unknown' and empty.fact_role == 'unknown'
    assert empty.origins == ['unknown'] and empty.environments == ['unknown'] and empty.input_refs == []
    assert source_modes([empty]) == ['unknown']
    assert source_modes([]) == []
    missing = source(ref(occurred_at='2026-11-01T00:00:00'))
    result = quantity(None, 'kg', 'required', [source(ref()), missing.model_copy(update={'reference': 'other'})])
    assert result.observed_at is None and result.collected_at is not None
    assert result.value is None


def test_conflicting_reference_is_rejected_and_explicit_coverage_only_degrades():
    one = source(ref())
    other = one.model_copy(update={'value': '21'})
    with pytest.raises(ValueError):
        quantity('1', 'kg', 'x', [one, other])
    assert quantity('1', 'kg', 'x', [one], coverage='partial').coverage == 'partial'
    incomplete = source(None)
    assert quantity('1', 'kg', 'x', [incomplete], coverage='complete').coverage == 'unknown'


def test_model_rejects_forged_projections():
    result = quantity('1', 'kg', 'x', [source(ref('mock'))])
    for field, value in [('origins', ['manual']), ('environments', ['production']), ('input_refs', [])]:
        data = result.model_dump()
        data[field] = value
        with pytest.raises(ValidationError):
            ProvenancedQuantity.model_validate(data)


def test_earliest_timestamps_and_coverage_order():
    from manufacturing_platform.workflow.contracts import SourceRef

    first = source(SourceRef.model_validate(ref()))
    second = source(ref(occurred_at='2026-11-02T00:00:00Z',
                        collected_at='2026-11-02T00:00:01Z'), 'p/r/2')
    result = quantity('1', 'kg', 'x', [second, first])
    assert result.observed_at == first.occurred_at
    assert result.collected_at == first.collected_at
    failed = first.model_copy(update={'coverage': 'failed'})
    assert quantity('1', 'kg', 'x', [failed, second], coverage='partial').coverage == 'failed'


def test_invalid_version_is_preserved_without_granting_identity():
    result = source(ref('api', version='legacy-v1'), trusted=True)
    assert result.version == 'legacy-v1'
    assert result.origin == 'unknown' and result.coverage == 'unknown'


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-Infinity', '1e999', 'garbage', '', ' 1'])
def test_quantity_values_reject_non_plain_decimals(value):
    valid = source(ref())
    for model, data in [(type(valid), valid.model_dump()),
                        (ProvenancedQuantity, quantity('1', 'kg', 'x', [valid]).model_dump())]:
        data['value'] = value
        with pytest.raises(ValidationError):
            model.model_validate(data)


@pytest.mark.parametrize('value', [None, '-001.23000000000000000001', '+0002', '0', '.1', '1.'])
def test_quantity_values_preserve_plain_decimal_strings(value):
    valid = source(ref())
    data = valid.model_dump()
    data['value'] = value
    assert type(valid).model_validate(data).value == value
    assert quantity(value, 'kg', 'x', [valid]).value == value


def test_direct_and_json_projection_reject_forged_merge_fields():
    import json

    missing = source(ref(occurred_at='broken', collected_at='broken'))
    result = quantity('1', 'kg', 'x', [missing])
    for field, value in [('coverage', 'complete'), ('observed_at', '2026-11-01T00:00:00Z'),
                         ('collected_at', '2026-11-01T00:00:00Z')]:
        data = result.model_dump(mode='json')
        data[field] = value
        with pytest.raises(ValidationError):
            ProvenancedQuantity.model_validate(data)
        with pytest.raises(ValidationError):
            ProvenancedQuantity.model_validate_json(json.dumps(data))
    data = result.model_dump()
    data['coverage'] = 'partial'
    assert ProvenancedQuantity.model_validate(data).coverage == 'partial'


def test_empty_projection_requires_unknown_identity_and_role():
    import json

    empty = quantity(None, 'kg', 'x', [])
    for field, value in [('origins', []), ('environments', []), ('fact_role', 'confirmed'),
                         ('coverage', 'complete'), ('observed_at', '2026-11-01T00:00:00Z'),
                         ('collected_at', '2026-11-01T00:00:00Z'), ('input_refs', ['fake'])]:
        data = empty.model_dump(mode='json')
        data[field] = value
        with pytest.raises(ValidationError):
            ProvenancedQuantity.model_validate_json(json.dumps(data))
    data = empty.model_dump()
    data['coverage'] = 'failed'
    assert ProvenancedQuantity.model_validate(data).coverage == 'failed'


def test_direct_projection_requires_earliest_times_and_cannot_upgrade_failed():
    first = source(ref()).model_copy(update={'coverage': 'failed'})
    second = source(ref(occurred_at='2026-11-02T00:00:00Z',
                        collected_at='2026-11-02T00:00:01Z'), 'p/r/2')
    result = quantity('1', 'kg', 'x', [first, second])
    for field, value in [('coverage', 'partial'), ('observed_at', second.occurred_at),
                         ('collected_at', second.collected_at)]:
        data = result.model_dump()
        data[field] = value
        with pytest.raises(ValidationError):
            ProvenancedQuantity.model_validate(data)
