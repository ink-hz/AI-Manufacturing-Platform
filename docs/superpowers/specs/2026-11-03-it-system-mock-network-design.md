# Complete OEM IT system mock network design

Date: 2026-11-03. Accepted direction: the user authorized the complete architecture's separately mocked IT systems, coherent OEM data, and direct deployment to the existing online mock platform. Implement and prepare autonomously; do not add scope or deployment confirmation gates. The global controller performs cutover after final engineering review. This document describes new work; it does not claim those connections exist today. The latest user correction explicitly excludes maintenance of their architecture/handbook/discussion documents: modify only these internal implementation documents and the product. Do not commit a separate dirty handbook baseline or semantically edit those documents; release packaging may read required existing handbook text unchanged.

## 1. Outcome and boundaries

Every named system has its own persisted state and typed operations. A successful demonstration contains the complete chain **operation → durable system state → immutable source event → trusted admission → linked business object/read model → visible frontend evidence**. A catalog entry, authority-rule registration, prefilled manual form, or canned success message does not meet this requirement.

Use one existing backend process and data mount. No vendor-specific HTTP server, new container, plugin framework, broker service or database server is needed. Preserve the current workbench and its business objects; embed each system’s responsibility, input/output, next business action, receipt and blocking conditions in the corresponding existing business workspace. 系统协同 retains adapter configuration/status, source inspection, receipts and recovery; it is not the container for all daily operations. Data received from external systems is visibly mock and keeps its original source identity. The platform still owns collaboration, reviews and mappings; it aggregates externally owned execution facts.

Out of scope: standalone QMS/EAM/APS/IIoT products, live vendor integrations, real AI, complete R10 delivery-package export product, new authentication/login system, real employee qualification grants, and replacement of the current frontend. This is a complete typed mock of the documented architecture, not a vendor application's entire feature set.

## 2. Global constraints

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

## 3. Evidence and present limitations

The company diagram is `docs/oem-ai-manufacturing-platform-discussion.md:97-135`; responsibility map is `:521-534`; identity, conservation and interface contract are `:670-689`. MES includes quality, line-side warehouse, equipment/NPI and genealogy. HR products are grouped in source material; their field ownership below is a modeled example. SRM is planned. Customer/overseas are distinct modeled boundary endpoints. These labels are displayed, not hidden in implementation notes.

Current `workflow/adapters/mock.py:43-46` accepts only `erp`; it aggregates inventory, IQC, production, shipment and holds. `exchange_models.py:31,301-343` allows only three inbound types. `imports.py:111-114` and `laboratory_models.py:39-47` reject nonmanual execution/test acquisition through public commands. `authority.py:1,67-72` records responsibility evidence rather than providing runtime routing. New paths must solve these limitations while preserving existing behavior.

Reuse `WorkflowService.execute` operation UUID, project CAS, policy, audit and post-commit I/O protocol (`service.py:763-890`), `ExchangeService` receipt validation and recovery (`exchanges.py:408-707`), and source admission (`imports.py:128-155,271-307`). Refactor shared pure/domain helpers only as required; do not rewrite established registries or business domains.

## 4. Typed boundaries and file ownership

New package `workflow/integrations/` separates these responsibilities:

| File | Responsibility |
| --- | --- |
| `contracts.py` | System/profile/source IDs, descriptors, source envelopes, receipts, closed operation/payload unions assembled from family models |
| `core_models.py` | SAP/WMS/MES payload and fact types, quantity/identity contracts |
| `enterprise_models.py` | PDM/CRM/OA/HR/SRM payload and fact types |
| `evidence_models.py` | Test/PLC/customer/overseas/BI payload and fact types |
| `catalog.py` | Fixed capabilities, policy mapping, modeled maturity and edge manifest |
| `routing.py` | Immutable profile route selection; legacy fallback; per-intent adapter lookup |
| `schema.py` | Additive workflow profile/intent/projection/link tables and migrations |
| `store.py` | One-system file validation, transactional event/operation/inbox/outbox storage |
| `network.py` | Bounded durable intersystem delivery and acknowledgments |
| `operations.py` | Registered mock command prepare/perform/apply using existing authorization/CAS/audit |
| `browse.py` | Project-scoped typed read APIs, source/object relations and runtime status |
| `core_systems.py` | SAP/WMS/MES state machines; shared types, distinct stores |
| `enterprise_systems.py` | PDM/CRM/OA/three HR/SRM state machines; distinct stores |
| `evidence_systems.py` | Product-test/PLC/customer/overseas/BI state machines; distinct stores |
| `core_projections.py` | Trusted core fact admission into current domain objects |
| `enterprise_projections.py` | Trusted enterprise fact admission and typed HR read models |
| `evidence_projections.py` | Trusted test/external fact admission and typed PLC/BI read models |

