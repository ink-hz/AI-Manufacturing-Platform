# Task 4 — Remaining enterprise/evidence systems and complete directed network

Reviewed starting commit: `75ade376d2ea9dc13e60b1ca3edcfbce4ae457d7`. Worktree: `/Users/neo/.codex/worktrees/a065/AI-Manufacturing-Platform`.

Implementation uses the approved narrow family-validation hook and responsibility-focused modules. No deployment, network/production mutation, legacy ERP-wire change, public profile selector, grants/session fabrication, user architecture/handbook/discussion/README edits, or old SDD report edits are included. Existing unrelated dirty user files remain untouched and unstaged.

## Composition and durable lifecycle

- `enterprise_systems.EnterpriseSystem(system, store, registry)` implements PDM, CRM, OA, HR SAP, HR Beisen, HR DingTalk, SRM. `evidence_systems.EvidenceSystem(system, store, registry)` implements product-test, PLC, customer, overseas, BI. All fifteen IDs use distinct source stores.
- `register_enterprise_network(registry)` calls fixed core/enterprise/evidence registrations. Default `WorkflowService` uses it; an explicit `configure_systems` callback retains full control. Construction remains lazy; production availability rejects before opening source stores.
- `CoreSystem.validate_fact` is now an overridable static hook, defaulting to the original core validator. All families retain the same project flock, immutable snapshots, durable rejected receipt/savepoint, query-first replay, consumer-original hash verification, and accepted-source-versus-pending-projection lifecycle. No generic plugin engine, recursive WorkflowService execution, source mode relabel, or model_construct bypass.
- `SourceSnapshot.source_cutoffs` records each observed source's actual maximum fact sequence for BI. Other-store observations precede the owning source writer. HR/qualification/shift/PLC/test/calibration operations acquire exactly the shared core project guard.

## Enterprise consequences and exact interfaces

- PDM revision publication calls shared `engineering.validate_revision/record_revision`; BOM material identities/per-unit dimensions remain typed source evidence, distinct from document PackageItems. PDM changes validate exact released target revision, old WO and each explicit old-revision unit, then create the actual ECO through the existing domain path.
- `sap.request_bom(work_order_id)` explicitly reconciles an existing source-owned original or MES-created replacement WO. It derives the released PDM revision through existing core lineage; no duplicate WO or rewritten provenance is imported. Existing `sap.release_work_order` still emits its original request.
- SAP→PDM consumption creates `pdm.bom_confirmation` with `request`, `released_revision`, `work_order_id`, exact `bom_materials`, and canonical `bom_digest`. Confirmation creates a typed auxiliary record, never another engineering revision. SAP must durably acknowledge the exact response before a plan can pass. `bom_sync.plan_causes` verifies request/release/response/digest, exact material IDs and unit/scale, and total requirement quantity = per-unit BOM × effective WO obligation. Accepted plans retain these causal keys. Replacement tests prove pre-sync plan rejection, actual request/confirmation/new plan/new start, unchanged retained original unit.
- CRM demand creates actual reviewable demands through extracted `orders.validate_demand/_record_demand`. Product/customer/dimensions and existing supersession rules remain enforced; five-dimension reviews and formal SAP orders remain separate actions.
- OA requests/decisions are exact-target and exact-request bound. Engineering decisions call real NPI review; approved required blocked checks reject. Quality decisions use shared `quality.validate_disposition/disposition`, including actual NC/test/WO binding and independent rework route. Rejections remain typed decisions without applying an approval. OA never grants NPI bulk approval, manufacturing/quality release, or customer release.
- HR source facts produce closed `EmployeeRecord`, `QualificationRecord`, `ShiftRecord` (`HRRecord` union). Current employee identity/activity, training and shift references feed existing MES eligibility. Publishing HR evidence does not alter grants, users, sessions or platform qualifications; revoked application permissions and newly expired source training independently block start.
- SRM remains maturity `planned`. A real `srm.promise` creates a new supplied commitment ID through shared `supply.validate_commitment/_commit_supply(assigned_id=...)`, never the amend-existing branch. ASN/COA creates `SupplierNotice` expected-arrival evidence, linked to its promise; matching actual WMS receipts retain ASN source causes. ASN alone changes no receipt/IQC/physical quantity.

