from typing import Literal
from uuid import UUID
from pydantic import Field
from .commands import WorkflowCommand


class BindMesOrder(WorkflowCommand):
    action: Literal['mes_order.bind']
    work_order_id: UUID
    shop_order: str = Field(min_length=1, max_length=128)
    replace_binding_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=1000)


class RefreshMesOrder(WorkflowCommand):
    action: Literal['mes_order.refresh']
    work_order_id: UUID
    binding_id: UUID