The package may split a family file when its state machines become difficult to review; do not merge these layers into one large mock service. Shared infrastructure never determines business ownership from freeform JSON.

Normative interfaces (all IDs are UUID unless stated):

```python
SystemId = Literal['sap','pdm','crm','oa','hr_sap','hr_beisen','hr_dingtalk',
                   'mes','wms','product_test','plc','bi','customer','overseas','srm']
ConnectorId = SystemId | Literal['erp']  # descriptors only; new operations exclude erp
ProfileId = Literal['legacy-erp-v1','oem-network-v1']
# SourceKey includes system, object_type, external_id, version.
# IntegrationFact includes SourceRef(mode='mock'), project_id, payload (closed
# discriminated union), external_actor, evidence, caused_by: list[SourceKey].
# SystemOperation includes operation_id, system, project_id, payload (closed union).
# SystemReceipt includes operation_id, system, request_hash, phase,
# source_keys, sequence, occurred_at, received_at, posted_at | None, error | None.
class SystemAdapter(Protocol):
    def execute(self, operation: SystemOperation) -> SystemReceipt: ...
    def query(self, project_id: UUID, operation_id: UUID) -> SystemReceipt | None: ...
    def facts(self, project_id: UUID, object_type: str, cursor: int, limit: int) -> FactPage: ...
    def consume(self, delivery: NetworkDelivery) -> DeliveryReceipt: ...
class SystemRegistry:
    def adapter(self, system: SystemId) -> SystemAdapter: ...
    def route(self, profile: ProfileId, action: str) -> str: ...
    def legacy_adapter(self) -> AuthorityAdapter: ...
class MockNetwork:
    def drain(self, project_id: UUID, *, limit: int = 100) -> DeliveryBatch: ...
def project_fact(tx, context: CommandContext, fact: IntegrationFact) -> ProjectionResult: ...
```

`SystemDescriptor.system` is `ConnectorId`, so the legacy connector is visible without admitting it into new-operation models. `ProjectionResult` contains `source_key`, payload hash, target `ObjectRef` list and auxiliary read-model references; all references carry project ID. `FactPage` contains typed records, opaque-or-integer continuation and source cutoff. Each read is project-scoped at SQL query time and bounded to 1–200 records. No broad snapshot followed by Python authorization filtering.

### 4.1 Closed business operations and required facts

Operation names are payload discriminator values; the outer command action is `mock_system.execute`. Every operation's exact model forbids extra fields and has a named underlying business policy. IDs are selected by the GUI; server checks project, source type/version and causal relations.

| System | Operations | Fact/output and policy family |
| --- | --- | --- |
| SAP | `sap.release_order`, `sap.release_work_order`, `sap.publish_plan`, `sap.post_movement`, `sap.post_completion` | Order/WO/plan, accounting entries with unique WMS/MES cause; existing order/WO/plan/supply policies |
| WMS | `wms.receive`, `wms.putaway`, `wms.reserve`, `wms.pick`, `wms.return`, `wms.stocktake`, `wms.ship` | Physical receipt/location/movement/reservation/shipment; warehouse/supply policies; stocktake appends variance evidence, never edits balance |
| MES | `mes.inspect`, `mes.start`, `mes.interrupt`, `mes.resume`, `mes.switch_revision`, `mes.pass`, `mes.assemble`, `mes.contain`, `mes.release`, `mes.complete` | IQC/execution/component/hold/OQC/completion, line-side custody and equipment/NPI references; production/inspection/disposition/release policies |
| PDM | `pdm.publish_revision`, `pdm.issue_change` | Controlled revision/BOM/ECN mapped to engineering/ECO |
| CRM | `crm.publish_demand`, `crm.open_return` | Demand/SAP order link/RMA mapped to existing demand/RMA |
| OA | `oa.request_approval`, `oa.decide_approval` | Target/version-bound approval workflow; engineering or quality policy selected by target type |
| HR SAP | `hr_sap.publish_employee` | Employee/org identity, never an authentication principal |
| HR 北森 | `hr_beisen.publish_qualification` | Training/qualification expiry tied to HR employee; never platform grant |
| HR 钉钉 | `hr_dingtalk.assign_shift` | Shift/attendance assignment tied to employee and MES work order |
| Product test | `product_test.run`, `product_test.calibrate` | Test attempt, program/spec/algorithm version, raw artifact reference/checksum; independent PLC readback required for confirmation |
| PLC | `plc.set_state`, `plc.sample`, `plc.readback` | Equipment state, process sample and independent readback; MES/test consume them |
| Customer | `customer.approve_revision`, `customer.confirm_delivery`, `customer.map_serial` | Customer approval, signed delivery/acceptance claims, SN mapping |
| Overseas | `overseas.receive_shipment`, `overseas.report_return` | Scoped downstream receipt/quality/return claim linked to local shipment/SNs |
| SRM | `srm.promise`, `srm.announce_arrival` | Supplier commitment/ASN/COA tied to SAP purchase requirement; marked planned |
| BI | `bi.refresh` | Read-only metric snapshot with source cutoff, formula version, numerator/denominator, source references |

