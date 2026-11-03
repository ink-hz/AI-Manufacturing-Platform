# Task 3 — SAP/WMS/MES authority and workflow bridge

Base: `f60cba724e508db35a32907bc28389f6282a6d4e`. Worktree: `/Users/neo/.codex/worktrees/a065/AI-Manufacturing-Platform`.

Implementation follows the brief and controller decisions in `task-3-decisions.md`. Only core source/bridge code, focused domain helpers/readers, tests and this report are owned. No deployment, network access, production data change, customer document edit, raw-file edit, or enterprise runtime implementation is included.

## Delivered behavior

- Real separate SAP/WMS/MES stores, immutable operations/facts/source receipts, durable business rejection with no source effects, query recovery after commit, exact producer/consumer replay, and genuine existing workflow projections. Default service composition registers the three core families lazily; production remains unavailable. Other families stay unregistered until Task4.
- SAP owns orders, work orders, plans, actual BOM/purchase request contexts and accounting. WMS owns receipt, qualification-derived reservation, custody/location transfer, pick/return, stocktake, logical reservation release and shipment. MES owns receipt-scoped IQC, pre-start preparation, physical start/execution/consumption, component genealogy, stop/resume, current containment, release, completion and ECO split/cancellation.
- The 12 required / 10 received / 8 qualified flow rejects reservation12, picks8, and posts each source movement once. Replenishment4 yields 14 received / 12 qualified / 2 rejected and reservation12. Pending receipt accounting never invents qualification. Completion never repeats execution consumption.
- Exact location AND custodian are required for custody transfers; owner remains a separate dimension. Positive stocktake discrepancy remains pending; qualified loss may only remove unreserved warehouse stock. Supplier return reduces physical stock; line-to-warehouse return changes custody while preserving reservation.
- Completion with consumption1 and return11 leaves original reservation12, consumed1, line-side0 and no generally available portion. Explicit `wms.release_reservation`11 leaves effective reservation1 and unused warehouse11 available. Re-picking through the released allocation rejects, while a valid new reservation/pick11 succeeds once. Original accepted receipt and reservation row remain12; release creates neither receipt stock nor SAP posting.
- Existing public reservation/start/interrupt/resume/freeze/shipment/ECO commands route new OEM intents to core adapters. Old ERP work orders, profiles and receipt sequences stay pinned. Direct typed controls use the same one-time domain preparation. Public stop severity is read from its exact prepared exception; the legacy StopPayload bytes are unchanged.
- Start/pass/resume validate real current HR employment, present shift, station qualification, PLC state/program and MES preparation before source effect. Resume retains fresh attestation keys in its immutable caused_by list, while original start history stays unchanged. Current deactivation, stale evidence, unavailable equipment and absent required family facts fail closed.
- MES hold acknowledgment gates require actual durable WMS and SAP acceptance. Frozen or pending/failed/unknown acknowledgment blocks physical actions; unfreeze references exact current selected member holds. Proactive hold without quality source is possible only through exact authorized immutable preparation. Stale release cannot clear newer hold. A reproduced source-accepted/local-held start race retains the accepted source receipt and local start_pending, then permits actual scoped safety stop.
- Completion requires the exact latest admitted matching route events and exact source consumption. Manufacturing/quality release requires current qualified test evidence. Shipment validates all selected units against current matching manufacturing and quality releases. Actual shipment consumption emits one MES delivery context per participating WO/subset, all citing the same actual WMS shipment.
- ECO split preserves retained accepted membership and creates the prepared replacement WO with actual `mes.revision_switch` provenance. Empty retained set is valid only for split-specific scope; global start/shipment UnitScope remains nonempty. Cancel remaining emits a distinct actual cancellation fact, no replacement WO. retain_existing remains the existing local command.
- Native source receipt/IQC reconciles existing manual observations using the original inspection_target rules and optional explicit manual_iqc_id; no duplicate physical or qualified quantity, no relabeling of manual records.

## Published interfaces for Tasks 4/5/6

### Composition, guard and source observations

