"""Stable material-control read contract."""
from typing import Any
from pydantic import BaseModel


class MaterialControlPage(BaseModel):
    project_id: str
    project_version: int
    read_at: str
    coverage_issues: list[str]
    source_modes: list[str]
    work_orders: list[dict[str, Any]]
    requirements: list[dict[str, Any]]
    expedites: list[dict[str, Any]]
    handoffs: list[dict[str, Any]]
    receipts: list[dict[str, Any]]
    issue_marks: list[dict[str, Any]]
    material_task_counts: dict[str, int] = {}
    scope_total: int
    problem_counts: dict[str, int]
    total: int
    limit: int
    offset: int