Minimum payload rules: orders include customer/product/quantity/unit/due date; work orders bind order line/released revision/quantity/trial quantity; plans carry requirement owner/material/lot unit/scale/cutoff. Receipt references commitment and lot, quantity/unit/owner/location/supplier batch; IQC references full WMS receipt SourceKey and accepted/rejected quantities. Movement references qualified lots, exact quantities, source/destination custody and cause. Execution binds work order/unit/revision/operator/shift/equipment/operation time/material-lot use. Tests bind unit/plan/run/versions/result and evidence; approvals bind target source key/decision/external signer. Claims carry exact shipment/SNs/quantity and signed evidence. Generic evidence text cannot substitute for these structured fields.

An internal operation may emit multiple facts in its own transaction (e.g. WMS pick emits movement and custody); it cannot perform another system's transaction. Existing authority-backed public actions use `route(profile, action)` with a new core adapter translating `ExternalRequest` to its system state machine without changing the persisted request. New source-side operations use `SystemOperation`; they must not bypass an existing applicable readiness gate merely because they are mock controls.

### 4.2 Immutable state, network and accounting

Each system DB stores metadata `(dataset_id, system_id, schema_version)`, operation intent/hash/receipt, immutable typed facts with increasing local sequence, domain state, inbox, outbox, and narrowly scoped faults. The outbox is committed with the source fact. Inbox uniqueness is `(producer_system, object_type, external_id, version)` with canonical hash. An equal duplicate returns prior acknowledgment; changed content fails `SOURCE_CONFLICT`. Outbox acknowledgment happens only after consumer commit; a crash between commits replays safely. `drain` is bounded, explicit, resumable and not a hidden background thread. Query/refresh and explicit retry can advance pending deliveries.

System file identity rejects symlinks/hardlinks/aliases outside the fixed root and wrong metadata. Relative filenames never come from browser input. Lazy opening only in demo/test ensures legacy projects do not initialize the whole network. Separate files provide independent state; business logic can share code.

WMS is authoritative for physical receipt/reservation/movement/location; MES owns IQC/holds/execution; SAP owns accounting. MES IQC references the WMS receipt, WMS qualification consumes it exactly once, SAP posts a WMS movement exactly once. Projection into the platform is not another stock movement. Exact owner/unit/scale/lot/quality/allocation/custody dimensions are validated; integer atom arithmetic and conservation remain enforced. Partial IQC/replenishment are separate facts. A stocktake discrepancy appends an authorized variance fact, preserving the original ledger.

MES containment publishes to WMS and SAP plus platform; pending/unknown downstream acknowledgments conservatively block affected reservation/start/shipment. Release does not unblock before required downstream acknowledgments. Production control ordering remains one MES stream for a new work order; use explicit causal references between streams, never compare bare SAP/WMS/MES sequence numbers. Existing legacy work orders remain entirely in the ERP stream.

Faults: `reject`, `partial_quantity`, `timeout_after_commit`, `stale_sequence`, `wrong_unit`, `changed_detail_same_total`, `none`, bound to exact project/system/operation or named delivery with one-shot count. Only private candidate/seed controls may configure faults initially; public UI can retry/query normal failures, not globally poison another user's system.

### 4.3 Trusted projection and authorization

Retain public manual/file provenance checks. Introduce closed trusted fact models and internal projectors that preserve `SourceRef.mode='mock'`, then invoke shared domain validation/persistence helpers. Do not relabel trusted execution/test facts manual; do not relax public command validators. Each fact's linked entities and source identity are admitted before evidence is visible. Duplicate projection returns identical ObjectRefs; changed detail conflicts. Projectors run in the workflow mutation transaction, without network I/O or nested `WorkflowService.execute`.

