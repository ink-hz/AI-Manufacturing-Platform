"""Small validated configuration with stable keys separate from display names."""
import json
from pathlib import Path
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from .models import Handoff, Model, Name, Participant, SystemRelationship

Identifier = Annotated[str, StringConstraints(strict=True, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$')]


class Group(Model):
    id: Identifier
    name: Name
    enabled: bool = True
    order: int


class Line(Group):
    group_id: Identifier
    stage_ids: Annotated[list[Identifier], Field(min_length=1)]
    description: str = ''


class Stage(Model):
    id: Identifier
    name: Name
    enabled: bool = True
    purpose: str
    help: str
    prompts: list[str]
    reference_participants: list[Participant]
    reference_handoffs: list[Handoff]
    reference_systems: list[SystemRelationship]


class Definition(Model):
    groups: Annotated[list[Group], Field(min_length=1)]
    lines: Annotated[list[Line], Field(min_length=1)]
    stages: Annotated[list[Stage], Field(min_length=1)]

    @model_validator(mode='after')
    def check_references(self):
        for items in (self.groups, self.lines, self.stages):
            if len({item.id for item in items}) != len(items):
                raise ValueError('Duplicate catalog ID')
        groups = {item.id for item in self.groups}
        stages = {item.id for item in self.stages}
        for line in self.lines:
            if line.group_id not in groups or not set(line.stage_ids) <= stages:
                raise ValueError('Unknown catalog reference')
            if len(line.stage_ids) != len(set(line.stage_ids)):
                raise ValueError('Duplicate stage reference')
        return self


class Catalog:
    def __init__(self, data):
        self.definition = Definition.model_validate(data)

    def line(self, line_id):
        enabled_groups = {g.id for g in self.definition.groups if g.enabled}
        for line in self.definition.lines:
            if line.id == line_id and line.enabled and line.group_id in enabled_groups:
                return line.model_dump()
        raise KeyError(line_id)

    def stage(self, line_id, stage_id):
        line = self.line(line_id)
        if stage_id in line['stage_ids']:
            for stage in self.definition.stages:
                if stage.id == stage_id and stage.enabled:
                    return stage.model_dump(exclude={'enabled'})
        raise KeyError(stage_id)

    def line_stages(self, line_id):
        line = self.line(line_id)
        enabled = {s.id for s in self.definition.stages if s.enabled}
        return [self.stage(line_id, stage_id) for stage_id in line['stage_ids'] if stage_id in enabled]

    def public(self):
        return {
            'groups': [g.model_dump() for g in sorted(self.definition.groups, key=lambda g: (g.order, g.id))],
            'lines': [line.model_dump() for line in sorted(self.definition.lines, key=lambda line: (line.order, line.id))],
            'stages': [s.model_dump(exclude={'enabled'}) for s in self.definition.stages if s.enabled],
        }


def load_catalog(path: str | Path | None = None):
    source = Path(path) if path is not None else Path(__file__).with_name('catalog.json')
    return Catalog(json.loads(source.read_text(encoding='utf-8')))