## Test artifacts, original bytes, PLC and failed observations

- New authorized operation `product_test.prepare_artifact` has only `run_id` and closed `template` choices `pass-v1`, `fail-v1`, `calibration-v1`. It is a distinct pinned intent/receipt before a run/calibration operation's payload is frozen. It does not finish a run, mark a pass, consume material, or create calibration.
- `product_test.artifact` returns `template` plus discriminated `PreparedTest`/`PreparedCalibration`. Prepared data contains the exact closed execute fields, `RawArtifactRef`, checksum, actual run/unit/plan/equipment/algorithm/version bindings and bounded measured/raw values. The UI selects a real run/template and uses these controlled fields; no arbitrary JSON/path/URL input is accepted.
- `test_artifacts.prepare`, `original_bytes`, `persist`, `resolve`, `validate_inline` own original canonical UTF-8 bytes in source-store `original_artifacts` BLOB rows, keyed by project/artifact/version/reference with SHA256. Update/delete/replace triggers enforce immutability. Exact stored byte hash and decoded original scope/values must match at execute; no reconstruction of current caller values is treated as original evidence.
- `WorkflowService.integration_artifact(actor, project_id, ref, checksum)` returns verified owned bytes after live project/source authorization. GET `/projects/{project_id}/systems/product_test/artifacts/{artifact_id}` under the existing workflow API prefix resolves the actual immutable prepare fact, returns JSON bytes with ETag/download name, and rejects another project. Generic authorized operation/fact routes already expose prepare/choice/recovery results.
- Actual product-test runs use Task3 `core_admission.project_test_fact` and shared qualified laboratory/quality validators. Original `mode='mock'`, source identity, raw_digest, immutable attempt and captured execution/rework basis survive. The public FinishTestRun model still rejects this mock provenance. Artifact byte checksum, integration fact hash, laboratory raw_digest and normalized parameter_digest remain distinct.
- Test occurrence/result/request/versions/equipment/fixture/algorithm/run/measurements are exact; latest current HR/shift/PLC eligibility is checked under the shared guard before physical source acceptance. Controlled out-of-limit samples persist an accepted source fact plus failed quality test and failed completed run; they do not become passes.
- Calibration uses shared extracted `laboratory.validate_calibration/record_calibration`, exact qualified run/plan, owned original parameter artifact. PLC readback is a separately executed actual observation with its own SourceKey/source_identity, exact product-test calibration cause, equipment/run/unit/version, observed values and independently computed `parameter_digest`.
- `PlcReadbackFact` adds server-derived `parameter_digest` and `confirmation_matches`. Wrong project/cause/equipment/version or reused write identity rejects with zero effects. A legitimate numeric/parameter-unit mismatch is **accepted immutable PLC observation evidence**, projects an `EquipmentRecord(confirmation_state='mismatched')`, and creates no calibration confirmation/target. A later independent matching observation with a fresh observation identity can confirm once through shared confirmation validation/persistence. `confirmation_state='matched'` links the actual calibration. No write artifact is copied as readback proof.

## External claims, derived RMAs, containment and BI

