"""Bounded, strict inputs for manually recorded business controls."""
from datetime import date, datetime
import re
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BeforeValidator, Field, StringConstraints, model_validator
from .models import Model
from .catalog import Identifier
from .project_models import Text as TaskOwner

Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, max_length=2000)]
Name = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=300)]
Notes = Annotated[str, StringConstraints(strict=True, max_length=6000)]
Flag = Annotated[bool, Field(strict=True)]
Version = Annotated[int, Field(strict=True, ge=1)]
Method = Literal['unknown','manual','file','api']


def calendar(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Expected calendar date')
    return value


def instant(value):
    if not isinstance(value, str):
        raise ValueError('Expected external event time')
    parsed = datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Event time requires timezone')
    return value


Day = Annotated[date, BeforeValidator(calendar)]
EventTime = Annotated[datetime, BeforeValidator(instant)]


class Operation(Model):
    operation_id: UUID


class Change(Operation):
    expected_version: Version


class SystemFields(Model):
    name: Name
    kind: Name
    line_ids: Annotated[list[Identifier], Field(min_length=1,max_length=100)]
    business_owner: Text = ''
    it_owner: Text = ''
    usage: Literal['unverified','purchased_unused','used_bypassed','manual_effective','missing'] = 'unverified'
    method: Method = 'unknown'
    notes: Notes = ''
    active: Flag = True


class SystemCreate(SystemFields, Operation):
    pass


class SystemPatch(Change):
    name: Name = None
    kind: Name = None
    line_ids: Annotated[list[Identifier], Field(min_length=1,max_length=100)] = None
    business_owner: Text = None
    it_owner: Text = None
    usage: Literal['unverified','purchased_unused','used_bypassed','manual_effective','missing'] = None
    method: Method = None
    notes: Notes = None
    active: Flag = None


ObjectType = Literal['material','ebom','mbom','work_order','inventory','inspection','equipment']


class AuthorityFields(Model):
    line_id: Identifier
    object_type: ObjectType
    system_id: Name
    entry_point: Name
    owner: Name
    notes: Notes = ''
    active: Flag = True


class AuthorityCreate(AuthorityFields, Operation):
    pass


class AuthorityPatch(Change):
    line_id: Identifier = None
    object_type: ObjectType = None
    system_id: Name = None
    entry_point: Name = None
    owner: Name = None
    notes: Notes = None
    active: Flag = None


class PackageItem(Model):
    id: Identifier
    kind: Literal['ebom','mbom','drawing','route','sop','firmware','test_program','test_spec','other']
    title: Name
    source_system_id: Name | None = None
    source_name: Text = ''
    source_ref: Text = ''
    revision: Text = ''
    evidence: Text = ''
    owner: Text = ''
    status: Literal['pending','verified','na'] = 'pending'
    reason: Text = ''


class UniqueItems(Model):
    @model_validator(mode='after')
    def unique_items(self):
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError('Duplicate item IDs')
        return self


class PackageFields(UniqueItems):
    title: Name
    product_ref: Text = ''
    scope: Text = ''
    provider: Text = ''
    owner: Text = ''
    customer_version: Text = ''
    internal_version: Text = ''
    approval_party: Text = ''
    approval_status: Literal['unknown','confirmed','not_required'] = 'unknown'
    approval_evidence: Text = ''
    items: Annotated[list[PackageItem], Field(min_length=1,max_length=200)]


class PackageCreate(PackageFields, Operation):
    pass


class PackageWrite(PackageFields, Change):
    pass


class PackageAction(Change):
    action: Literal['submit','verify','return','revise','invalidate']
    reason: Text = ''


class HandoffCreate(Operation):
    package_id: Name
    from_party: Name
    to_party: Name
    to_system_id: Name | None = None
    owner: Name
    due_date: Day | None = None
    method: Method = 'manual'
    evidence: Text = ''
    occurred_at: EventTime | None = None


class HandoffAction(Change):
    action: Literal['send','receive','return','cancel']
    received_revision: Version | None = None
    evidence: Text = ''
    occurred_at: EventTime | None = None
    reason: Text = ''


class ReadinessItem(Model):
    id: Identifier
    kind: Literal['version','materials','equipment','people','first_article','customer','customer_material']
    label: Name
    required: Flag = True
    owner: Text = ''
    due_date: Day | None = None
    status: Literal['pending','verified','blocked','na'] = 'pending'
    evidence: Text = ''
    source_ref: Text = ''
    source_system_id: Name | None = None
    reason: Text = ''
    valid_until: Day | None = None
    package_item_id: Identifier | None = None
    supply_mode: Literal['unknown','self','customer','mixed'] = 'unknown'
    first_article_result: Literal['unknown','planned','passed','failed','na'] = 'unknown'


class ReadinessCreate(UniqueItems, Operation):
    title: Name
    package_id: Name
    work_order_ref: Name
    scope: Name
    planned_use_date: Day
    required: Flag = True
    owner: Name
    items: Annotated[list[ReadinessItem], Field(min_length=1,max_length=200)]


class ReadinessWrite(UniqueItems, Change):
    items: Annotated[list[ReadinessItem], Field(min_length=1,max_length=200)]


class IssueCreate(Operation):
    item_id: Identifier
    title: Name
    owner: TaskOwner = ''
    due_date: Day | None = None
    priority: Literal['normal','high','urgent'] = 'normal'
    notes: Notes = ''