- `core_systems.register_core(registry)` registers `SapSystem`, `WmsSystem`, `MesSystem` factories and their separate `CoreAuthorityAdapter` factories. `WorkflowService(..., configure_systems=None)` uses that composition by default; a supplied callback controls composition for tests/later tasks.
- Each SystemAdapter implements pure `query(project_id, operation_id)`, `query_delivery(project_id, delivery_id)`, `fact(project_id, SourceKey)`, `facts(...)`, and genuine `execute/consume`. Do not confuse these with the old exchange protocol.
- `core_authority.CoreAuthorityAdapter(system, registry)` implements `submit(ExternalRequest)`, `query(system, business_key)`, `snapshot(system, object_type)` and `stock_basis(ExternalRequest)`. The separate existing ERP MockAuthorityAdapter is unchanged. Full original request hash/bytes and original receipt JSON are preserved; queries do not advance source business state. Stock proof checks exact original project/system/exchange/reservation and receipt hash, and returns original physical provenance, not a rewritten smaller receipt.
- `core_guards.project_guard(registry, project_id)` is the shared dataset/project cross-process flock. **Task4 HR, PLC, product-test and other eligibility mutations must use this same guard.** Acquire before any source/workflow writer, never nest acquisition. Path aliases/symlinks and multi-link guard files reject.
- `SourceSnapshot(registry, project_id)` reads actual existing producer stores and durable acknowledgments under that guard, before opening the owning source writer. Methods: `fact(key)`, `of_type(tag)`, `containment(lot_ids=(), unit_ids=())`, `acknowledged(fact)`. No cross-system SQL transaction nesting; no source I/O from workflow projection/application. Producer acknowledgment is also recorded under the shared guard after the actual consumer commit.
- `core_eligibility.validate_eligibility(operation, observations, now) -> list[SourceKey]` is pure and returns the exact employee/shift/equipment/station qualification/process request/preparation attestations. `current_start(operation, original_start_fact, observations, now) -> SystemOperation` constructs a typed start-shaped current eligibility check for resume, preserving original operator identity and unit/WO/revision scope. It does not write or relabel the original start.

### Projection/admission and IDs

- `core_projections.validate_fact(tx, context, fact)` performs narrow domain validation; `project_fact(tx, context, fact) -> ProjectionResult` persists through shared domain helpers. Source execution invokes the same validation before its source writer; later workflow application validates again against current state.
- `domain_id(fact)` is UUID5(NAMESPACE_URL, colon-joined full project/system/object_type/external_id/version). SAP order/WO/plan use this explicit map. Plan requirement IDs, material-lot IDs, selected unit IDs, supplied shipment/interruption IDs and prepared replacement WO IDs remain actual declared IDs. Existing domain handlers that allocate IDs return their actual ID in ProjectionResult and integration links; consumers must resolve that mapping.
- Narrow validate→persist phases were extracted in orders, engineering, supply, execution, quality and laboratory. Public wrappers remain strict. `_record_execution(..., trusted_fact=fact)`, `_record_test(..., trusted_fact=fact)` and `_install(..., trusted_fact=fact)` are internal trusted paths, not public bypasses.
- `core_admission.execution_command`, `validate_execution_admission`, `test_command`, `validate_test_admission`, `project_test_fact`, `admitted_component_source` define exact trusted translation/admission. Readers require complete SourceKey, canonical fact/hash, project, target/unit/WO/revision and stored scope. Execution and test admissions retain actual typed IntegrationFact; public manual-source commands are not widened. Component history exposes actual source when present and omits it for legacy None.
- `core_preparation.prepare_core_effect(tx, context, operation)` creates one-time existing domain requests. `bound_requests(...)`, `ensure_core_tables(...)`, and `project_bound_effect(...)` preserve immutable request/wire associations. `integration_core_bindings` and `integration_core_receipts` reject update/delete/replace. Actual source wire observations are collected outside workflow TX, stored before CAS/reauthorization, and later applied without external I/O.

### Closed contract/catalog changes (undeployed new integration wire only)

There are now 47 operation variants and 60 fact variants. Existing ExternalRequest/ExternalReceipt, PackageItem and engineering revision wire remain unchanged.

