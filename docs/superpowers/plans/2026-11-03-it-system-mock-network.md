# Complete OEM IT System Mock Network Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all fifteen documented/modelled OEM IT systems operate through independently persisted mock state, coherent source facts and the current workbench, preserving existing online data and preparing an authorized direct mock-platform release.

**Architecture:** Add a closed typed integration package, server-owned profile routing, per-system SQLite state, durable causal outbox/inbox and trusted projectors into existing domains. Preserve the legacy ERP adapter and serialized contracts; embed source responsibilities, business operations, receipts and blockers in the existing order/engineering/supply/execution/quality/laboratory/delivery/trace/home workflows; keep 系统协同 for adapter operations and recovery. Append three versioned scenario graphs to the existing dataset; the global controller cuts over only after final review and candidate evidence.

**Tech Stack:** Python3.11+, FastAPI, Pydantic2, SQLite, pytest/httpx; existing React19/TypeScript/Vitest/Vite; current MF release controller and Linux candidate runtime. No new runtime service or dependency.

## Global Constraints

- Worktree: `/Users/neo/.codex/worktrees/a065/AI-Manufacturing-Platform`; accepted starting commit `40db85e4abeb7ad3c09d7cf95601d18f70b4c853`.
- Preserve dataset `manufacturing-full-flow-demo-20261028-v1`, mode `demo`, label `全流程模拟环境`, existing workflow/authority database paths, all six existing workflow projects and 45 SN, existing grants and historical operations.
- Fifteen new system IDs: `sap`, `pdm`, `crm`, `oa`, `hr_sap`, `hr_beisen`, `hr_dingtalk`, `mes`, `wms`, `product_test`, `plc`, `bi`, `customer`, `overseas`, `srm`; preserve `erp` as a separate legacy connector.
- New projects use immutable profile `oem-network-v1`; existing projects default to `legacy-erp-v1`. Dataset identity does not change.
- Mock stores and operations are available only in `demo`/`test`; production does not construct/open a mock adapter or store.
- Target workflow schema is `23`, advancing additively from source `22` and online `21`; preserve material-handoff migration and use forward-only recovery after schema advance.
- New state files reside under `<workflow-db-parent>/mock-systems/<dataset-id>/<system-id>.sqlite3` inside the existing data mount; no new environment variable, mount or container.
- Every persisted intent pins its system and canonical payload before I/O. Retry/query never reroutes an existing intent.
- New work ledgers/briefs/reports use `.superpowers/sdd/it-mock-20261103/`; do not overwrite or stage old SDD reports or unrelated dirty documentation.
- Release is MF-only: preserve actual PF source/static inventories, ordered 57 Compose inputs and 16 mounts at the audited baseline; recapture and repin if runtime changes.
- Require existing 36 candidate cases plus new complete mock-network acceptance; candidate preparation is not deployment evidence.

The user already approved scope and direct online deployment. Do not ask an execution-choice, scope, seed, or deploy-permission question. Seven implementation tasks below end in reviewable commits. Task7 ends at candidate/release preparation; the global controller performs the authorized cutover after its final review. The latest user correction excludes their architecture/handbook/discussion documents from this work: do not make the formerly proposed dirty-document baseline commit or semantically edit those files. Release packaging may read existing required handbook text unchanged. Record the corrected internal-plan commit as Task1’s base; do not stage unrelated dirty docs.

Read [the design](../specs/2026-11-03-it-system-mock-network-design.md) sections4–8 before implementation. `/tmp/it-mock-contract-audit.md`, `/tmp/it-mock-plan-decisions.md` and `/tmp/online-mock-release-readiness.md` are supplemental local evidence; the committed design contains their required contracts and live-baseline cautions.

## File structure and task dependencies

All new runtime modules live under `src/manufacturing_platform/workflow/integrations/`. Tasks own focused layers:1 contracts/catalog/routing/schema;2 store/network/operation lifecycle;3 core state machines/projection;4 enterprise/evidence state machines/projection/read models;5 frontend;6 seed/coverage;7 release preparation. Tests live under `tests/workflow/integrations/`, with a test-only helper `support.py`. No test helper is included in the business release.

Task3 depends on1–2;4 on3;5 consumes1–4 APIs;6 uses3–5;7 consumes all. Do not claim complete-network acceptance after only the core three systems. Avoid independent concurrent edits to `exchanges.py`, `service.py`, command unions or shared TS types.

## Task 1: Typed contracts, immutable routing and additive profile schema

**Files**

Create `workflow/integrations/{__init__,contracts,core_models,enterprise_models,evidence_models,catalog,routing,schema}.py` under the source root; create `tests/workflow/integrations/{__init__,test_contracts,test_profile_migration}.py`. Modify `workflow/{schema,store,commands,contracts}.py` only for additive schema/command type registration points. Type models are split now; their behavior belongs to later tasks.

**Interfaces**