`mock_system.execute` authorizes the selected underlying policy (including quality qualifications), stores intent + canonical hash in the existing operation/CAS/audit boundary, then performs I/O after commit. Final application reauthorizes and compares project version. Losing CAS leaves source committed and intent recoverable; retry queries the same operation. `mock_system.query`, `mock_system.retry`, and `integration.pull` authorize the original operation/source policy. Neither mock mode nor project-owner role implicitly grants inspection/release qualifications.

HR/PLC/BI have typed auxiliary readers with lineage. HR qualification evidence can affect mock MES operator eligibility but cannot modify application `grants`. OA and customer approval are distinct. Supplier COA and customer/overseas receipts remain counterparty claims. Host users, employee identities and external signers are separate concepts.

### 4.4 Runtime API and UI

Add authenticated reads under current workflow prefix:

- `GET /projects/{project_id}/systems`: descriptors with mode/maturity, capability and permitted-operation lists, per-project connectivity/last receipt/pending counts. “Mock connected” requires adapter health and real stored round-trip evidence; capability-only systems show configured/unexercised.
- `GET /projects/{project_id}/systems/{system}/facts?object_type=...&cursor=...&limit=...`: bounded typed source browser, source cutoff and projection relations.
- `GET /projects/{project_id}/systems/{system}/facts/{object_type}/{external_id}?version=...`: admitted project-scoped detail and causal predecessors/receipts.
- Mutations remain `POST /projects/{project_id}/commands` using existing operation UUID/project expected version, with `mock_system.execute`, `mock_system.query`, `mock_system.retry`, `integration.pull` closed command types.

Embed reusable `SystemStepPanel` and typed operation forms in the existing business workspaces, driven by `businessSteps.ts` rather than duplicating forms or adding fifteen navigation items. Every step names its responsible system, consumed facts, produced business objects, next permitted action, latest receipt and specific blocker. Selected business context binds source/object IDs automatically; users choose readable business references and enter business fields, never UUID/JSON. Fetch server capability/allowed-action data; never assume `demo` means unrestricted actions. Business object details and trace results link original system/source/version/receipt and causal predecessor.

| Existing business context | Integrated steps and observable result |
| --- | --- |
| Orders (`OrdersWorkspace`, ordinary mode) | CRM demand → SAP formal order; demand/order identity, customer, commitment and SAP acceptance remain visible together |
| Engineering (`OrdersWorkspace`, engineering mode; `IntroductionWorkspace`) | PDM released material/BOM/change → OA workflow and separate contractual customer approval → fixed MES work-order revision; missing approval/version and explicit ECN boundary block next step |
| Supply and handoff | SAP plan/requirements → WMS receipt/location → MES IQC → WMS qualification/reserve/pick → named-person manual handoff; SAP posts each relevant physical movement once. Show pending IQC/shortage/receipt and physical-versus-accounting distinction |
| Execution | MES work/order/pass with HR employee, position/training/qualification and shift inputs plus PLC equipment/process acknowledgment; expired evidence, wrong revision, pending hold or unavailable device blocks operation |
| Laboratory and quality | Product-test run/calibration → independent PLC readback → MES quality evidence/release; mismatched readback, failed test or hold acknowledgment blocks release |
| Delivery | WMS actual shipment → SAP posting → separate customer/overseas receipt and acceptance claims; preserve signer, exact SN/quantity and pending discrepancies |
| Trace | Read-only composition of PDM revision, SAP document, WMS lot/movement, MES execution/components, test/readback and external delivery; follow source and causal links without creating a second fact ledger |
| Home BI (`WorkflowHome`) | Read-only SAP/MES-derived yield/shortage/delivery snapshots with source cutoff, formula and drill-down; a refresh creates a new derived snapshot, never edits source facts |

HR and PLC auxiliary facts appear where execution/tests consume them; BI appears on home and related business summaries. `ConnectedSystemsWorkspace` remains under `ExchangeWorkspace` for configuration/capability/status, bounded diagnostic source inspection and receipt/retry/reconciliation. It must not be the only place to discover or perform normal business operations. Show modeled ownership/direction as “模拟契约”; it is not a claim that actual SAP/MES/WMS field directions were verified.

