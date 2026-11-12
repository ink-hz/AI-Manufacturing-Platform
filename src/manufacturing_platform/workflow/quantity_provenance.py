"""Pure, conservative provenance projections for quantities."""

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, TypeAdapter, ValidationError, model_validator

from .contracts import SourceRef, StrictModel

Origin = Literal['native', 'manual', 'file', 'mock', 'unknown']
Environment = Literal['production', 'test', 'development', 'mock', 'unknown']
Coverage = Literal['complete', 'partial', 'failed', 'unknown']
FactRole = Literal['confirmed', 'observation', 'unknown']
_COVERAGE_ORDER = {'failed': 0, 'partial': 1, 'unknown': 2, 'complete': 3}
_TIME = TypeAdapter(AwareDatetime)


class QuantitySource(StrictModel):
    reference: str
    project_id: str
    object_kind: str
    object_id: str
    system: str | None
    source_type: str | None
    external_id: str | None
    version: int | str | None
    namespace: str | None
    origin: Origin
    environment: Environment
    occurred_at: AwareDatetime | None
    collected_at: AwareDatetime | None
    coverage: Coverage
    value: str | None
    unit: str | None
    meaning: str

    @model_validator(mode='after')
    def mock_environment(self):
        if self.origin == 'mock' and self.environment != 'mock':
            raise ValueError('mock sources require mock environment')
        return self


class ProvenancedQuantity(StrictModel):
    value: str | None
    unit: str
    meaning: str
    origins: list[Origin]
    environments: list[Environment]
    fact_role: FactRole
    observed_at: AwareDatetime | None
    collected_at: AwareDatetime | None
    coverage: Coverage
    source_refs: list[QuantitySource]
    input_refs: list[str]

    @model_validator(mode='after')
    def validate_projection(self):
        refs = [source.reference for source in self.source_refs]
        if len(refs) != len(set(refs)) or self.input_refs != refs:
            raise ValueError('input_refs must match unique source_refs')
        if self.origins != sorted({source.origin for source in self.source_refs}):
            raise ValueError('origins must match source_refs')
        if self.environments != sorted({source.environment for source in self.source_refs}):
            raise ValueError('environments must match source_refs')
        return self


def _time(value):
    try:
        return _TIME.validate_python(value) if value is not None else None
    except (ValidationError, ValueError, TypeError):
        return None


def source_from_ref(source, *, reference: str, project_id: str, object_kind: str,
                    object_id: str, value: str | None, unit: str | None, meaning: str,
                    environment: str = 'unknown', namespace: str | None = None,
                    trusted: bool = False) -> QuantitySource:
    if isinstance(source, SourceRef):
        data = source.model_dump()
    elif isinstance(source, dict):
        data = source
    elif source is None:
        data = {}
    else:
        raise TypeError('source must be SourceRef, dict, or None')

    identity = all(isinstance(data.get(key), str) and data[key].strip()
                   for key in ('system', 'object_type', 'external_id'))
    version = data.get('version')
    identity = identity and type(version) is int and version >= 1
    mode = data.get('mode')
    if mode == 'mock':
        origin = 'mock'
    elif identity and mode in ('manual', 'file'):
        origin = mode
    elif identity and mode == 'api' and trusted:
        origin = 'native'
    else:
        origin = 'unknown'
    env = 'mock' if mode == 'mock' else (
        environment if trusted and environment in ('production', 'test', 'development', 'mock')
        else 'unknown')
    try:
        SourceRef.model_validate(data)
        coverage = 'complete'
    except ValidationError:
        coverage = 'unknown'
    def string_field(key):
        item = data.get(key)
        return item if isinstance(item, str) and item.strip() else None

    return QuantitySource(
        reference=reference, project_id=project_id, object_kind=object_kind, object_id=object_id,
        system=string_field('system'), source_type=string_field('object_type'),
        external_id=string_field('external_id'), version=version if type(version) in (int, str) else None,
        namespace=namespace, origin=origin, environment=env,
        occurred_at=_time(data.get('occurred_at')), collected_at=_time(data.get('collected_at')),
        coverage=coverage, value=value, unit=unit, meaning=meaning,
    )


def quantity(value: str | None, unit: str, meaning: str, sources: list[QuantitySource], *,
             fact_role: str = 'confirmed', coverage: str | None = None) -> ProvenancedQuantity:
    unique = {}
    for source in sources:
        if source.reference in unique and unique[source.reference] != source:
            raise ValueError('conflicting source reference')
        unique[source.reference] = source
    refs = list(unique.values())
    coverages = [source.coverage for source in refs] or ['unknown']
    if coverage is not None:
        if coverage not in _COVERAGE_ORDER:
            raise ValueError('invalid coverage')
        coverages.append(coverage)

    def earliest(attribute: str) -> datetime | None:
        times = [getattr(source, attribute) for source in refs]
        return min(times) if times and all(time is not None for time in times) else None

    return ProvenancedQuantity(
        value=value, unit=unit, meaning=meaning,
        origins=sorted({source.origin for source in refs}),
        environments=sorted({source.environment for source in refs}),
        fact_role=fact_role if refs else 'unknown', observed_at=earliest('occurred_at'),
        collected_at=earliest('collected_at'), coverage=min(coverages, key=_COVERAGE_ORDER.get),
        source_refs=refs, input_refs=[source.reference for source in refs],
    )


def source_modes(quantities) -> list[str]:
    return sorted({'api' if origin == 'native' else origin
                   for item in quantities for origin in item.origins})