- Customer design approval creates a real `method='mock'` approval with external signer separate from applying actor. Its existing revision reader recovers original admitted integration provenance. Customer serial mapping validates actual WMS shipment membership and original project customer, then uses shared alias uniqueness/persistence. These actions do not substitute for customer unit release. Existing explicitly authored customer `release.decide` remains the separate real manual path when contract policy requires it; neither OA nor design approval invents that release or disables contract flags.
- Customer `acceptance` and overseas `delivery_receipt` keep their native source names and project/physical shipment/SN/quantity/customer provenance. Actual MES delivery contexts must cover every selected unit/WO; all selected context keys are preserved in causes, including multi-WO shipments. Shared delivery validation/persistence changes signed/accepted totals only, never physical shipped quantity. Delivery readers require persisted project/source-system/type/external-ID columns to match the exact admitted original fact, in addition to action/count/signatory.
- `DeliveryClaimData.accepted_unit_ids` provides an explicit nonempty strict subset for `partial`. Accepted counts are per-unit, deduplicated across documents. Rejected claims retain typed issue unit scope and add no positive delivery fact. `ExternalClaimRecord` exposes original claim, accepted units and issue units without inventing local issue-owner identities.
- CRM/overseas return claims use shared `feedback.validate_rma/_persist_rma` and actual shipped membership/open-RMA rules. New immutable `integration_return_units` maps original full claim SourceKey/hash to every exact unit/RMA. Each derived row explicitly uses `platform-derived/rma_unit/<derived RMA UUID>` for its work-item identity; `source_json` remains the original complete external claim. No fake external-ID suffix, collapsed units, or legacy RMA rewrite. `feedback.admitted_source` verifies exact source/hash/mapping/target before returning readable original provenance.
- Actual MES consumption of either return claim emits a scoped `mes.containment` caused by that original claim; WMS/SAP acknowledge it. Replay emits no second hold. Derived hold projection validates the full original claim/unit scope and links actual units. Existing physical core guards consume that real hold.
- `bi.refresh` is now a closed empty request, with no caller metric arithmetic or caller-selected historical snapshot. The server fixes current business cutoff, immutable source sequence vector, workflow version (admission/cohort/current quality state read in one workflow transaction), explicit tested-unit cohort and monotonic snapshot version. `MetricSnapshot` exposes the original immutable `bi.snapshot`.
- FPY is first admitted immutable test pass / distinct first-tested units; successful rework/retest and duplicate deliveries do not inflate it. Final yield uses the same cohort and current qualified latest test with scrap/unresolved-defect exclusions at the recorded cutoff. Shortage is a dimensionless short-requirement count/current-requirement count, never kg+pieces. Delivery explicitly means distinct physically shipped/formal-order unit count, separate from signed/accepted. Zero denominator remains explicit 0/0, never invented 100%. Snapshot refresh writes only its own facts, and old bytes remain unchanged after new test/rework/source evidence.

## Typed read views, schema and test foundations

- `FactDetail.auxiliary_records` is a closed union of `EnterpriseRecord`, `BomConfirmationRecord`, `EquipmentRecord`, `PreparedArtifactRecord`, `ExternalClaimRecord`, `MetricSnapshot`. Records include full source identity and fact hash, and are exposed only when the exact admitted projection includes their matching auxiliary ref. Auxiliary kinds add approval_request, approval_decision, supplier_notice, bom_confirmation, artifact, external_claim; existing object references remain actual domain objects.
- Schema stays 23. `integration_return_units` is additive and initialized for fresh/source22/existing23 stores, with immutable update/delete/replace guards and deferred full projection identity FK. No old RMA/ERP rows or wire bytes are rewritten. Original artifact BLOB schema lives only in product-test's own source DB, created in the authorized prepare transaction.
- `EdgeSpec.id` is `<producer>-><consumer>`. All original 32 distinct directions remain in `EDGES`; PDM→SAP includes actual BOM confirmation.
- `MockRig(..., network=True)` composes all real families. `connected_scenario('completion'|'shortage'|'ecn_return')` returns `ScenarioRefs` with actual core/checkpoint references and committed source keys. Completion exercises preparation/OA, real HR, PLC sample, original artifact test/calibration/readback, component, completion, returned-unused allocation and explicit release, shipment, separate counterparty claims, BI. ECN scenario proves new BOM sync/plan/start and original-unit return containment. Shortage uses actual 12/10/8 facts.
- `completed_operations`, `visible_fact_count`, `edge_evidence`, `all_visible_systems` read real stores and authenticated service browse APIs. Per-system parameterization verifies accepted source receipt+fact+domain/typed read model for every ID; all-edge assertion verifies real producer key/consumer receipt/projection refs for every direction. Test-only core prerequisite fixtures remain separate and do not count toward network acceptance. Production imports no test code; Task6 owns the durable importer/manifest/resume tool.