- `mes.prepare`: `MesPrepare/PreparationData(work_order_id, unit_ids[1..500 unique], test_plan_id, equipment_id, approval_target=None)`. Emits `mes.preparation`, per-unit/station `mes.process_request`, per-unit `mes.test_request`, and optional exact engineering/quality `mes.approval_request`. Real WO/revision/test-plan/equipment/unit scope is required. Base policy is work_order.register; approval target additionally requires npi.review or nonconformance.disposition. `mes.start` now emits only start. `mes.release` emits only release, never a future shipment context.
- `RevisionData.bom_materials: list[BomMaterial]` is required, nonempty, unique material_id. Each row has `material_id` and `per_unit: PositiveAmount(quantity, unit, scale)`. These are actual BOM rows, distinct from PackageItem document metadata. SAP release_work_order emits BOM request from the exact released PDM rows/revision before plan. Purchase requirement emits from actual plan requirements and actual order due date. Task4 must produce/confirm these rows truthfully.
- `ReceiptData.custodian` is required, independent of owner and location. `InspectionData.manual_iqc_id: UUID | None` is optional and reuses exact existing manual reconciliation rules.
- `StocktakeData.quality_state` is required (`pending|qualified`). WmsReturn/WmsReturnFact require `direction` (`to_warehouse|to_supplier`). OwnershipBalance adds optional nonzero signed adjustment; zero omits from old serialization.
- `ShipmentData.releases` is the canonical nonempty unique list of exact MES release SourceKeys; it replaces singular release in the new wire. `MesDeliveryContext.releases` is also canonical. WMS validates both current release kinds for every exact selected unit/WO/revision/order/owner. MES produces per-WO/subset contexts only after consuming real WMS shipment; Task4 customer/overseas claims must prove all selected units are covered by actual contexts, not assume one context covers every shipment unit.
- `InterruptData.start_id` optionally scopes safety stop to an actual accepted start. `SwitchData.units` allows empty retained membership only in this subtype. `MesSwitchRevisionFact` adds required actual replacement_work_order_id and remaining_amount. `mes.cancel_remaining`/`mes.remaining_cancellation` has work_order_id, eco_id, unique retained_unit_ids, evidence; output adds remaining_amount. Both remain under existing eco.switch policy.
- `ContainmentData.work_order_id` is optional for valid public multi-WO/project scope. `cause` may be absent only for prepared frozen scope; `additional_causes` supports multiple current holds. Unfrozen requires nonempty unique exact hold causes and WMS/SAP acknowledgments. Initiating actor/prepared request/audit remain separate from quality provenance.
- `sap.receipt_posting`: exact WMS receipt cause, material_lot_id/material_id/owner_id, actual received amount, account, posted_at. It posts pending receipt, not qualified allocation. `sap.shipment_posting`: exact WMS shipment cause, shipment_id/order_line_id, exact units/finished amount/account/posted_at. `sap.variance_posting`: signed counted-minus-expected via explicit StocktakeData plus raw-variance account. Existing accounting/completion fact variants add optional posted_at; actual SAP producers always set it on commit. `wms.consumption` mirrors exact real MES execution/allocations once; it is not second consumption.
- `wms.release_reservation`: `ReservationReleaseData(work_order_id, reservation: exact WMS reservation SourceKey, allocations: MaterialAllocation[], cause, evidence)`; every allocation must cite that original reservation. Actual cause must be same-WO warehouse return/completion/cancellation. Output `wms.reservation_release` enriches allocations with actual original receipt key and mapped reservation_id (`ReleasedAllocation`). Positive unused warehouse-held scope only, exact qualified lot/material/owner/dimensions, no consumed or line-side amount; frozen scope rejects. Policy reservation.request. Edge to MES only; deliberately no SAP financial edge.
- Fixed FACT_POLICIES includes all consumer-only facts; variance, pending receipt, shipment, consumption, test/approval/delivery contexts have explicit typed FactPolicy entries. SAP BI edges include actual new accounting variants. Closed union roundtrip/extra-field tests and typed policy coverage include the changes.

### Reservation release storage/read model

