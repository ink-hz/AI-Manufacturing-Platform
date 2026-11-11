# Task 1 report

Red: `PYTHONPATH=src /private/tmp/manufacturing-contract-py311/bin/python -m pytest -q tests/workflow/test_material_control.py` — 2 failed as expected: project route returned 404; overview route returned 404 without `total`.

Green: focused test suite: 4 passed. Regression command: `PYTHONPATH=src /private/tmp/manufacturing-contract-py311/bin/python -m pytest -q tests/workflow/test_material_control.py tests/workflow/test_supply.py tests/workflow/test_expedites.py tests/workflow/test_expedite_tasks.py tests/workflow/test_material_handoffs.py tests/workflow/test_receipt_expedite_flags.py` — 102 passed in 29.10s.

Contract:
- Overview: `{items: [{project_id, name, customer_id, product, work_order_count, requirement_count, open_expedite_count, unreceived_handoff_count, coverage_issues, source_modes}], total, limit, offset, read_at}`. Counts cover each complete authorized project, not just the page. `unreceived_handoff_count` counts pending handoffs.
- Project: `{project_id, project_version, read_at, coverage_issues, source_modes, work_orders, requirements, expedites, handoffs, receipts, issue_marks, total, limit, offset}`. `total` and pagination describe requirements after filters. Related arrays describe those paged requirements.
- Requirement: `{id, work_order_id, material_id, owner_id, unit, required, received, qualified, rejected, reserved, shortage, in_transit, need_at, need_at_basis, timing_risk, coverage_issues, expedite_ids, receipt_ids, handoff_ids}`. Quantities are decimal strings. `need_at_basis` is `work_order_planned_start_proxy`; timing risk is unknown.
- Related objects contain `id` and the existing detail-reader value; work orders additionally have `title`; receipts additionally have `qualified` equal to effective inspected accepted quantity. Sources remain on those existing values. All dates are serialized from the business clock or source values.

Limitations: Project pages return work orders and related evidence associated with paged requirements, not a complete project ledger. Evidence links use existing requirement lineage, receipt lot and work order facts; a handoff association does not imply inventory or physical availability. Related lists are capped at 200 per type per requirement and marked on overflow; provenance mode scans are bounded to 501 records per source table. Generic coverage notices mean absence is not evidence of external completeness. Existing object detail readers may themselves bound history or expose unbounded expedite progress. Timing remains unknown. A mock source mode is tested by seeding an existing record because public registration rejects mock source mode.

Files: `src/manufacturing_platform/workflow/{api.py,material_control.py,material_control_api.py,material_control_models.py}`, `tests/workflow/test_material_control.py`, and this report. No accounting writes are issued by the projection.