## TDD evidence and regression work

All commands use `PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest` from this worktree.

- Initial `tests/workflow/integrations/test_enterprise_edges.py -q`: **3 failed**, PDM/CRM/HR not configured; after real producers/typed projections: **3 passed**. OA/SRM expansion then failed on unavailable enterprise fact admission and passed after actual domain implementations. Focused enterprise + existing supply/orders: **53 passed in 9.11s**.
- Initial `test_test_external_edges.py -q`: **2 failed**, PLC/product-test not configured. Real equipment/artifact/test path: **2 passed**. Calibration RED: missing evidence fact admission; calibrated/readback+existing laboratory suite GREEN: **28 passed in 12.67s**.
- BOM confirmation RED: no actual `bom_confirmation` facts. Enterprise GREEN after source response/plan gate: **6 passed in 1.17s**. Replacement RED: missing replacement-specific request. GREEN after explicit request/confirm/plan/new-start recipe: **1 passed, 6 deselected in 3.52s**.
- Initial all-edge RED: real connected scenario builder missing. First real all15/all32 GREEN: **1 passed in 3.45s**; expanded suite adds a separate per-system parameterization using the same real complete network.
- External receipt RED: missing evidence admission, then exact public shipment projection-target gap. Fixed source claim path and added real shipment ObjectRef to existing public WMS facade projection; external shipment/RMA/containment GREEN. Multi-WO claims/partial/rejected tests: **3 passed, 6 deselected in 7.72s**.
- BI request RED: foundation required caller cutoff/metrics. Server-derived refresh GREEN; later actual fail→OA independent rework→pass test proves retained FPY0/1 and final1/1, **1 passed, 10 deselected in 1.29s**.
- Original artifact immutable-replace RED: `DID NOT RAISE IntegrityError`. Added source-store before-insert replacement guard; original bytes/changed inline data/manual-provenance checks GREEN.
- Controller observation-semantics RED: legitimate PLC mismatched values rejected as if no observation. After retaining accepted mismatch fact/typed status while skipping confirmation, matching/mismatched/identity/version/equipment proof GREEN.
- HTTP artifact download RED: 404 missing endpoint. Authorized owned download/cross-project proof GREEN. Combined download/readback/retest focused check: **3 passed, 9 deselected in 3.55s**.
- Intermediate 200-case core/contracts/new-family suite: **4 failed, 196 passed**. Failures were three generic contract tests assuming every operation input equals its derived output (new BI/prepare/BOM operations intentionally derive outputs), plus the old second-WO fixture attempting a plan before the new required BOM acknowledgment. Tests now construct valid derived outputs and explicitly deliver that actual request/confirmation before planning; no gate was weakened.
- Focused new-family/all-edge/contracts verification before final hardening: **144 passed in 23.81s**.
- Final broad collection initially stopped on a test fixture import-order NameError (pytest decorator before import), corrected before any test execution; this was not a product failure.

- First full `tests/workflow -q`: **1 failed, 901 passed, 35 skipped in 441.42s**. The sole failure was `test_a1_extensions.py::test_extension_contracts_exist_and_production_registry_contains_only_real_actions`: its exact literal allowlist omitted `mock_system.execute/query/retry` and `integration.pull`, all four already present in reviewed Task2/3 base. Added only these existing actual production commands to the expected set; no production registry change. Affected file GREEN: **10 passed in 0.50s**.
- Self-review delivery provenance RED: mismatching a persisted source-system/type/external-ID column still returned admitted provenance. Narrow exact-project/source-column guard GREEN together with both BI regressions: **3 passed, 10 deselected in 3.87s**.
- Self-review independent observation RED: a second PLC readback could reuse a prior failed observation's `source_identity` with different values (`DID NOT RAISE DomainError`). Guard rejects already committed PLC observation identity; test retains separate failed-value and failed-unit observations, verifies original failed fact remains byte-equivalent after a fresh matching readback, GREEN: **1 passed, 12 deselected in 1.43s**.
- Final affected-file run `test_enterprise_edges.py test_test_external_edges.py test_all_edges.py tests/workflow/test_a1_extensions.py -q`: **48 passed in 33.11s**.