- `core_reservations.released_quantity(observations, reservation, qualification=None, lot_id=None)` gives actual immutable source release amount. `prepare_release`, `validate_release`, `validate_projection`, `project_release` are the source/bridge phases; `validate_requirement_budget(payload, observations)` also counts unprojected source reservations, net of releases, against actual SAP requirement scope. `released_basis_atoms(tx, project_id, reservation_id, system, external_id, version)` adjusts active capacity claims against original receipt evidence.
- Additive `integration_reservation_releases` key: project/system/object_type/external_id/version/reservation_id/qualification_key; columns include original receipt identity, positive q_atoms, canonical payload_hash and timestamp. Immutable insert-replace/update/delete triggers; deferred full-source FK to integration_projections. Projection receipt rows are not changed.
- `effective_reservations` contains original reservation columns with confirmed_atoms reduced by admitted release deltas, plus original_confirmed_atoms and released_atoms. The delta sum joins full projection identity and canonical payload_hash. Capacity, readiness, consumption, current scoped freeze and availability readers use the net view. Original history and stock-proof receipt joins use original rows, with active stock-basis allocation capacity reduced by releases.
- ReservationValue.confirmed is effective/net, `released` is nonzero-only, remaining is requested minus original confirmation; release never becomes unconfirmed demand. Original exchange receipt still reports its immutable accepted quantity. For the completed-unused proof, requested12 = confirmed1 + released11 + rejected0 + unconfirmed0. Existing zero-release wire serialization is unchanged.
- `initialize_reservation_releases(tx)` initializes the additive ledger/view on existing pre-release schema23. WorkflowStore invokes it only if the view is absent, after dataset/version validation. Fresh and source22→23 migrations include the same DDL. No version24 and no historical row rewrite. Old v2/v3/v4 synthetic schema fixtures now drop this new view when constructing their historical schema.

## Explicit Task4 boundaries and remaining family checks

- Core tests register **test-only prerequisite producers** for PDM, HR, PLC, OA and product-test; no runtime fake approval/qualification/test producer is registered. These are core control proofs, not enterprise/evidence family acceptance.
- Product-test fixture stores owned original artifact bytes, version and SHA256, then passes a real typed product_test.test through the extracted qualified laboratory path. Task4 must implement actual immutable artifact storage/read validation, run/input/request/equipment/process/measurements consistency, original bytes/hash/version, source observation timing and current eligibility under the shared guard. Do not replace this with metadata-only test evidence or public manual provenance. Public test_run.finish remains manual-only; trusted helper is internal.
- PDM real release/BOM confirmation, HR active/training/attendance policies, OA request/decision governance, PLC session/sample/readback, customer/overseas acceptance, SRM and BI actual business consequences remain Task4. Merely retaining their network facts is not proof of those consequences.
- Replacement ECN path is explicitly supported by sap.publish_plan against the actual projected replacement WO through supply.validate_plan with current revision/order input versions; its purchase requirement targets that actual replacement ID. mes.prepare resolves mes.revision_switch→released PDM revision, covered by the replacement preparation test. **No replacement-specific SAP BOM synchronization request/confirmation gate exists yet**: original BOM request is emitted on sap.release_work_order only. Controller accepted this named Task4 enterprise-to-core boundary; Task4 must resolve it without duplicate WO import, relabeling MES provenance or plan-before-BOM circularity.
- WMS balance reads its own committed observations, so its consumption mirror may lag MES until delivery; physical custody guards additionally consult the guarded actual MES execution snapshot immediately. Current authoritative source observations precede workflow projection, so a physical fact may legitimately exist while local application is unknown/held. The receipt remains accepted and immutable; query/pull retries reconcile it without repeating physical effects. No guarantee of a distributed atomic source+workflow commit is claimed.

## TDD and verification evidence

All commands ran in this worktree with Python3.11 at `/Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python`, `PYTHONPATH=src`, and `TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform`. Earlier RED/GREEN milestones established the real 12/10/8 path, preparation/admission, control facade, split/cancel, multi-WO shipment, current hold/ack gates, physical location/custody, manual reconciliation and explicit release. No SQL insertion of fake ready/approved/accepted business states is used in the core rig; SQL is limited to source/artifact persistence, read assertions, fault configuration and schema migration fixtures.

Concrete captured regression cycles (full commands use the environment prefix above):

