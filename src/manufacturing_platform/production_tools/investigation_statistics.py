"""Typed historical impact captured directly from trusted source aggregates.

These are source record/SN counts with explicit denominators and coverage, never
manufactured yield or production quantities. No observation snapshot is created.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..workflow.clock import checked_time
from .contracts import ProductionQuery, MissingScope
from .investigation_models import DecimalId, Text, TimeRange

Count = Annotated[str, Field(strict=True, pattern=r'^(0|[1-9][0-9]{0,19})$')]
CaptureState = Literal['available', 'partial', 'unavailable', 'unsupported_scope']
SCOPE_FIELDS = (
    'start', 'end', 'sn', 'order_id', 'device', 'status', 'stage_id',
    'software_id', 'software_version', 'config_log_id', 'config_version',
    'error_code', 'barcode', 'missing_fields',
)


class ImpactFilters(TimeRange, MissingScope):
    kind: Literal['production_statistics'] = 'production_statistics'
    sn: Text | None = None
    order_id: DecimalId | None = None
    device: Text | None = None
    status: Literal['1', '2'] | None = None
    stage_id: DecimalId | None = None
    software_id: DecimalId | None = None
    software_version: Text | None = None
    config_log_id: DecimalId | None = None
    config_version: Text | None = None
    error_code: Text | None = None
    barcode: Text | None = None


class OutputModel(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class ImpactCounts(OutputModel):
    records: Count
    distinct_sn: Count
    pass_records: Count
    fail_records: Count
    unknown_records: Count


class ImpactCapture(OutputModel):
    state: CaptureState
    filters: ImpactFilters
    captured_at: datetime
    complete: bool = Field(strict=True)
    counts: ImpactCounts | None = None
    unsupported_filters: list[str] = Field(default_factory=list, max_length=13)
    error: Literal['SOURCE_UNAVAILABLE', 'SOURCE_SCHEMA_INVALID', 'UNSUPPORTED_FILTERS', 'CAPABILITY_UNAVAILABLE'] | None = None


class ImpactDenominator(OutputModel):
    numerator: Count | None
    denominator: Count | None
    numerator_capture: Literal['failure'] = 'failure'
    numerator_metric: Literal['records', 'distinct_sn']
    denominator_capture: Literal['baseline'] = 'baseline'
    denominator_metric: Literal['records', 'distinct_sn']


class InvestigationImpact(OutputModel):
    version: Literal[1] = 1
    state: CaptureState
    captured_at: datetime
    requested_filters: ImpactFilters
    unsupported_filters: list[str] = Field(default_factory=list, max_length=13)
    baseline: ImpactCapture
    selected: ImpactCapture
    failure: ImpactCapture
    failure_records: ImpactDenominator
    failed_involved_sn: ImpactDenominator


def scope_filters(context):
    """Exclude navigation, evidence identity and text notes from impact scope."""
    return ImpactFilters.model_validate({key: context[key] for key in SCOPE_FIELDS if context.get(key) is not None}).model_dump(mode='json', exclude_none=True)


def _counts(row):
    names = ('records', 'distinct_sn', 'pass_records', 'fail_records')
    if any(type(row.get(key)) is not int or not 0 <= row[key] < 10**20 for key in names):
        raise ValueError('invalid source aggregate')
    if row['distinct_sn'] > row['records'] or row['pass_records'] + row['fail_records'] > row['records']:
        raise ValueError('contradictory source aggregate')
    return ImpactCounts(**{key: str(row[key]) for key in names}, unknown_records=str(row['records'] - row['pass_records'] - row['fail_records']))


def _capture(production, actor, scope, filters, clock):
    now = checked_time(clock)
    unsupported = sorted(set(filters) - set(ProductionQuery.model_fields))
    if unsupported:
        return ImpactCapture(state='unsupported_scope', filters=filters, captured_at=now, complete=False, unsupported_filters=unsupported, error='UNSUPPORTED_FILTERS')
    try:
        config = production.config
        if 'production_statistics' not in config.source.capabilities:
            return ImpactCapture(state='unavailable', filters=filters, captured_at=now, complete=False, error='CAPABILITY_UNAVAILABLE')
        query = ProductionQuery.model_validate(filters)
        production._reauthorize(actor, scope.source_project_id, scope)
        config.source.project(scope.source_project_id)
        result = config.source.query(scope, query)
    except Exception:  # noqa: BLE001 - Credentials and connector details never enter durable metadata.
        production._reauthorize(actor, scope.source_project_id, scope)
        return ImpactCapture(state='unavailable', filters=filters, captured_at=checked_time(clock), complete=False, error='SOURCE_UNAVAILABLE')
    production._reauthorize(actor, scope.source_project_id, scope)
    try:
        if (
            result.source_kind != 'production_statistics'
            or type(result.items) is not list or len(result.items) != 1
            or type(result.complete) is not bool
            or not isinstance(result.captured_at, datetime) or result.captured_at.utcoffset() is None
            or ProductionQuery.model_validate(result.filters).model_dump(mode='json', exclude_none=True) != query.model_dump(mode='json', exclude_none=True)
        ):
            raise ValueError('invalid aggregate capture')
        counts = _counts(result.items[0])
        if query.status is not None:
            matching = counts.pass_records if query.status == '1' else counts.fail_records
            if matching != counts.records:
                raise ValueError('aggregate contradicts result filter')
        complete = result.complete and result.truncation_reason is None
        return ImpactCapture(state='available' if complete else 'partial', filters=filters, captured_at=result.captured_at.astimezone(UTC), complete=complete, counts=counts)
    except Exception:  # noqa: BLE001 - Invalid source schemas are represented as unavailable, never copied.
        return ImpactCapture(state='unavailable', filters=filters, captured_at=checked_time(clock), complete=False, error='SOURCE_SCHEMA_INVALID')


def capture_impact(production, actor, scope, context, *, clock):
    requested = scope_filters(context)
    baseline_filters = {key: value for key, value in requested.items() if key not in {'status', 'error_code'}}
    if baseline_filters.get('missing_fields'):
        baseline_filters['missing_fields'] = [field for field in baseline_filters['missing_fields'] if field != 'error_code']
        if not baseline_filters['missing_fields']:
            baseline_filters.pop('missing_fields')
    # Failure retains the selected symptom/error scope, replacing result status only.
    failure_filters = requested | {'status': '2'}
    baseline = _capture(production, actor, scope, baseline_filters, clock)
    selected = _capture(production, actor, scope, requested, clock)
    failure = _capture(production, actor, scope, failure_filters, clock)
    captures = (baseline, selected, failure)
    unsupported = sorted({key for capture in captures for key in capture.unsupported_filters})
    states = {capture.state for capture in captures}
    state = 'unsupported_scope' if unsupported else 'available' if states == {'available'} else 'unavailable' if states == {'unavailable'} else 'partial'
    def ratio(metric):
        return ImpactDenominator(
            numerator=getattr(failure.counts, metric) if failure.counts else None,
            denominator=getattr(baseline.counts, metric) if baseline.counts else None,
            numerator_metric=metric, denominator_metric=metric,
        )
    impact = InvestigationImpact(
        state=state, captured_at=checked_time(clock), requested_filters=requested,
        unsupported_filters=unsupported, baseline=baseline, selected=selected,
        failure=failure, failure_records=ratio('records'), failed_involved_sn=ratio('distinct_sn'),
    )
    production._reauthorize(actor, scope.source_project_id, scope)
    payload = impact.model_dump(mode='json')
    payload['requested_filters'] = requested
    for name, capture in zip(('baseline', 'selected', 'failure'), captures):
        payload[name]['filters'] = capture.filters.model_dump(mode='json', exclude_none=True)
    return payload