- `catalog.SYSTEM_IDS: tuple[str, ...]`, `catalog.OPERATIONS: Mapping[str, OperationSpec]`, `catalog.EDGES: tuple[EdgeSpec, ...]`; `OperationSpec` has system, input model, output fact types, underlying action and required target discriminator.
- `routing.profile_for(tx, project_id: UUID) -> ProfileId`; missing row is `legacy-erp-v1`.
- `routing.assign_profile(tx, project_id: UUID, profile: ProfileId) -> None`; server-only, demo/test, idempotent same value, rejects change after any existing domain command/exchange/integration intent; the project-creation audit itself does not prevent initial assignment. This release initializes only the three maintenance-seeded projects through create→assign→domain-intents. Other public creations retain the legacy default and display legacy/unconfigured capabilities. Do not extend public ProjectCreate or change its canonical payload/hash/default test-mode ERP route.
- `routing.route(profile: ProfileId, action: str) -> str`; legacy always `erp`; new profile maps reservation/stock proof toWMS, production/ECO/freeze toMES, shipment toWMS. SAP accounting occurs through the network once per physical fact.
- `ConnectorId = SystemId | Literal['erp']` is used by descriptors; new operation/fact types admit only the fifteen `SystemId` values. `SystemOperation`, `SystemReceipt`, `IntegrationFact`, `SourceKey`, `SystemDescriptor`, `ProjectionResult`, `FactPage`, `NetworkDelivery`, `DeliveryReceipt`, `DeliveryBatch` follow design4 exactly. `CoreAuthorityAdapter` later implements old `AuthorityAdapter` via the new core state machines.
- `ExecuteSystemOperation`, `QuerySystemOperation`, `RetrySystemOperation`, `PullIntegrationFact` extend `WorkflowCommand`; outer action literals are `mock_system.execute`, `mock_system.query`, `mock_system.retry`, `integration.pull`. Execute carries a discriminated operation payload; query/retry carry original intent UUID; pull carries a full SourceKey. No arbitrary dict payload.

- [ ] Write direct contract tests first. Use this executable route assertion and parameterize every explicit system/operation discriminator from design4.1:

```python
from manufacturing_platform.workflow.integrations.catalog import SYSTEM_IDS
from manufacturing_platform.workflow.integrations.routing import route

def test_profiles_do_not_reinterpret_legacy_execution():
    assert len(SYSTEM_IDS) == len(set(SYSTEM_IDS)) == 15
    assert 'erp' not in SYSTEM_IDS
    assert route('legacy-erp-v1', 'production.start') == 'erp'
    assert route('oem-network-v1', 'production.start') == 'mes'
    assert route('oem-network-v1', 'reservation.request') == 'wms'
    assert route('oem-network-v1', 'shipment.request') == 'wms'
```

- [ ] Run `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/integrations/test_contracts.py -q`; record RED missing module/route. Add model tests proving wrong system/operation pair, unknown discriminator, extra payload field, mixed units, malformed source identity, naive datetime and duplicate unit/SN scope fail validation.
- [ ] Implement all typed payloads from design4.1, including emitted context/request facts needed by edge matrix5. Use Pydantic `extra='forbid'`, typed decimal quantities, bounded lists, timezone validation and exact action/payload matching. Do not modify serialization of old ExternalRequest/ExternalReceipt. Model omitted posted time explicitly; no timestamp inventing.
- [ ] Fill fixed policy table: SAP order→`order.register`, WO→`work_order.register`, plan→`plan.receive`, posting→`ownership.movement`; WMS receive→`supply.receive`, reserve→`reservation.request`, other physical movements→`ownership.movement`, shipment→`shipment.request`; MES IQC→`supply.inspect`, controls→matching `production.*`, switch→`eco.switch`, pass/complete→`execution.record`, assembly→`component.install`, contain→`freeze.request`, release→`release.decide`; PDM→`engineering.revision`/`eco.open`; CRM→`demand.record`/`rma.open`; OA typed engineering approval→`npi.review`, typed quality approval→`nonconformance.disposition`; HR evidence→`authority.register`; SRM→`supply.commit`/`arrival.record`; test/calibration→`test.record`/`calibration.record`; PLC→`execution.record`; customer→`engineering.customer_approval`/`delivery.accept`/`unit.alias`; overseas→`delivery.sign`/`rma.open`; BI→`plan.receive`. Apply the existing action's qualifications and additional variant restrictions; the table never overrides existing `authorize` hooks.
- [ ] Add schema23 tables for immutable project profiles; source operation intents and receipts; source projections keyed by project/full SourceKey and payload hash; object links. Integrate migration after schema22 and test fresh,21→22→23,22→23, repeated initialization, unknown-future-version rejection. Preserve all prior rows and no readiness seed.
- [ ] Add migration regression using a source22 fixture with projects/audit/exchange JSON; compare logical rows and exact stored request/receipt bytes before/after. Verify a missing profile stays legacy and profile reassignment with any intent fails. Existing production configuration must not create new mock directories.
- [ ] Run `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/integrations/test_contracts.py tests/workflow/integrations/test_profile_migration.py tests/workflow/test_exchanges.py tests/workflow/test_imports.py -q`; expected GREEN, including unchanged legacy behavior. Record actual counts/output under the new ledger.
- [ ] Review explicit diff, then stage only Task1 files and commit `feat: define typed OEM mock systems and immutable profiles`. Do not stage the old SDD reports or handbook changes.

## Task 2: Independent stores and recoverable network operation lifecycle

**Files**

Create `workflow/integrations/{store,network,operations,browse}.py`, `tests/workflow/integrations/{support,conftest,test_store_network,test_operation_boundary}.py`. Modify `workflow/integrations/{routing,__init__}.py`, `workflow/{service,api,exchanges}.py` for registry lifecycle/authorized reads/post-commit work. Keep family business state machines out of this task.

**Interfaces**