```text
python -m pytest -q tests/workflow/integrations/test_core_flow.py -k 'stop_resume or stock_proof or release_reservation'
RED: 1 failed, 1 passed, 46 deselected; valid refreshed PLC resume rejected: "PLC equipment observation is stale".
python -m pytest -q tests/workflow/integrations/test_core_flow.py -k 'stop_resume or stock_proof or release or training'
GREEN: 8 passed, 40 deselected in 4.84s.

python -m pytest -q tests/workflow/integrations/test_core_flow.py -k older_passed
RED: 1 failed, 48 deselected; older passed route completion DID NOT RAISE.
python -m pytest -q tests/workflow/integrations/test_core_flow.py -k 'completion or replenishment' tests/workflow/integrations/test_core_compatibility.py
GREEN: 4 passed, 50 deselected in 2.74s (the -k filter excludes unrelated compatibility tests).

python -m pytest -q tests/workflow/integrations/test_core_flow.py tests/workflow/integrations/test_core_compatibility.py tests/workflow/integrations/test_contracts.py tests/workflow/integrations/test_profile_migration.py
RED: 2 failed, 185 passed in 25.58s; existing schema23 lacked effective_reservations; a test cleanup accidentally removed a used local binding (restored).
python -m pytest -q tests/workflow/integrations/test_core_compatibility.py tests/workflow/integrations/test_profile_migration.py tests/workflow/integrations/test_core_flow.py -k 'schema23 or prepare_precedes or replenishment or completion or reservation_release'
GREEN: 8 passed, 56 deselected in 4.36s.

python -m pytest -q tests/workflow/integrations/test_operation_boundary.py -k all_closed_fact
RED: 1 failed, 35 deselected; consumer variance policy was a string instead of FactPolicy.
python -m pytest -q tests/workflow/integrations/test_operation_boundary.py -k all_closed_fact tests/workflow/test_supply.py tests/workflow/test_engineering_readiness.py -k 'migration or migrates or all_closed_fact'
GREEN: 5 passed, 79 deselected in 1.02s after typed policy and historical schema-fixture correction.
python -m pytest -q tests/workflow/integrations/test_core_flow.py -k stocktake tests/workflow/test_exchanges.py -k 'production_never or stocktake'
GREEN: 3 passed, 66 deselected in 1.10s, including actual variance posting pull and retained old module adapter export.

python -m pytest -q tests/workflow/integrations/test_core_flow.py -k scoped_safety_stop
RED: 1 failed, 48 deselected; source interruption kind was 'other' instead of original 'S4'.
python -m pytest -q tests/workflow/integrations/test_core_flow.py -k 'scoped_safety_stop or stop_resume'
GREEN: 2 passed, 47 deselected in 1.52s.
```

The source22 wire/proof golden fixture was generated from actual old commit `b0c61bfc856625b21e2c709747341f2a78f17e38` in isolated `/tmp/it-mock-core-old22`, using that commit's MockAuthorityAdapter to receive/inspect/submit/stock_basis. Expected original request/receipt/hash/proof and source SQL are stored in `tests/workflow/integrations/legacy22_authority.py`; they were not regenerated using the new implementation. Schema23 replay asserts exact bytes/hash/proof and one original operation row.

A final conservation RED extended the explicit-release test through new reservation and the existing ownership reader:

```text
python -m pytest -q tests/workflow/integrations/test_core_flow.py -k explicit_reservation_release
RED: 1 failed, 48 deselected in 1.18s; after release11/re-reserve11, historical proof counted received23/balance22 instead of received12/balance11.
python -m pytest -q tests/workflow/integrations/test_core_flow.py -k 'explicit_reservation_release or stock_proof or replenishment'
GREEN: 3 passed, 46 deselected in 1.94s after stock_evidence subtracts admitted release amounts from active claims. Original physical receipt quantity and historical receipt bytes remain unchanged.
```

Final verification after the release/read-model fix and all code edits:

```sh
PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q tests/workflow/integrations/test_core_flow.py tests/workflow/integrations/test_core_compatibility.py tests/workflow/test_execution.py tests/workflow/test_eco.py tests/workflow/test_trace_freeze.py tests/workflow/test_imports.py tests/workflow/test_exchanges.py
# 225 passed in 98.95s (0:01:38)

PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q tests/workflow/integrations/test_contracts.py tests/workflow/integrations/test_store_network.py tests/workflow/integrations/test_operation_boundary.py tests/workflow/integrations/test_profile_migration.py tests/workflow/test_quality.py tests/workflow/test_supply.py tests/workflow/test_material_handoffs.py tests/workflow/test_laboratory.py tests/workflow/test_engineering_readiness.py
# 346 passed in 64.86s (0:01:04)

git diff --check
# exit 0, no output
```

Ruff `check --select F` over all 48 explicitly owned Python paths: `All checks passed!`. New/modified integration files were formatted. **571 passing tests across the two final suites, no warnings or failures.** Earlier full-suite failures were corrected before these final runs: historical schema fixtures dropping columns while the new view still existed, and a removed compatibility module export used by production guard instrumentation. Task3 implementation is complete and ready for controller/spec/code review; enterprise family acceptance remains explicitly Task4.