- Direct isolated real-network shortage smoke (same Python/environment plus `PYTHONPATH=src:tests`, canonical temporary directory): `connected_scenario("shortage")` produced actual SAP requirement **12**, WMS physical receipt **10**, WMS qualification **8**; repeated helper returned the same committed scenario. No repository/production data involved.

## Self-review and intentional boundaries

Reviewed the brief against real source operations, immutable receipts, snapshots-before-writes, target/provenance validation, typed read models, all 32 directed acknowledgments, original artifact bytes and download, independent failed/matching observations, multi-unit return/hold scope, replacement BOM gating, manual-command provenance protection and legacy projection regression coverage. Source files stay focused (largest new family module 263 lines), with the approved narrow core validation hook. Extracted existing domain validators retain public manual admission; no parallel workflow engine was introduced. Self-review repaired the delivery-column and repeated-observation identity cases above and made BI workflow-state reads coherent within one transaction.

Intentional documented boundaries: SRM is still planned maturity; BI v1 snapshots the current server cutoff (no arbitrary historical reconstruction); customer unit release remains a distinct explicit existing manual claim if required by contract; controlled artifact templates are mock-source originals, not real external equipment I/O. Task5/6 still own business workspace UI and durable seed/import/cutover. No required Task4 family or edge is deferred. No known unresolved implementation blocker.

## Exact owned paths

- `src/manufacturing_platform/workflow/api.py`
- `src/manufacturing_platform/workflow/delivery.py`
- `src/manufacturing_platform/workflow/engineering.py`
- `src/manufacturing_platform/workflow/feedback.py`
- `src/manufacturing_platform/workflow/integrations/bi_metrics.py`
- `src/manufacturing_platform/workflow/integrations/bom_sync.py`
- `src/manufacturing_platform/workflow/integrations/browse.py`
- `src/manufacturing_platform/workflow/integrations/calibration_bridge.py`
- `src/manufacturing_platform/workflow/integrations/catalog.py`
- `src/manufacturing_platform/workflow/integrations/contracts.py`
- `src/manufacturing_platform/workflow/integrations/core_guards.py`
- `src/manufacturing_platform/workflow/integrations/core_mes.py`
- `src/manufacturing_platform/workflow/integrations/core_models.py`
- `src/manufacturing_platform/workflow/integrations/core_projections.py`
- `src/manufacturing_platform/workflow/integrations/core_sap.py`
- `src/manufacturing_platform/workflow/integrations/core_systems.py`
- `src/manufacturing_platform/workflow/integrations/core_wms.py`
- `src/manufacturing_platform/workflow/integrations/customer_bridge.py`
- `src/manufacturing_platform/workflow/integrations/enterprise_admission.py`
- `src/manufacturing_platform/workflow/integrations/enterprise_models.py`
- `src/manufacturing_platform/workflow/integrations/enterprise_projections.py`
- `src/manufacturing_platform/workflow/integrations/enterprise_systems.py`
- `src/manufacturing_platform/workflow/integrations/evidence_models.py`
- `src/manufacturing_platform/workflow/integrations/evidence_projections.py`
- `src/manufacturing_platform/workflow/integrations/evidence_systems.py`
- `src/manufacturing_platform/workflow/integrations/external_claims.py`
- `src/manufacturing_platform/workflow/integrations/operations.py`
- `src/manufacturing_platform/workflow/integrations/schema.py`
- `src/manufacturing_platform/workflow/integrations/test_artifacts.py`
- `src/manufacturing_platform/workflow/laboratory.py`
- `src/manufacturing_platform/workflow/orders.py`
- `src/manufacturing_platform/workflow/quality.py`
- `src/manufacturing_platform/workflow/service.py`
- `src/manufacturing_platform/workflow/store.py`
- `src/manufacturing_platform/workflow/supply.py`
- `tests/workflow/integrations/conftest.py`
- `tests/workflow/integrations/network_scenarios.py`
- `tests/workflow/integrations/support.py`
- `tests/workflow/integrations/test_all_edges.py`
- `tests/workflow/integrations/test_contracts.py`
- `tests/workflow/integrations/test_core_flow.py`
- `tests/workflow/integrations/test_profile_migration.py`
- `tests/workflow/integrations/test_enterprise_edges.py`
- `tests/workflow/integrations/test_test_external_edges.py`
- `tests/workflow/test_a1_extensions.py`
- `.superpowers/sdd/it-mock-20261103/task-4-report.md`