- `SystemStore(root: Path, dataset_id: str, system: SystemId, *, clock: Callable[[], datetime])`; `transaction(write: bool=False)` context; `append_fact(tx, fact)`, `enqueue(tx, fact, target)`, `list_facts(project_id, object_type, cursor, limit) -> FactPage`.
- `SystemRegistry(workflow_store)` lazily supplies `adapter(system)`, `legacy_adapter()` and delegates immutable `route`; production raises `SOURCE_UNAVAILABLE` before opening a file.
- `MockNetwork(registry).drain(project_id, *, limit=100) -> DeliveryBatch`; batch reports delivered, duplicate, pending and failed causal deliveries and cursor, with no global success claim on partial delivery.
- `IntegrationService(workflow, registry)` has `authorize(tx, actor, project_id, command)`, `prepare(tx, context, command) -> MutationResult`, `perform(actor, project_id, command, result) -> CommandResult`; `perform` uses durable original intent, query-first retry, source receipt validation, reauthorization and CAS before projection.
- `browse.systems(tx, actor, project_id, registry) -> list[SystemDescriptor]`, `browse.facts(...) -> FactPage`, `browse.fact(...) -> FactDetail` implement design4.4. Source observations and linked facts are checked before serialization.
- Test-only `MockRig` in `support.py` wraps actual WorkflowService + independent system roots. Methods `command(action, **fields)`, `execute(system, payload, *, operation_id=None, actor=None)`, `query(intent_id)`, `retry(intent_id)`, `pull(source_key)`, `drain(limit=100)`, `reopen()`, `fault(system, operation_id, name)`, `rows(system, table)`; properties `project_id`, `other_project_id`, `registry`, `actor`, `root`. All writes use actual service boundaries except explicit fault configuration. Fixtures `rig`, `production_rig` build separate test roots and deterministic authorized test-only identities.

- [ ] Write store tests: same operation ID/same canonical payload yields same receipt; changed payload conflicts; two system files remain distinct; wrong dataset/system metadata or filesystem alias fails; unauthorized/production read never opens files. Use fresh fixture paths; assert both state and source event counts.
- [ ] Run `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/integrations/test_store_network.py -q`; record RED. Implement schema metadata, immutable event/outbox/inbox records and WAL transactions. Unique keys are full SourceKey, not merely external ID. Keep source stream sequence local to each system.
- [ ] Implement durable delivery algorithm exactly in this order:

```python
# Producer transaction already committed the source fact and outbox row.
receipt = target.consume(delivery)  # inbox, projected state and acknowledgment in ONE target transaction
producer.acknowledge(delivery.id, receipt)  # separate producer transaction
# If acknowledgment write fails, retry consume returns its original inbox receipt.
```

`consume` checks target project/full causal identity/hash before modifying state. Rejected business input has a durable rejection acknowledgment; transient unavailability leaves pending. Never mark delivered solely because Python returned without a receipt.
- [ ] Add crash test between consumer commit and producer acknowledgment, reopen all stores, drain again; assert one target effect and stable receipt. Add wrong-version/hash rejection, delivery of projectA into projectB denial, bounded drain preserving pending remainder, and one project's fault not affecting another system/project/operation.
- [ ] Implement integration commands inside existing registry and service flow. General outer registration may admit business roles, but `authorize` must require the exact inner action and variant before intent persistence and again before apply. New I/O goes after the workflow transaction, like ExchangeService. Query original operation after timeout; do not generate a replacement operation ID.
- [ ] Add meaningful boundary test:

```python
import pytest
from manufacturing_platform.workflow.contracts import DomainError

def test_projection_waits_for_current_policy(rig):
    attempt = rig.begin_and_commit_source_then_revoke_actor()
    with pytest.raises(DomainError) as exc:
        rig.finish_pending(attempt)
    assert exc.value.status == 403
    assert rig.projection_count(attempt.source_key) == 0
    assert rig.source_receipt(attempt.operation_id) is not None
```

Implement these four test helper methods in `support.py` using a paused `IntegrationService.perform` boundary and ordinary grant commands; do not mock the authorization result. Add concurrent CAS test retaining source receipt and recoverable intent, plus raw evidence cross-project404 tests.
- [ ] Wire authenticated browse routes, bounded SQL reads and `mode/maturity/health` descriptors; capability-only shows unexercised. Preserve old `authority_rule` semantics. Bind `ExchangeService` to registry lookup using stored system for existing intents; `self.adapter` compatibility for old tests may be retained internally, never as new routing authority.
- [ ] Run `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/integrations/test_store_network.py tests/workflow/integrations/test_operation_boundary.py tests/workflow/test_exchanges.py tests/workflow/test_authority_assistance.py -q`; expected GREEN with query-after-commit, policy/CAS and legacy adapter tests.
- [ ] Stage exact Task2 paths; commit `feat: persist isolated mock system operations and causal deliveries`. Include private report of crash/replay proof, not credentials/runtime inspect.

## Task 3: Core SAP/WMS/MES authoritative facts and existing domain projections

**Files**

Create `workflow/integrations/{core_systems,core_projections}.py`, `tests/workflow/integrations/{test_core_flow,test_core_compatibility}.py`. Modify `integrations/{routing,operations,network}.py` plus focused helper/routing sites in `workflow/{exchanges,execution,eco,freeze,delivery,imports,supply}.py`; update `tests/workflow/integrations/support.py`. Avoid moving whole legacy files.

**Interfaces**

- `SapSystem`, `WmsSystem`, `MesSystem` implement `SystemAdapter` with separate `SystemStore` instances.
- `CoreAuthorityAdapter(system, registry)` implements `submit(ExternalRequest) -> ExternalReceipt`, `query(system, business_key)`, `snapshot(system, object_type)` and `stock_basis(request: ExternalRequest) -> StockBasisProof` used by existing reconciliation. Translate to shared core state-machine functions, retaining exact request hash and receipt scope. Existing ERP still uses `MockAuthorityAdapter` unchanged.
- `core_projections.project_fact(tx, context, fact) -> ProjectionResult` dispatches core typed facts to extracted domain validators/persistence helpers. Helpers accept already validated trusted record objects; public commands retain their original validation and source restrictions.
- `support.MockRig.core_ready(*, quantity=12, received=10, accepted=8) -> CoreRefs`; named refs include order, order_line, revision, work_order, requirement, commitment, lot, WMS receipt SourceKey and unit IDs. It uses actual operations/imports and exposes independent `physical_balance`, `accounting_balance`, `projection_count`, `original_receipt_bytes` queries.

- [ ] Write the RED conserved-quantity path using the actual rig:

```python
import pytest
from manufacturing_platform.workflow.contracts import DomainError

def test_iqc_and_sap_posting_are_distinct_exactly_once(rig):
    refs = rig.core_ready(quantity=12, received=10, accepted=8)
    assert rig.physical_balance(refs.lot).qualified == 8
    with pytest.raises(DomainError):
        rig.execute('wms', dict(kind='wms.reserve', requirement_id=str(refs.requirement),
                               lot_id=str(refs.lot), quantity='12', unit='件'))
    move = rig.pick_qualified(refs, quantity=8)
    rig.drain()
    rig.replay_delivery(move.source_key, 'sap')
    assert rig.sap_post_count(move.source_key) == 1
    assert rig.physical_balance(refs.lot).picked == 8
```

Implement `pick_qualified`, `replay_delivery`, `sap_post_count` test helpers against actual operations/network, not inserted SQL results. Their signatures are fixed above and used only in this test layer.
- [ ] Run `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/integrations/test_core_flow.py -q`; expected RED unsupported core operations. Implement typed SAP orders/WO/plan and WMS receive/location/movements; project these to existing object schemas with full source identity.
- [ ] Implement MES IQC against full WMS receipt key; accepted+rejected cannot exceed uninspected receipt quantity. Deliver qualification once to WMS; retain manual-receipt confirmation reconciliation without duplicate quantity. SAP accounting subscribes once per physical source key; source copies never create additional stock.
- [ ] Implement core control adapter mapping at `execution.py` start/interrupt/resume, `eco.py` switch, `freeze.py` requests, `delivery.py` shipment, and `exchanges.py` reservation. Replace only **new-intent** `system='erp'` construction with profile route. Receipt application and legacy old JSON remain stable. Pin active legacy work orders and sequences to old ERP.
- [ ] Implement MES execution/component/consumption/line-side custody and WMS pick/return/stocktake/shipment as source-owned facts. Reuse current readiness, version, quarantine, quantity, unit/SN and shipment constraints in source-side controls as well as existing public controls. Consumer cannot forge readiness by sending a broad accepted receipt.
- [ ] Implement containment acknowledgment gate: MES hold→WMS/SAP and platform; reserve/start/ship blocked while required target acknowledgment is pending or unknown, and after acknowledgment if frozen. Release requires matching current hold/version and downstream acknowledgment; a stale release cannot clear a newer hold.
- [ ] Add RED/GREEN tests for pending hold and failed downstream delivery, mismatched owner/unit/lot, competing reservations across adapter instances, unknown committed shipment query without duplicate accounting, sequence inversion across systems, ECN retained-unit conservation, and legacy source22 request hash/stock basis receipt replay after schema23. Compare exact prior ERP request/receipt bytes; do not regenerate expected hashes with new code.
- [ ] Run `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/integrations/test_core_flow.py tests/workflow/integrations/test_core_compatibility.py tests/workflow/test_execution.py tests/workflow/test_eco.py tests/workflow/test_trace_freeze.py tests/workflow/test_imports.py tests/workflow/test_exchanges.py -q`; expected GREEN, capture actual count.
- [ ] Stage only core files and focused existing changes; commit `feat: connect mock SAP WMS and MES without duplicate posting`. Reviewer verifies both ownership and legacy compatibility before Task4.

## Task 4: Every remaining system, trusted test ingestion and typed auxiliary views

**Files**

Create `integrations/{enterprise_systems,evidence_systems,enterprise_projections,evidence_projections}.py`, `tests/workflow/integrations/{test_enterprise_edges,test_test_external_edges,test_all_edges}.py`. Modify `integrations/{catalog,routing,network,operations,browse}.py`, narrow trusted helper sites in `workflow/{engineering,introduction,laboratory,laboratory_evidence,execution,delivery,genealogy_models}.py` only where the existing domain requires them. Extend `support.py` with scenario builders; do not alter manual command provenance validators.

**Interfaces**

- `EnterpriseSystem(system, store, registry)` supports exactly PDM/CRM/OA/three HR/SRM operations; `EvidenceSystem(...)` supports test/PLC/customer/overseas/BI. Each registered instance owns a distinct store.
- `enterprise_projections.project_fact(...)` and `evidence_projections.project_fact(...)` return the same `ProjectionResult`; no alternate visibility or idempotency rules.
- `HRRecord`, `EquipmentRecord`, `MetricSnapshot` are closed auxiliary value models in the corresponding family model files. `FactDetail` links these plus existing ObjectRefs; auxiliary entries never impersonate manufacturing orders or grant records.
- `support.MockRig.connected_scenario(name: Literal['completion','shortage','ecn_return']) -> ScenarioRefs`; it produces actual graph facts/checkpoint refs. `edge_evidence(edge_id)` returns durable source/ack/projection identities; `all_visible_systems()` uses authenticated browse API. These helpers become foundations for the real seed in Task6, not a parallel production fixture API.