## Owned changed paths
- `src/manufacturing_platform/workflow/delivery.py`
- `src/manufacturing_platform/workflow/delivery_models.py`
- `src/manufacturing_platform/workflow/eco.py`
- `src/manufacturing_platform/workflow/engineering.py`
- `src/manufacturing_platform/workflow/exchange_models.py`
- `src/manufacturing_platform/workflow/exchanges.py`
- `src/manufacturing_platform/workflow/execution.py`
- `src/manufacturing_platform/workflow/freeze.py`
- `src/manufacturing_platform/workflow/genealogy_models.py`
- `src/manufacturing_platform/workflow/integrations/browse.py`
- `src/manufacturing_platform/workflow/integrations/catalog.py`
- `src/manufacturing_platform/workflow/integrations/contracts.py`
- `src/manufacturing_platform/workflow/integrations/core_admission.py`
- `src/manufacturing_platform/workflow/integrations/core_authority.py`
- `src/manufacturing_platform/workflow/integrations/core_eligibility.py`
- `src/manufacturing_platform/workflow/integrations/core_guards.py`
- `src/manufacturing_platform/workflow/integrations/core_inventory.py`
- `src/manufacturing_platform/workflow/integrations/core_mes.py`
- `src/manufacturing_platform/workflow/integrations/core_mes_contexts.py`
- `src/manufacturing_platform/workflow/integrations/core_models.py`
- `src/manufacturing_platform/workflow/integrations/core_preparation.py`
- `src/manufacturing_platform/workflow/integrations/core_projections.py`
- `src/manufacturing_platform/workflow/integrations/core_reservations.py`
- `src/manufacturing_platform/workflow/integrations/core_sap.py`
- `src/manufacturing_platform/workflow/integrations/core_systems.py`
- `src/manufacturing_platform/workflow/integrations/core_wms.py`
- `src/manufacturing_platform/workflow/integrations/enterprise_models.py`
- `src/manufacturing_platform/workflow/integrations/network.py`
- `src/manufacturing_platform/workflow/integrations/operations.py`
- `src/manufacturing_platform/workflow/integrations/routing.py`
- `src/manufacturing_platform/workflow/integrations/schema.py`
- `src/manufacturing_platform/workflow/laboratory.py`
- `src/manufacturing_platform/workflow/laboratory_readers.py`
- `src/manufacturing_platform/workflow/orders.py`
- `src/manufacturing_platform/workflow/ownership.py`
- `src/manufacturing_platform/workflow/quality.py`
- `src/manufacturing_platform/workflow/readiness.py`
- `src/manufacturing_platform/workflow/service.py`
- `src/manufacturing_platform/workflow/store.py`
- `src/manufacturing_platform/workflow/supply.py`
- `tests/workflow/integrations/legacy22_authority.py`
- `tests/workflow/integrations/support.py`
- `tests/workflow/integrations/test_contracts.py`
- `tests/workflow/integrations/test_core_compatibility.py`
- `tests/workflow/integrations/test_core_flow.py`
- `tests/workflow/integrations/test_operation_boundary.py`
- `tests/workflow/test_engineering_readiness.py`
- `tests/workflow/test_supply.py`
- `.superpowers/sdd/it-mock-20261103/task-3-report.md`

## Self-review

- Reviewed full source→domain ownership, every new operation/fact and explicit catalog policy, original wire hashing/receipt storage, savepoint rejection path, source effect order and query recovery, guard acquisition/snapshot order, actual source→domain IDs, and effective versus historical reservation reads.
- Reduced unrelated formatter churn in legacy files by restoring AST-identical original functions/methods. Shared public wrappers and ERP authority implementation retain their behavior and original wire. Retained MockAuthorityAdapter module export for existing production guard instrumentation.
- Checked actual two-process competing reservation proof, exact source22 golden replay, schema21/22 and existing23 initialization, original manual reconciliation, new-model closed union/policy coverage, current attestation resume, source-accepted held-start safety stop, and release/re-reservation physical/read-model conservation.
- Core source modules are split by authority, admission, preparation, eligibility, context emission, inventory reading and logical reservation release. No whole-workflow preview/copy engine, generic extensibility framework, direct SQL fake business-state seed, or runtime enterprise prerequisite fallback was added.
- Remaining family acceptance and replacement BOM synchronization are explicitly assigned above to Task4; no deployment or online dataset mutation is claimed.
