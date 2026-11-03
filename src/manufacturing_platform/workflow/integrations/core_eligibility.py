"""Pure current HR/PLC eligibility over a guarded immutable source snapshot."""

from .core_guards import require


def validate_eligibility(operation, observations, now):
    p = operation.payload
    employee = observations.fact(p.operator)
    shift = observations.fact(p.shift)
    equipment = observations.fact(p.equipment)
    require(
        employee.payload.fact_type == "hr_sap.employee" and employee.payload.active,
        "Active authoritative employee required",
    )
    latest_employee = [
        f
        for f in observations.of_type("hr_sap.employee")
        if f.payload.employee_id == employee.payload.employee_id
    ][-1]
    require(
        latest_employee.source_key == p.operator and latest_employee.payload.active,
        "Employee source is no longer active/current",
    )
    require(
        shift.payload.fact_type == "hr_dingtalk.shift"
        and shift.payload.employee == p.operator
        and shift.payload.work_order_id == p.work_order_id
        and shift.payload.attendance == "present",
        "Matching present work order shift required",
    )
    require(
        shift.payload.starts_at <= p.occurred_at <= now <= shift.payload.ends_at,
        "Shift does not cover execution time",
    )
    latest_shift = [
        f
        for f in observations.of_type("hr_dingtalk.shift")
        if f.payload.employee == p.operator
        and f.payload.shift_id == shift.payload.shift_id
    ][-1]
    require(latest_shift.source_key == p.shift, "Current shift required")
    qualifications = [
        f
        for f in observations.of_type("hr_beisen.qualification")
        if f.payload.employee == p.operator
    ]
    latest = {}
    for f in qualifications:
        latest[f.payload.qualification] = f
    require(
        equipment.payload.fact_type == "plc.equipment"
        and equipment.payload.state == "available"
        and equipment.payload.observed_at <= p.occurred_at,
        "Current available PLC equipment required",
    )
    current_equipment = [
        f
        for f in observations.of_type("plc.equipment")
        if f.payload.equipment == equipment.payload.equipment
    ][-1]
    require(
        current_equipment.source_key == p.equipment,
        "PLC equipment observation is stale",
    )
    request = observations.fact(equipment.payload.process_request)
    require(
        request.payload.fact_type == "mes.process_request"
        and request.payload.work_order_id == p.work_order_id
        and request.payload.revision_id == p.revision_id
        and request.payload.equipment == equipment.payload.equipment
        and request.payload.program_version == equipment.payload.program_version,
        "Equipment acknowledgment must match prepared work order program",
    )
    qualification = latest.get(request.payload.station)
    require(
        qualification is not None
        and qualification.payload.valid_from
        <= p.occurred_at
        <= now
        <= qualification.payload.valid_until,
        "Current station training qualification required",
    )
    if p.operation == "mes.pass":
        require(
            request.payload.station == p.station
            and request.payload.unit_id == p.unit.unit_id,
            "Execution differs from actual PLC process request",
        )
    unit_ids = (
        {u.unit_id for u in p.units} if p.operation == "mes.start" else {p.unit.unit_id}
    )
    preparations = [
        f
        for f in observations.of_type("mes.preparation")
        if f.payload.work_order_id == p.work_order_id
        and f.payload.equipment_id == equipment.payload.equipment
        and unit_ids <= set(f.payload.unit_ids)
    ]
    require(bool(preparations), "Exact pre-start preparation required")

    return [
        employee.source_key,
        shift.source_key,
        equipment.source_key,
        qualification.source_key,
        request.source_key,
        preparations[-1].source_key,
    ]


def current_start(operation, start, observations, now):
    """Resume the original operator identity with current source attestations."""
    original_employee = observations.fact(start.payload.operator).payload.employee_id
    employees = [
        f
        for f in observations.of_type("hr_sap.employee")
        if f.payload.employee_id == original_employee
    ]
    employee = employees[-1]
    shifts = [
        f
        for f in observations.of_type("hr_dingtalk.shift")
        if f.payload.employee == employee.source_key
        and f.payload.work_order_id == start.payload.work_order_id
        and f.payload.starts_at <= now <= f.payload.ends_at
    ]
    equipment_id = observations.fact(start.payload.equipment).payload.equipment
    equipment = [
        f
        for f in observations.of_type("plc.equipment")
        if f.payload.equipment == equipment_id
    ]
    require(
        bool(shifts) and bool(equipment),
        "Current resume attendance and equipment required",
    )
    payload = start.payload.model_dump(mode="json", exclude={"fact_type"})
    payload.update(
        operation="mes.start",
        operator=employee.source_key,
        shift=shifts[-1].source_key,
        equipment=equipment[-1].source_key,
        occurred_at=now,
    )
    return type(operation)(
        operation_id=operation.operation_id,
        project_id=operation.project_id,
        system="mes",
        payload=payload,
    )