- [ ] Write per-system parameterized tests requiring real persisted operation receipt, source fact and linked object/read model for every ID. Add every diagram edge from design5 as a required ID in `catalog.EDGES`; forward/reverse requirements have separate direction keys and acknowledgments.
- [ ] Run `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/integrations/test_enterprise_edges.py tests/workflow/integrations/test_test_external_edges.py -q`; expected RED unsupported systems. Implement PDM revision/BOM/ECN, SAP request context, CRM demand/return, OA target-bound request/decision, planned SRM promise/ASN/COA. Wrong target/version/project fails before any decision projection.
- [ ] Implement all HR variants as typed fictional source identities/evidence. MES validates operator employee+qualification expiry+shift. Source qualification publication must leave platform grants byte-for-byte unchanged. Tests revoke actual operator permission separately and prove valid HR evidence cannot overcome application denial.
- [ ] Implement MES↔test task/results and PLC↔MES process acknowledgment/sample. Trusted execution/test projectors extract shared domain validators/persistence from manual paths while preserving `mode='mock'`; keep public manual models rejecting forged mock/API provenance. Test same trusted record through public manual form fails, through configured projector succeeds with original source identity.
- [ ] Implement independent calibration write/readback: readback carries its own PLC source key and actual value/hash; mismatched value/version/unit/equipment or reused write identity blocks confirmation. Raw evidence artifact index resolves under owned mock assets with checksum, no arbitrary host path or remote URL fetch.
- [ ] Implement customer approval/SN mapping/delivery claim and overseas receipt/return separately. Link shipment/SNs/quantity and retain external signer versus local actor. Customer/overseas confirmation never mutates local shipped quantity again. CRM/overseas returns create the corresponding MES containment linkage rather than a disconnected RMA row.
- [ ] Implement BI refresh from committed SAP/MES source references at pinned cutoff, formula version and first-attempt/final-good denominator; duplicate deliveries/retests do not inflate first-pass counts. BI is read-only to source quantities. Test the retained snapshot stays unchanged after later source facts and a new refresh creates a new version.
- [ ] Add all-edge assertion:

```python
from manufacturing_platform.workflow.integrations.catalog import EDGES, SYSTEM_IDS

def test_every_system_has_an_operation_and_every_edge_has_evidence(rig):
    rig.connected_scenario('completion')
    rig.connected_scenario('ecn_return')
    for system in SYSTEM_IDS:
        assert rig.completed_operations(system) > 0
        assert rig.visible_fact_count(system) > 0
    for edge in EDGES:
        evidence = rig.edge_evidence(edge.id)
        assert evidence.producer_key
        assert evidence.consumer_receipt
        assert evidence.projection_refs
```

Implement the three counting/evidence helper methods as reads through real stores and authorized API. Require both directions for bidirectional edges; a descriptor cannot satisfy evidence.
- [ ] Run `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/integrations/test_enterprise_edges.py tests/workflow/integrations/test_test_external_edges.py tests/workflow/integrations/test_all_edges.py tests/workflow -q`; expected GREEN. This broad run is warranted by trusted changes to several established domains; record failures precisely, repair and rerun affected tests before repeating broad tests.
- [ ] Commit exact task paths as `feat: connect enterprise test equipment and external mock systems`. Reviewer checks all15 systems and supporting edges, not only family-level tests.

## Task 5: Integrate system responsibilities and actions into existing business workflows

**Files**

Create `webui/src/workflow/integrations/types.ts`, `businessSteps.ts`, `{SystemStepPanel,ConnectedSystemsWorkspace,SystemFacts,SystemOperationForm,CoreOperationFields,EnterpriseOperationFields,EvidenceOperationFields}.tsx`, and `{businessSteps,businessJourneyHttp,connectedSystems}.test.tsx` in that integration directory. Modify existing `webui/src/workflow/{OrdersWorkspace,IntroductionWorkspace,SupplyWorkspace,MaterialHandoffWorkspace,ExecutionWorkspace,QualityWorkspace,LaboratoryWorkspace,DeliveryWorkspace,TraceWorkspace,WorkflowHome,ExchangeWorkspace}.tsx` only at small shared-panel/context mounting points. Modify existing `api.ts`, `types.ts`, `labels.ts`, and `ConflictComparison.tsx` in the workflow directory for typed API/form support. Reuse established object-detail source/evidence rendering; no fifteen top-level routes, vendor application rebuild or isolated all-systems business dashboard.

**Interfaces**

- API methods `systems(projectId)`, `systemFacts(projectId, system, filters)`, `systemFact(projectId, key)` match backend4.4 and use current error/auth handling.
- `BusinessContext = 'orders' | 'engineering' | 'introduction' | 'supply' | 'handoff' | 'execution' | 'quality' | 'laboratory' | 'delivery' | 'trace' | 'home'`.
- `BusinessStepDefinition` includes `id`, `context`, `responsibleSystem`, `inputTypes`, `outputTypes`, `operationKind`, `receiptType`, `blockingDependencies`, and `nextStepIds`. `BUSINESS_STEPS: readonly BusinessStepDefinition[]` maps every design4.4 step. Read-only trace/home steps permit `operationKind: null`; BI refresh invokes the permitted derived-snapshot operation.
- `SystemStepPanel(props: OEMWorkspaceProps & {context: BusinessContext; selected: ObjectRef | null})` resolves project/business context and source links, shows responsible system/input/output/next action/receipt/blocker, and invokes shared `SystemOperationForm`. `SystemOperationForm` receives descriptor, selected operation and controlled domain choices; it never creates another operation ID for frozen retry.
- `ConnectedSystemsWorkspace(props: OEMWorkspaceProps & {mode: DatasetMode})` is diagnostic/operational: adapter capabilities/status/configuration, source inspection, receipt/query/retry/reconciliation. Daily business operation forms are discoverable and actionable inside their consuming business workspace.
- TypeScript discriminated unions mirror backend operations/facts; three family field components render typed business fields, not JSON textareas. Binding source/object IDs from selected context is server-validated; no editable UUID business field.