## Final verification

- Ruff `check --select F` on every owned Python file: **All checks passed!**
- `git diff --check` and `git diff --cached --check`: exit 0, no output. Exact staged-path equality check: **46 owned files**, no unrelated paths (45 source/test files plus this report).
- Full pytest retains the repository's **35 explicitly opt-in business-case skips** (`WORKFLOW_ACCEPTANCE_CASES`/CLI); this task did not alter those selectors or claim candidate/cutover acceptance.
- Broad `tests/workflow -q` rerun (started before the late return-mapping trigger fix below): **903 passed, 35 skipped in 461.02s**, exit 0. Final SQL change is verified by the targeted results below, as directed by controller.


### Late immutable return-mapping hardening

Final schema review found that `INSERT OR REPLACE` could preserve the full claim/unit primary key while changing to another valid RMA ID, because the trigger only checked reuse of the old RMA ID. An isolated SQLite test with real declared foreign keys and two valid referenced RMA IDs reproduced **DID NOT RAISE IntegrityError**. The trigger now checks both the full `(project_id, system, object_type, external_id, version, unit_id)` primary key and unique `rma_id` before insert, preserving both identities regardless of recursive-trigger settings. No table data or existing RMA row is rewritten. Focused evidence suite after the fix: **14 passed in 20.28s**.

Controller requested completion of the already-running broad check with precise attribution to its pre-trigger-fix state, followed by profile/schema migration + enterprise/evidence/all-edge coverage on final code; no third broad run is needed for this narrow SQL guard. Added an existing-v23 initialization test using an actual legacy ERP-backed public workflow and actual manual RMA. It drops only the empty new mapping table to recreate the reviewed v23 boundary, then reopens twice and verifies the newly initialized table/triggers, every prior workflow table's rows, the complete RMA read model/manual provenance, raw authority/legacy file bytes, the legacy profile and absence of mock source stores. The initial new test setup failed because the normal harness `db()` deliberately opens read-only; using an explicit fixture-only SQLite connection to simulate the old schema corrected the test setup without any product change. Final targeted command:

```text
PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/integrations/test_profile_migration.py tests/workflow/integrations/test_enterprise_edges.py tests/workflow/integrations/test_test_external_edges.py tests/workflow/integrations/test_all_edges.py -q
50 passed in 35.43s
```

The replacement regression was then expanded (test-only) to cover both primary-key and unique-RMA collisions with `recursive_triggers=0/1`; final focused `test_test_external_edges.py -k return_lineage_cannot -q`: **2 passed, 13 deselected in 0.03s**. All final production changes are covered by those final targeted runs; no source edits followed them.

## Independent-review fix wave (I1–I4)

Reviewed fix base: `3f61b9ee47ee9bdab6eb136bc6ed8e165d7e15a0`. This appendix supersedes the earlier no-known-issues statement for the four reproduced review findings. It records one focused implementation wave; controller still requires independent spec and quality re-review before Task5. No deployment, user-document edit, real account creation, legacy data rewrite, or full-suite re-run was performed for these precise boundary fixes.

### Fixes and published interface delta