Show separate descriptors for legacy ERP, modeled HR/customer/overseas and planned SRM. Existing `authority_rule` remains responsibility evidence; no inference from registration origin to actual connected state. UI distinguishes unexercised, pending, connected-mock, degraded and unavailable; none imply real API/vendor connectivity.

## 5. Complete edge acceptance matrix

For every arrow below capture operation ID, producer source key/hash, consumer inbox acknowledgment, projected ObjectRef/auxiliary reference, and frontend-visible source/receipt in the consuming business workspace. Scenario coverage also records business-step ID, workspace, responsible system, input/output references, next action and blocker/receipt state. Bidirectional arrows require evidence both ways. Each source read and action also needs a negative cross-project authorization case.

| Diagram edge | Required real mock flow |
| --- | --- |
| SAP ↔ MES | SAP WO/BOM/plan accepted by MES; MES completion/consumption returned to SAP posting |
| SAP ↔ WMS | SAP material/PO/order intent to WMS; WMS receipt/issue/shipment to SAP accounting and acknowledgment |
| SAP ↔ PDM | SAP material/BOM request context to PDM; released BOM/ECN back to SAP |
| PDM → MES | ECN/revision release causes explicit MES remaining-work switch while preserving old unit revisions |
| WMS ↔ MES | WMS receipt/lot/pick to MES; MES IQC/hold/consumption/return requirement to WMS |
| OA ↔ MES | MES NPI/quality approval request to OA; version-bound OA decision back to MES |
| HR → MES | Employee, qualification/expiry and shift from all three HR IDs accepted as operator references |
| CRM → MES | CRM return scoped to shipped SN enters MES containment/rework evidence |
| MES ↔ product test | MES work/route/unit request to test; test run/result/calibration evidence back to MES |
| MES ↔ customer/overseas | Product/quality/shipment references exported to each endpoint; approval/delivery/return claims returned and linked |
| PLC ↔ MES | MES process/program request acknowledged by PLC; equipment/process sample returned to exact MES session |
| SAP → BI | Accounting/order/delivery events feed immutable cutoff snapshot |
| MES → BI | First/final test and execution results feed yield snapshot without duplicate retry denominator |
| Planned SRM ↔ SAP/WMS | SAP purchase requirement to SRM; promise/ASN/COA to supply/WMS arrival; explicit planned label |
| Product test ↔ PLC | Calibration write reference and independently identified readback; mismatch blocks confirmation |

The last two are explicit modeled supporting edges, not invented claims about the source company's current installations. Named inbound consumer operations such as SAP BOM-context requests and MES process/test requests may be emitted as part of listed operations; their event types still require closed models and edge receipts.

## 6. Three coherent added scenarios

Namespace `it-mock-20261103-v1`; append three projects, do not reseed old portfolio. Deterministic IDs are namespaced by dataset/scenario/system/type/key. Manifest contains original timestamp, source times, operation IDs, intended results, project versions, source event hashes, receipts, projections, edges and intentional starting checkpoints. Frozen clock fixtures are candidate-only; online facts use captured real time and valid future expiry/due dates.

1. **Customer OEM completion and overseas branch**: customer/CRM demand → SAP order/WO/plan → PDM approved revision → OA NPI request/decision → HR employee/qualification/shift → SRM planned supplier ASN plus customer-supplied material → WMS receipt/putaway → MES IQC → WMS reserve/pick/SAP issue → named real-owner handoff → MES/PLC execution/components → test/calibration independent readback → OQC/release → WMS shipment/SAP posting → customer and overseas signed claims → BI. Seed one branch completed for evidence and another ready-to-advance work order in the same scenario; cannot seed only completed screens.
2. **Shortage and rejected IQC recovery**: order12; first receipt10, accepted8/rejected2; qualified shortage4; reserve12 blocked. Seed at blocked state with explicit source evidence and supplier promise. Run normal replenishment4 → IQC4 → qualified12 → reserve12/pick/production; SAP posts each physical event once. Stocktake discrepancy and return use separate immutable variance/return facts. Customer ownership remains unchanged.
3. **ECN, failed test, containment and return**: partially started WO; PDM ECN/OA approval → split remaining work; retain old units' revisions. Test failure creates MES containment, downstream WMS shipment denied; unknown-after-commit is recovered by query with same operation ID. Rework/retest/independent readback permits release; CRM and overseas return claims link shipped SN and containment. Seed at an actionable review/retry checkpoint; candidate completes recovery and validates BI first-pass denominator.