- [ ] Write failing component tests for `SystemStepPanel` showing system responsibility, required inputs, resulting object, next permitted action, receipt and blocker for each `BUSINESS_STEPS` definition. Write HTTP-backed journeys starting in real existing business workspaces, not a standalone system page.
- [ ] Run `npm --prefix webui test -- src/workflow/integrations/businessSteps.test.tsx src/workflow/integrations/businessJourneyHttp.test.tsx`; expected RED missing integrated panels/actions.
- [ ] Implement typed API and `businessSteps.ts`. Cover orders CRM→SAP; engineering PDM→OA and separate customer contractual approval→MES revision; supply SAP plan→WMS physical→MES IQC→WMS pick/manual handoff with SAP accounting per physical event; execution MES+HR+PLC; laboratory test+PLC readback→MES release; delivery WMS→SAP→customer/overseas; trace source aggregation; home BI readonly cutoff snapshot. Source-side ownership labels explicitly say “模拟契约”, not empirically verified field direction.
- [ ] Implement the shared panel/form and mount it in existing workspaces. The order-versus-engineering modes in `OrdersWorkspace` use distinct context maps. HR/PLC evidence appears in execution/laboratory where it matters; BI appears on home with metric cutoff/formula/drilldown. Preserve existing tasks, object selectors, navigation, dirty drafts and business detail links.
- [ ] Implement family fields for readable business references, quantities/unit/owner/location, revisions/approval targets/decisions, people/shifts/equipment, test/result/readback and shipment/signature. Present exact blockers beside the relevant next action. Context preselects the existing order/work order/lot/unit; server still rejects wrong project/version/source. No UUID or JSON entry is required.
- [ ] Retain `ExchangeWorkspace` and diagnostic connected-system view for adapter state, pending receipts, query/retry/reconcile; do not move all day-to-day actions into it. Keep legacy ERP exchange forms. Runtime statuses distinguish mock connected/unexercised/pending/degraded; SRM is planned and HR/customer variants modeled. Authority registration alone never changes connectivity.
- [ ] Add HTTP-backed journeyA from Orders: CRM demand→SAP formal order→PDM revision/OA/customer approval in engineering→MES work-order binding. JourneyB starts in Supply and performs SAP plan→WMS receipt→MES IQC→WMS pick/handoff→SAP accounting; assert source receipts and blocked shortage before recovery. JourneyC starts in Execution/Laboratory and covers HR/PLC eligibility→MES execution→product-test/PLC readback→MES release→WMS/SAP delivery→customer/overseas claims→home BI/trace links. These exercise at least three families and actual mutations/projections, not fetch-only cards.
- [ ] Add authorization/conflict tests: qualified HR evidence does not grant platform quality rights, manual form rejects forged mock provenance, unauthorized actions hidden/denied, cross-project source absent, stale project conflict retains draft and UUID, unknown result queries the existing operation, dirty-form leave behavior preserved.
- [ ] Use assertions against the integrated workspace, including:

```tsx
expect(within(supplyWorkspace).getByText('WMS 实物收货')).toBeTruthy();
expect(within(supplyWorkspace).getByText('MES 检验回执')).toBeTruthy();
expect(within(supplyWorkspace).getByText('待检物料不可配料')).toBeTruthy();
expect(within(supplyWorkspace).queryByLabelText('JSON')).toBeNull();
expect(within(supplyWorkspace).queryByLabelText('UUID')).toBeNull();
expect(within(deliveryWorkspace).getByText('SAP 过账回执')).toBeTruthy();
```

`SupplyWorkspace` and `DeliveryWorkspace` renders in the HTTP test supply these DOM roots; fixtures create a normal authorized network project through the real host fixture. Mock fetch only in pure component tests, not journey acceptance. Retain per-step workspace/source/receipt observations for Task6 coverage.
- [ ] Run `npm --prefix webui test` and `npm --prefix webui run test:bundle`; expected fullGREEN/build/typecheck/bundle checks. Keep the current lock and visual conventions; small shared-panel mounts avoid duplicating full operation UI across workspaces.
- [ ] Commit explicit Task5 frontend paths as `feat: integrate mock system steps into OEM business workspaces`. Reviewer rejects a result where all fifteen cards exist but business workspaces lack responsible systems, next actions, source receipts or blockers.

## Task 6: Durable coherent seed, preserved online portfolio and complete coverage report

**Files**

Create `scripts/seed_it_mock_network.py`, `scripts/it_mock_network/{__init__,runner,scenario_completion,scenario_shortage,scenario_ecn_return,verify}.py`, `tests/workflow/integrations/{test_seed,test_network_acceptance}.py`. Reuse `scripts/seed_workflow_demo.py` helpers through composition or a small shared helper extraction only if necessary; its existing namespace/run behavior must not change. Existing test support may import scenario recipe data, but production seed must never import `tests`.

**Interfaces**

- CLI `python3 scripts/seed_it_mock_network.py --workflow-db ABS --authority-db ABS --dataset-id ID --dataset-label LABEL --manifest ABS --owner-id VERIFIED_UUID [--verify-only]`; owner is repeatable if existing support permits, dataset must be demo/test and fixed existing metadata.
- `NetworkSeed.run(*, verify_only: bool=False) -> SeedReceipt`; durable namespace `it-mock-20261103-v1`, deterministic per-step operation IDs, private atomically written manifest, captured source times and per-project versions. Assign the network profile immediately after new project creation and before its first domain command; persist this assignment in the seed manifest.
- Scenario modules expose `populate(seed: NetworkSeed) -> ScenarioReceipt`; runner shared methods `project(key, title)`, `command(key, project, action, **fields)`, `execute(key, project, system, payload)`, `pull(key, project, source_key)`, `drain(key, project)`, `checkpoint(key, refs)` all record an intent before I/O and reconcile on restart.
- `verify.verify_network(seed, *, complete: bool) -> CoverageReceipt`; schema/version/dataset/legacy baseline plus system operation counts, typed fact/projection links, direction-specific edge evidence, business-step/workspace/input/output/next-action/receipt/blocker coverage, current actionable checkpoints and owner access. Every BUSINESS_STEPS ID must appear in the scenario manifest with its business workspace and actual source/projection references; system-page presence alone is not coverage. Coverage identifies seeded checkpoints separately from full candidate-completed scenarios.

