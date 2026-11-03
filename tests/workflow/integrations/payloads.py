"""Pytest-independent typed operation fixture data."""
from uuid import uuid4

def order_payload():
    return dict(
        operation="sap.release_order",
        demand_id=str(uuid4()),
        customer_id="C1",
        product="OEM",
        amount={"quantity": "2", "unit": "piece", "scale": 0},
        due_date="2027-01-01",
    )