Seed operations use an audited server-only maintenance principal established by the existing importer pattern; it is not a login or hidden grant. Do not create test accounts or borrow sessions. Verify real owner IDs against existing host metadata, attach appropriate existing project ownership through supported APIs, and select a verified real owner as pending handoff recipient where useful. Seeded source HR qualifications are fictional evidence and never application authorization. Users without quality qualifications see the blocked requirement and can perform their authorized operations; the seed must not silently give them quality power.

Before/after logical baseline asserts unchanged six-project/45-SN identities, versions, grants, immutable histories and ERP authority rows. Total counts may increase only for newly owned namespace facts. Idempotent resume after a crash reconciles operation IDs and source receipts before retry; `--verify-only` does no business mutation. Missing manifest with an existing namespace fails closed.

## 7. Legacy and recovery invariants

Do not rename `erp` to `sap`, rewrite old source JSON, recompute request hashes, reset sequences, copy its inventory into new authority stock, or transfer an active legacy work order between streams. Existing legacy requests/query/stock proofs keep their old adapter/database. No old payload gains serialized defaults merely because new types exist. Profile initialization is maintenance-only in this release: the new seed follows create project → assign `oem-network-v1` → first domain intent for exactly its three owned scenario projects. Users continue normal operations in these projects. The six old projects and other publicly created projects without a profile remain `legacy-erp-v1`; their UI shows legacy or unconfigured capabilities rather than fabricated network connectivity. Do not add a public ProjectCreate field, change its canonical replay hash, or change default test-mode ERP routing. The project-creation audit alone is not a business intent. New request target selection happens once, before canonical hashing. Existing serializers preserving omitted fields remain intact.

Workflow schema23 adds profile, integration intent/projection/link metadata. System DB schemas are independently versioned. Migration from21 includes existing22 material handoff before23; snapshot comparison proves no business rows are seeded during migration/readiness. Any deployment after schema advance repairs forward; old schema21 code is not a rollback target. Never edit schema_version, delete WAL/SHM, or restore an old backup over live writes.

New system stores live under the existing mount. Release backups must enumerate already initialized per-system DBs from the server-owned fixed catalog, in addition to legacy/workflow/ERP, exclude unexpected/aliased files and preserve metadata. Per-file consistent backups do not imply atomic cross-system backup; network inbox/outbox reconciliation is the recovery mechanism. First release may correctly report the new stores absent before explicit seed. Future releases must not omit them.

## 8. Delivery verification and release handoff

Review seven implementation commits/tasks with meaningful RED/GREEN evidence; new brief/report artifacts use the new SDD directory. The scenario manifest covers every business step in section4.4; fifteen system cards alone cannot satisfy UI acceptance. Run Python domain/import/exchange/authorization/legacy tests, React business-context controls and source links, including HTTP-backed journeys starting from existing workspaces across at least three system families, build/bundle, seed restart/idempotency, every system and edge, and deploy migration/recovery tests. Candidate retains its existing exact36 cases and adds separate pinned `it-mock-network-v1` socket/React/seed evidence. Missing or skipped new acceptance fails release preparation.

Audited live baseline from `/tmp/online-mock-release-readiness.md`: MF `642362d95885ecb65bf80645d605b618626ac739`, PF `aff9cbd2b9d413ddee912c8773a0107c717cece3`, image `sha256:08485a2b6c7b14f3df6972b59d6f4475e348e268a0f7f6eaecb7e05f529eb59b`, 57 Compose inputs, 16 mounts, 534 PF source and869 static files, 34 other containers. These are audit facts to recapture, not permanent assumptions. Preserve existing unrelated runtime patches and existing unhealthy platform-brain baseline. No Nginx change/reload or standalone nginx config validation.

Build MF-only from reviewed exact committed sources, preserve actual PF maps with empty PF backend/static overlays and actual platform state pointer. Prepare fixture/runtime from exact lock; do not ship tests or Node dependencies in production. Controller prepare must prove full-chain replay; candidate runs UID10001/networknone/readonlyroot with pinned owned512MiB evidence filesystem. Verify all36 results plus new network evidence and archive inventory/hash.

Task7 hands over candidate/release-ready artifacts only. After global final review the controller executes already-authorized cutover, consistent backups, schema23 readiness, explicit new seed CLI with private manifest and verified real owner, then online runtime/source/data/health/protected-route checks. Preserve the current five workflow config values; only MF source bind changes. Never report browser verification if it was not performed; no borrowed employee session is permitted. Completion requires actual online profile/source data/operation receipts and preserved legacy baseline, not staging success alone.