- [ ] Write RED seed test on a copy of a legacy portfolio fixture: capture old project/SN/grant/audit/ERP row identities and stored JSON; run new seed; assert exactly three new owned projects, unchanged old rows, same dataset identity, all15 source identities with persistent operations and typed facts. Fixtures use test-only users; production CLI validates actual owner via authorized existing metadata.
- [ ] Run `PYTHONPATH=src:. /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/integrations/test_seed.py -q`; expected RED missing importer. Implement private manifest durability and path/root/namespace checks, mode guard and owner validation. Missing manifest with existing namespace fails; unrelated workflow edits produce a conflict requiring recorded resume, never overwritten state.
- [ ] Implement the three recipes exactly as design6. Use simple legible quantities and explicit ownership; no fictional source may change the customer owner. Include completed evidence branch plus actionable checkpoint per recipe. Populate ancillary data by operations: HR source qualification→MES eligibility, PLC sample/readback, BI snapshot, separate customer/overseas flows and planned SRM. No direct platform SQL insertion or manual-source disguise.
- [ ] Ensure real owner access and recipient selection uses verified existing users, no test login, no borrowed session, no implicit grant of inspection/disposition/release qualifications. The server-only seed maintenance actor is explicit in audit and has no authentication session; data lineage preserves external/mock actors separately.
- [ ] Add interruption tests at source commit, target inbox commit and workflow projection commit. Resume original manifest; assert original operation IDs/receipt hashes and zero duplicate quantities. Re-run completed seed and `--verify-only`; assert no business/audit/project-version changes.
- [ ] Add complete candidate acceptance (seed checkpoints then normal authorized commands finish scenarios): shortage12/receipt10/IQC8+2/replenish4, pending hold block/release acknowledgments, changed revision retains old units, test/readback failure, timeout-after-commit query, customer and overseas claim/RMA, immutable BI cutoff. Cross-project same-source/SN attempts fail without evidence exposure.
- [ ] Add coverage assertion code:

```python
from manufacturing_platform.workflow.integrations.catalog import EDGES, SYSTEM_IDS

def assert_complete_network(receipt):
    assert receipt.dataset_unchanged
    assert receipt.legacy_rows_unchanged
    assert set(receipt.systems) == set(SYSTEM_IDS)
    assert all(v.operations and v.facts and v.projections for v in receipt.systems.values())
    assert set(receipt.edges) == {edge.id for edge in EDGES}
    assert all(v.source_hash and v.consumer_receipt and v.frontend_ref for v in receipt.edges.values())
    assert receipt.business_steps_complete
    assert receipt.http_journey_family_count >= 3
    assert receipt.cross_project_denials > 0
    assert receipt.duplicate_postings == 0
```

`CoverageReceipt` declares these typed fields in `scripts/it_mock_network/verify.py`; `frontend_ref` names a business-workspace step/object reference proven by Task5 HTTP-backed journeys, not merely a system-card route and not a claim that a human browser was opened. The receipt includes `business_steps_complete: bool`, `http_journey_family_count: int`, and a step-indexed observation map linking context, responsible system, inputs/outputs, next action, blocker and receipt.
- [ ] Run `PYTHONPATH=src:. /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/integrations/test_seed.py tests/workflow/integrations/test_network_acceptance.py -q`; expected GREEN. Run local CLI twice and verify-only on fresh private temporary DB copies with fixture owner; compare logical legacy snapshots and report manifest/system-store paths without credentials.
- [ ] Commit exact task files as `feat: seed coherent OEM network scenarios without replacing legacy data`. Reviewer requires per-system and per-edge receipts, not aggregate count alone.

## Task 7: Candidate and MF-only release preparation; no cutover in this task

**Files**

Create `deploy/it_mock_acceptance.py`, `deploy/tests/{test_it_mock_acceptance,test_it_mock_backup}.py`; modify `deploy/{candidate_fixture,candidate_verify,release_support,sqlite_backup}.py` and `deploy/release.py` only where new acceptance/store backup inventory must be wired. Modify `docs/runbooks/workflow-release.md` with target23/additional-store recovery and explicit seed command. New task reports/briefs use `.superpowers/sdd/it-mock-20261103/`; private runtime/payload/candidate receipts remain in a newly owned release stage, not Git. The existing backup helper is exactly `deploy/sqlite_backup.py` (`backup_database` and `backup_databases`); the controller invokes it in the old API as appUID before cutover.

**Interfaces**

- `it_mock_acceptance.run(fixture_root: Path, evidence_root: Path) -> AcceptanceReceipt`; deterministic socket/API tests + pinned React business-workspace HTTP journeys across at least three families + seed/complete graph with every business step; receipt ID `it-mock-network-v1`, system/edge evidence, original36 independent result inventory.
- Candidate fixture includes current integration tests/new scripts from exact committed MF SHA; production business export remains runtime source/assets/approved handbook files only. Existing36 case IDs and pass/fail semantics do not change.
- Backup inventory derives initialized files from fixed catalog + configured workflow root, validates metadata/path uniqueness and backs them up as appUID alongside legacy/workflow/ERP. Records missing first-release stores without creating them. No arbitrary client path or cross-file atomicity assertion.
- Release preparation uses existing controller `prepare` then `candidate`; cutover invocation is intentionally reserved to the global controller after final review. This is task ownership, not a new user approval gate.