- **I1:** `WorkflowService.integration_artifact` retains resolved original bytes locally, then opens a new workflow read transaction and repeats `browse.authorize` (live project/source authorization) before returning. Source I/O stays outside either workflow transaction. Service and HTTP tests revoke actual project-grant metadata through `change_grant`, separately setting roles empty and setting `active=false`. Both paths now return NOT_FOUND/404 with no artifact bytes/ETag/checksum disclosed. The controller confirmed this is the required live metadata boundary; no additional availability redesign is needed.
- **I2:** `external_claims.validate_signed_coverage(tx, context, fact)` checks the exact accepted unit set against admitted signed delivery rows for the same project and physical WMS shipment. Each contributing native signature must pass existing original-source/hash/projection/row admission, be no later than the acceptance, and appear in the acceptance's immutable `caused_by`. Source-accepted but not yet projected signatures do not count. Validation runs before source commit and again during projection. Disjoint or incompletely covered accepted scopes reject with a durable rejected receipt and zero new source facts or delivery effects.
- **Controller-approved domestic path:** new closed `CustomerReceiveShipment(DeliveryClaimData)` operation **`customer.receive_shipment`** produces `CustomerReceiveShipmentFact`, **`customer.delivery_receipt`**. It has the same typed claim fields as overseas signing: `shipment_id`, exact WMS `shipment` SourceKey, `units` (unit ID + SN), `amount`, `customer_id`, `external_signer`, `reason`, `signed_evidence`, `occurred_at`, `decision=accepted|partial|rejected`, and `accepted_unit_ids` for an explicit partial subset. Catalog policy is the existing **`delivery.sign`**; `FACT_POLICIES` derives it automatically. The closed operation/fact unions and `ExternalClaimRecord.claim` include this fact. It creates actual signed delivery state and the typed original claim view, and is delivered on the existing **customer→MES** edge. There are still exactly 15 systems and 32 directed edges; no schema version, legacy command model, or ERP wire change.
- **Task5/6 sequence/API:** for domestic flow, use the existing authorized command endpoint with `action=mock_system.execute`, `system=customer`, and the new typed payload operation `customer.receive_shipment`, then separately execute `customer.confirm_delivery` for only signed units. Overseas may instead use `overseas.receive_shipment`. Customer acceptance can use the union of exact admitted CUSTOMER and OVERSEAS signed subsets, preserving each contributing source key. A new signing operation overlapping already signed SNs across either source is rejected before effects; disjoint signed subsets and idempotent retry do not inflate signed counts. These are distinct source operations and receipts, not a generic stage/JSON shortcut.
- **Legacy/manual boundary:** existing `DeliverySign` has aggregate quantity only. Its handler, model, JSON and historical rows are unchanged; those quantities cannot invent signed serial membership for a typed external acceptance. Valid typed customer/overseas signed SN evidence supplies that membership. Physical `shipment_items` are never rewritten or counted a second time.
- **I3:** `external_claims.admitted_return` now requires immutable mapping `unit_id == row.unit_id` and `row.id == uuid5(domain_id(original_full_claim), mapped_unit_id)`. Existing exact full-claim source/hash/project/target/row checks remain. Both valid derived RMAs remain readable with original full claim provenance; swapping either member in memory rejects for CRM and overseas.
- **I4:** `external_claims.prepare_causes(payload, observations)` is the single shared claim preparation policy for physical shipment/MES-context lineage, positive-unit deduplication and signed-source causes. Enterprise calls it only for its CRM return operation; evidence calls it only for its supported customer/overseas operations. The duplicated dispatch/policy block and unreachable enterprise branches are removed. Shared `SIGN_TAGS` classifies the two actual signing fact types; no generic plugin/workflow engine was introduced.

### RED/GREEN evidence

All commands below use `PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest` in the worktree.

