from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from manufacturing_platform.workflow.contracts import (
    ContractPolicy,
    ProjectCreate,
    Quantity,
)


def test_contract_boolean_rejects_coercion():
    with pytest.raises(ValidationError):
        ContractPolicy(
            customer_approval_required="false",
            customer_release_required=False,
            acceptance_required=False,
            customer_revision="a",
            internal_revision="a",
            material_ownership_rules="a",
        )


def test_fractional_quantity_is_exact_and_rejects_float():
    body = {
        "operation_id": str(uuid4()),
        "name": "a",
        "line_id": "a",
        "product": "a",
        "customer_id": "a",
        "mode": "internal",
        "unit": {"code": "kg", "scale": 2},
        "quantity": 1.25,
        "contract": {
            "customer_approval_required": False,
            "customer_release_required": False,
            "acceptance_required": False,
            "customer_revision": "a",
            "internal_revision": "a",
            "material_ownership_rules": "a",
        },
    }
    with pytest.raises(ValidationError):
        ProjectCreate.model_validate(body)


def test_shared_quantity_contract_requires_positive_canonical_decimal_string():
    adapter = TypeAdapter(Quantity)
    assert str(adapter.validate_python("1.250")) == "1.250"
    for value in (1.25, 1, "0", "-1", "01", "1e2", "NaN"):
        with pytest.raises(ValidationError):
            adapter.validate_python(value)