- [ ] Write RED candidate test: existing36 pass but absent/new-network failure refuses release readiness; altered fixture/acceptance inventory/hash or skipped edge fails. Write backup test with three initialized system files plus symlink/unknown metadata negative cases; accepted inventory includes only validated fixed catalog paths and preserves old five configuration fields.
- [ ] Run `PYTHONPATH=src:. /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest deploy/tests/test_it_mock_acceptance.py deploy/tests/test_it_mock_backup.py -q`; expected RED. Add independent acceptance receipt gate, export pinning and additional-store backup enumeration without altering old36 semantics or weakening candidate isolation.
- [ ] Add migration/recovery regression: old schema21→23 readiness with no business rows, source22 handoff intact, post-advance old-code rollback refused; preserve WAL/history and report forward repair. Existing old ERP databases remain readable and queryable. New per-system schemas are independently validated; unknown versions fail closed.
- [ ] Run `PYTHONPATH=src:. TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests deploy/tests -q`, `WORKFLOW_TEST_PYTHON=/Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python npm --prefix webui test -- --exclude src/workflow/acceptanceNavigationHttp.test.tsx --reporter=dot`, and `npm --prefix webui run test:bundle`; expected GREEN. Run private E30 separately through `WORKFLOW_ACCEPTANCE_CASES=E30 TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/test_acceptance.py::test_e30 -q` rather than bare Vitest. Record exact command/output/commit and resolve failures before candidate preparation. Do not create tests that merely restate a descriptor table in place of exercising it.
- [ ] Commit exact Task7 tooling/runbook files as `build: require complete mock network candidate and preserve system stores`. The controller reviews all task commits, integrates the accepted final MF SHA and supplies immutable release source; a dirty worktree is not a build input.
**Controller checklist after Task7 tool review and whole-branch approval:** The Task7 implementer completes tooling/tests/commit first. The operations below execute only after the controller has integrated the exact reviewed source to MF main; actual prepare/candidate/cutover remain controller delivery gates, not a reason to build an unmerged or unreviewed worktree. No new user confirmation is required. Runtime packaging may pin the current two required handbook files byte-for-byte in a release-input commit; no semantic editing of user-maintained architecture/handbook/discussion documents.

- [ ] Recapture actual API/image/PF source+static inventories, ordered Compose chain+hashes, mounts/security, other containers, Nginx hash, five workflow fields and logical legacy baseline privately under existing locks. Audit expected values: PF `aff9cbd2b9d413ddee912c8773a0107c717cece3`, MF `642362d95885ecb65bf80645d605b618626ac739`, image `sha256:08485a2b6c7b14f3df6972b59d6f4475e348e268a0f7f6eaecb7e05f529eb59b`,57 inputs,16 mounts,534 PF source/869 static files,34 other containers. If drift, refresh and repin actual facts; never silently force old assumptions.
- [ ] Prepare new root0700 stage and MF-only payload from exact reviewed commit. Preserve actual PF source/static and image patches: empty `build/backend`/`build/static`, `backend_base_hashes={}`, `backend_hashes={}`, `backend_added_files=[]`, `static_hashes={}`; use current actual platform state as previous_manifest. `baseline_workflow` preserves all five values and `target_workflow` is omitted. Do not use unchanged generic assembler that rebuilds PF static from Git.
- [ ] Export pinned fixture/runtime with `candidate_fixture.export_fixture` using exact final MF lock, actual PF SHA/maps/image, manifest inventory and direct Linux-compatible Node version. Create owned512MiB disk-backed candidate evidence with≥65536inodes and required free space; appUID10001 reads fixtures and writes only evidence. No dependencies/tests enter production image.
- [ ] Use existing installer and controller interfaces with fresh artifacts:

```text
python3 <new-private-stage>/install_payload.py <new-private-stage> <payload-tar-sha256>
python3 <new-private-stage>/release.py <new-private-stage> prepare
python3 <new-private-stage>/release.py <new-private-stage> candidate
```

Angle-bracket values are controller-produced exact private artifact identities, never literal shell arguments. `prepare` must prove full57-input Compose replay. `candidate` must run original36 cases plus complete network acceptance in isolated candidate, archive full evidence, remove candidate and independently verify archive hash/inventory/zero failed/zero not-executed results.
- [ ] Produce final preparation handoff containing final MF SHA, actual baseline pins, stage/request/payload/fixture/runtime/evidence hashes,36+network results, all system/edge coverage, schema23 forward-repair policy, existing data baseline, new seed namespace/private manifest destination and verified real owner references. No secret/session values or whole runtime inspect in the report. Explicitly report browser-not-run if applicable.
- [ ] Stop Task7 at reviewed candidate/release readiness. The global controller's already authorized subsequent actions are: reacquire/revalidate locks+baseline; backup old data; cutover only API with all existing inputs plus new overlay; schema23 readiness; run explicit seed CLI as appUID; verify old six projects45SN/history and all new source facts/receipts plus runtime/health/protected401/no-store and unchanged PF/other containers/Nginx. Source-only rollback after schema advance is forbidden; repair forward without restoring old DB snapshots. Do not end the global task claiming success until this actual online cutover and data verification occur.

## Self-review and task completion evidence

- [ ] Map every design section to task: constraints/profiles1; state/network/auth2; physical/accounting/execution3; all other systems/trusted test/auxiliary4; business-context integrated frontend5; three scenarios/legacy preservation6; candidate/release/recovery7.
- [ ] Confirm fifteen system IDs plus legacy ERP, all direction-specific diagram edges and two modeled supporting edges have execution evidence.
- [ ] Check exact interface names and closed unions across Python/TypeScript; no changed old JSON defaults, manual-provenance relaxation, implicit qualifications, bare cross-system sequence comparison or extra inventory posting.
- [ ] Verify candidate fixtures contain new source tests/scripts and actual compiled frontend;36-case success cannot mask skipped new coverage.
- [ ] Verify staged paths belong to each task; old reports, unrelated handbook drafts, source PPT/XLSX/mindle and node_modules stay untouched. Explicitly record Task1’s corrected internal-plan parent SHA and final reviewed release SHA. Do not create the canceled dirty-handbook baseline commit; user-maintained architecture/handbook/discussion documents remain untouched.