- `tests/workflow/integrations/test_test_external_edges.py -k 'artifact_reauthorizes or multi_work_order_claim_has_two' -q`: **RED 6 failed, 13 deselected in 9.90s**. Four grant-revocation cases returned bytes/HTTP200 instead of 404; both CRM/overseas swapped-member probes returned admitted provenance. After I1/I3 guards: **GREEN 6 passed, 16 deselected in 9.20s** (three I2 tests had meanwhile been added to collection).
- `.../test_test_external_edges.py -k review_customer_acceptance -q`: **RED 3 failed, 19 deselected in 8.28s**, all `DID NOT RAISE DomainError`: disjoint SN, overlapping scope padded by an aggregate manual receipt, and entirely aggregate-only manual evidence. After exact coverage/lineage validation: **GREEN 3 passed, 19 deselected in 7.60s**. Valid exact subsets succeed, duplicate acceptance rejects, and physical shipped quantity remains 2.
- `.../test_test_external_edges.py -k review_pending_signature -q`: **1 passed, 22 deselected in 2.87s**. Actual timeout-after-source-commit leaves the signature receipt accepted but unprojected; it cannot supply SN coverage despite manual aggregate credit. Retrying projects the same immutable signature and allows exact acceptance without duplicate signed/shipped counts.
- Before the approved domestic addition, enterprise/evidence/all-edge plus four targeted legacy delivery/feedback tests: **52 passed in 46.65s**. This is intermediate evidence, not the final domestic-path result.
- `.../test_test_external_edges.py -k 'review_domestic or review_mixed' -q`: **RED 3 failed, 23 deselected in 6.38s**, closed union rejected missing `customer.receive_shipment`. After typed registration/real projection/shared signed coverage: **GREEN 3 passed, 23 deselected in 6.65s**. Domestic signing/acceptance needs no overseas receipt; both customer-first and overseas-first mixed-source orders reject overlap, accept disjoint subsets, retain both causal keys, and preserve physical shipped quantity.

### Fix-owned paths and final verification

- `src/manufacturing_platform/workflow/service.py`
- `src/manufacturing_platform/workflow/integrations/catalog.py`
- `src/manufacturing_platform/workflow/integrations/contracts.py`
- `src/manufacturing_platform/workflow/integrations/enterprise_systems.py`
- `src/manufacturing_platform/workflow/integrations/evidence_models.py`
- `src/manufacturing_platform/workflow/integrations/evidence_projections.py`
- `src/manufacturing_platform/workflow/integrations/evidence_systems.py`
- `src/manufacturing_platform/workflow/integrations/external_claims.py`
- `tests/workflow/integrations/test_contracts.py`
- `tests/workflow/integrations/test_test_external_edges.py`
- This report.

**Exact code/test fix commit:** `363df1743c1ac755e166cf1dc9213751d9ee7896` — `fix: enforce artifact authorization and exact claim scope` (10 source/test paths; this report is recorded separately).

Final command on the complete domestic + I1–I4 code:

```text
PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/integrations/test_contracts.py tests/workflow/integrations/test_test_external_edges.py tests/workflow/integrations/test_enterprise_edges.py tests/workflow/integrations/test_all_edges.py tests/workflow/test_feedback.py::test_rma_retains_original_delivery_revision_failure_and_manual_source tests/workflow/test_feedback.py::test_invalid_rma_source_is_suppressed_in_value_and_restricted_audit_projection tests/workflow/test_delivery.py::test_pending_claim_and_separate_signed_accepted tests/workflow/test_delivery.py::test_required_named_issue_and_independent_closures -q
182 passed in 53.13s
```

Ruff `check --select F` on all 10 changed Python files: **All checks passed!** Unstaged and staged `git diff --check`: exit0/no output. Exact staging assertion verified only those 10 source/test paths. Source/test files were not edited after this final verification. Final self-review checked source I/O/authorization ordering, original signed-source/hash admission and same-shipment coverage, pending-projection rejection, cross-counterparty signed-SN duplication, deterministic per-unit RMA identity, catalog/fact policy/typed view registration, actual customer→MES acknowledgment and unchanged manual/legacy delivery/RMA behavior. No known remaining implementation issue in these four findings; independent spec and quality verdicts remain the controller's next gate.
