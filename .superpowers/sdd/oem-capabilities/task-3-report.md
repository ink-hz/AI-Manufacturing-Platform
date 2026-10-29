# Task 3 implementation report

Status: DONE_WITH_CONCERNS (the one configured full-suite run preceded the final six-mode/presentation edits; its sole failure was the exact registry allowlist, now fixed and verified by focused regressions. Parent explicitly owns the final integrated full run).

Branch: `feat/oem-manufacturing-capabilities`. Worktree: `/Users/neo/Developer/work/AI-Manufacturing-Platform/.worktrees/oem-manufacturing-capabilities`. Base: `a90dacd303d2bb0932af354d898b2cf42a19c9e3`.

## Delivered behavior and boundaries

- Registered `authority_rule` and `arrival` in the existing ObjectRegistry, and four real commands in CommandRegistry. Writes use unchanged WorkflowService live policy, operation UUID replay, project CAS, real actor audit and private/no-store HTTP handling. Engineering/project_owner may register/verify mappings; warehouse/supply may record/match observations. Global trusted owner/admin inherits all registered actions without new grant rows. Ordinary project roles remain scoped.
- Authority registration records a proposed system/object category/business scope/responsible identity/evidence. Re-registering a normalized scope creates its next immutable revision; the latest revision is the active projection. Contract verification is separate, attributable and immutable. HTTP cannot specify connection state; derived states are only `unconnected` or `demo`. No authority-rule handler is read by production/source selection, and neither action touches inventory, exchanges or in-flight production facts. Mock adapter availability does not promote an arbitrary registered system to a connection.
- Arrival is an actual known-project package observation, before material/PO identity. No PO, material lot or inventory identity is required. Manual SourceRef, original arrival number, location, integer package count and description are recorded with authenticated actor/time. Actual receipt matching requires a same-project existing supply receipt. Corrections require a nonblank reason; every match retains previous_receipt_id, evidence, actor/time in append-only history. Original observation and audit are retained. The commands create no material, stock, IQC, reservation, exchange, consumption or source-confirmation facts.
- Assistance is GET-only, deterministic, `mode=rules`, and explicitly reports no-evidence/unknown/truncated states. Every item references a real project object or an approved public catalog entry. Six kinds: introduction, materials, change, knowledge, testing, quality. It never invokes a model, guesses an arrival, approves a customer/quality outcome or submits commands. Public knowledge content uses only public_content_json; source project/issue/history/private content remain protected.
- Testing returns recorded test/run states, exact measurements and out-of-bound measurements. Similarity references use the same object kind, pinned revision and program, with no causal/predictive claim. Quality returns an `8d_evidence_draft`: actual NCR/RMA facts, registered CAPA containment/causes/actions/verification, including recorded false effectiveness and explicitly absent team/prevention/recognition or missing step fields. It does not invent causes, a team, effectiveness or closure.
- Receipt presentation derives `pending_inspection`, `partially_inspected`, `accepted`, `rejected`, `mixed` from existing effective received/accepted/rejected atom calculations. `next_step` is inspect_remaining/review_rejected/await_authority_reservation. The summary offers supply.inspect only while actual uninspected quantity remains; live role filtering still applies. No accounting algorithm or reservation authority was changed.

## Schema

Schema **21**, additive from **20**. New tables: authority_rules, authority_verifications, arrivals, arrival_matches, with scoped paging/history indexes. Existing data is not rewritten. A schema20 HTTP reopen test drops only these new tables, migrates, verifies exact old project/operation/audit/material/IQC/reservation/source rows, then records a new observation. Existing schema19 laboratory migrations continue to target SCHEMA_VERSION.

## Exact API and command contracts

API prefix: `/api/v1/manufacturing/workflow`.

- `POST /projects/{project_id}/commands`: existing command endpoint for all four actions.
- `GET /projects/{project_id}/objects/authority_rule[/{id}]` and `/objects/arrival[/{id}]`: existing typed project-scoped page/detail endpoints. Pages accept existing limit/offset. Details retain evidence, relations, audit history and live next_actions.
- `GET /projects/{project_id}/assistance?kind=introduction|materials|change|knowledge|testing|quality`: `AssistanceResult`. Invalid kind is 422; inaccessible/revoked project is 404; POST is 405. Successful read-only actors may GET.

All commands inherit `operation_id: UUID`, `expected_version: strict int >= 1`; all named DTOs forbid extra fields. `Name` is strict stripped nonblank text <=200 chars and `Text` is strict stripped nonblank text <=2000 chars. `SourceRef` is the existing strict DTO (system, object_type, external_id, version, mode, occurred_at, collected_at, cutoff, evidence).

```python
RegisterAuthority(
  action: Literal['authority.register'],
  object_category: ObjectKind, business_scope: Name, system: Name,
  responsible_identity: Name, evidence: Text, origin: Literal['manual','demo'])
VerifyAuthority(
  action: Literal['authority.verify'], rule_id: UUID, contract_evidence: Text)
RecordArrival(
  action: Literal['arrival.record'], arrival_number: Name, location: Name,
  package_count: strict int[1..100000], description: Text, source: SourceRef)
MatchArrival(
  action: Literal['arrival.match'], arrival_id: UUID, receipt_id: UUID,
  evidence: Text, correction_reason: Text | None = None)
```

RecordArrival requires source.mode=manual, source.object_type=arrival, nonblank source evidence, and already occurred/collected observation times with collection >= occurrence. MatchArrival rejects redundant same-receipt matches, missing correction reasons, foreign receipts/arrivals and an initial match mislabeled as a correction.

Read DTOs:

```python
AuthorityVerification(contract_evidence: Text, actor_id: UUID, recorded_at: datetime)
AuthorityRule(kind='authority_rule', id: UUID, object_category: ObjectKind,
  business_scope: Name, system: Name, responsible_identity: Name, evidence: Text,
  origin: Literal['manual','demo'], revision: int, supersedes_id: UUID | None,
  actor_id: UUID, recorded_at: datetime, active: bool,
  state: Literal['registered','verified'], connection_state: Literal['unconnected','demo'],
  verification: AuthorityVerification | None)
ArrivalMatch(id: UUID, receipt_id: UUID, previous_receipt_id: UUID | None,
  evidence: Text, correction_reason: Text | None, actor_id: UUID, recorded_at: datetime)
Arrival(kind='arrival', id: UUID, arrival_number: Name, location: Name,
  package_count: int, description: Text, source: SourceRef, actor_id: UUID,
  recorded_at: datetime, state: Literal['unlinked','matched'],
  receipt_id: UUID | None, matches: list[ArrivalMatch])
AssistanceTarget(scope: Literal['project','public_catalog'],
  project_id: UUID | None = None, kind: ObjectKind, id: UUID)
ReceiptQuantities(accepted: NonnegativeQuantity, rejected: NonnegativeQuantity,
  pending: NonnegativeQuantity, unit: str)
TestingEvidence(revision_id: UUID, program_version: str,
  run_state: Literal['running','completed','aborted','invalid'] | None,
  outcome: Literal['pass','fail'] | None, measurements: list[Measurement],
  failed_measurements: list[Measurement], current_qualified: bool | None,
  origin: Literal['manual','demo'] | None,
  comparison_basis: Literal['same_revision_and_program']='same_revision_and_program',
  similar_targets: list[AssistanceTarget]=[])  # max 20
QualityOutline(format: Literal['8d_evidence_draft']='8d_evidence_draft', facts: list[str],
  containment: list[CapaStep]=[], registered_causes: list[CapaStep]=[],
  actions: list[CapaStep]=[], verification: list[CapaStep]=[],
  disposition: str | None=None, disposition_evidence: str | None=None,
  missing_fields: list[str])
AssistanceItem(target: AssistanceTarget, title: str, state: str, suggestion: str,
  blockers: list[str], unknowns: list[str], evidence: list[str],
  related_targets: list[AssistanceTarget]=[], source: SourceRef | None=None,
  quantities: ReceiptQuantities | None=None, material_balance: MaterialBalance | None=None,
  public_asset: PublicAssetEntry | None=None, testing: TestingEvidence | None=None,
  quality_outline: QualityOutline | None=None, evidence_truncated: bool=False)
AssistanceResult(project_id: UUID, kind: AssistanceKind, mode: Literal['rules']='rules',
  state: Literal['evidence_available','no_evidence'],
  source_scope='authorized_project_and_approved_public_catalog',
  items: list[AssistanceItem], unknowns: list[str], truncated: bool)
```

The existing ReceiptValue gains required quantity_state and next_step enums listed above; all other fields retain their original meaning. Existing Measurement, CapaStep, PublicAssetEntry and MaterialBalance DTOs are reused without changes. CapaStep carries sequence/basis_sequence, registered step/description/evidence/effective/action_kind/implementation_evidence/eco_id. `effective` is recorded source evidence, never a generated conclusion.

Example command bodies (replace sample UUIDs and obtain the current project version before each new action):

```json
{"action":"authority.register","operation_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1","expected_version":1,"object_category":"receipt","business_scope":"customer-supplied material","system":"candidate WMS","responsible_identity":"Warehouse lead","evidence":"proposed contract v1","origin":"manual"}
{"action":"authority.verify","operation_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2","expected_version":2,"rule_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1","contract_evidence":"reviewed receipt contract and responsibility scope"}
{"action":"arrival.record","operation_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3","expected_version":3,"arrival_number":"SCAN-001","location":"receiving shelf","package_count":2,"description":"sealed packages; material identity unverified","source":{"system":"manual receiving desk","object_type":"arrival","external_id":"desk-record-001","version":1,"mode":"manual","occurred_at":"2026-10-28T08:00:00+00:00","collected_at":"2026-10-28T08:01:00+00:00","cutoff":null,"evidence":"signed package observation"}}
{"action":"arrival.match","operation_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa4","expected_version":4,"arrival_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2","receipt_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb3","evidence":"actual package and receipt label checked"}
{"action":"arrival.match","operation_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa5","expected_version":5,"arrival_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2","receipt_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb4","evidence":"second receipt label checked","correction_reason":"first receipt selected incorrectly"}
```

## RED/GREEN evidence

All commands below run from this worktree with:

```sh
TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest ... -q
```

1. Initial corrected HTTP RED: `tests/workflow/test_authority_assistance.py tests/workflow/test_arrivals.py` -> **7 failed** (0.95s), missing authority/arrival actions and missing assistance route. Early first probe exposed missing fixture grants; those were corrected before recording feature RED. Raw corrected RED: `/tmp/oem-task3-red.log`.
2. First implementation GREEN, same command -> **7 passed** (1.58s).
3. Expanded NPI/ECO/public sanitization/migration/replay coverage was included in the 79-pass regression after correcting a pre-existing source project grant in the fixture. Adding limit/live-summary checks and running the focused paths -> **13 passed** (3.46s).
4. Explicit suggestion RED: `tests/workflow/test_authority_assistance.py::test_material_assistance_actual_partial_iqc_and_pending_identity` -> **1 failed** (0.42s), absent suggestion; GREEN of the focused paths -> **13 passed** (3.79s). RED: `/tmp/oem-task3-suggestion-red.log`.
5. Six-mode extension: valid actual HTTP fixtures with four-mode API contract -> **2 failed, 9 deselected** (0.90s), expected 422 for missing testing/quality kinds; restore six-mode contract/handlers -> **2 passed, 9 deselected** (1.03s). The first expanded test probe caught an invalid attempt to retest failure without rework; fixture corrected to a real prior passing measurement followed by failed run finish. Sensitivity RED: `/tmp/oem-task3-six-modes-valid-red.log`.
6. Complete IQC action-presentation RED: `tests/workflow/test_authority_assistance.py::test_receipt_complete_iqc_presentation_does_not_offer_inspecting_remaining_quantity` -> **1 failed** (0.38s), fully inspected receipt still advertised supply.inspect. Fixed scoped candidates while retaining registry authorization; final focused run below verifies.
7. Pre-final focused supply/source/authorization run -> **79 passed** (25.40s).
8. Configured full workflow run, exactly once: `tests/workflow` -> **1 failed, 539 passed, 35 skipped** (315.41s). Sole failure: `test_a1_extensions.py::test_extension_contracts_exist_and_production_registry_contains_only_real_actions`, old exact allowlist missing the four newly registered real actions. Updated just those four expected entries. This was before final six-mode/presentation changes; do not describe it as a final green full run. Parent explicitly requested final full integrated regression later, not a second broad run here.
9. Expanded regression after six-mode code and allowlist update: `tests/workflow/test_authority_assistance.py tests/workflow/test_arrivals.py tests/workflow/test_a1_extensions.py tests/workflow/test_a1_security.py tests/workflow/test_supply.py tests/workflow/test_source_manifest.py tests/workflow/test_source_history_binding.py tests/workflow/test_d3_authorization.py tests/workflow/test_action_capabilities.py tests/workflow/test_final_grants.py tests/workflow/test_laboratory.py tests/workflow/test_quality.py tests/workflow/test_feedback.py` -> **173 passed** (71.64s). This run preceded the final complete-IQC summary adjustment.
10. Focused regression after complete-IQC adjustment: same command as #9 without laboratory/quality/feedback -> **100 passed** (30.78s).
11. Final fresh authority/arrival/assistance run after the last bounded family-query refinement: `tests/workflow/test_authority_assistance.py tests/workflow/test_arrivals.py` -> **16 passed** (4.33s).
12. `git diff --check -- src/manufacturing_platform/workflow tests/workflow` -> clean. The unrelated user's handbook diff contains pre-existing trailing whitespace and was not edited or staged.

Tests compare exact material_lots/supply_receipts/iqc_results/reservations/material_consumption/source_corrections/source_confirmations contents across arrival record/match/correction/replay. Testing/quality assistance compare **all application tables** before/after reads; materials checks operations/audit counts plus accounting tables. Scope, foreign receipt/arrival refusal, revocation, current roles, readonly, CAS, CSRF, conflicting UUID replay, preserved history and actual source evidence are exercised through real HTTP fixtures.

## Self-review and limits

- No source adapter or connection machinery was changed; mappings are intentionally not production routing configuration.
- Assistance examines at most 100 objects per source category, 100 candidate published assets and 100 actual introduction families; comparisons show at most 20 references. Truncation is explicit. Existing typed readers retain their own bounded test/step/history behavior; inherited object detail semantics are unchanged.
- No runtime dependency, frontend, user handbook, PPT, dependency symlink, browser/employee session, production/deployment or messaging changes. Parent-authored specification/plan edits remain outside this commit. Historical tracked `.superpowers/sdd/task-1-report.md` has no diff.
- Known verification concern: final branch full-suite verification is intentionally deferred to parent as instructed. No remaining focused test failures are known.

## Review fix: bounded arrival correction evidence (2026-10-29)

Addressed the single Important finding in `task-3-review.md` on base `85b4e82`.

- Arrival summaries now read the original observation payload, latest scoped receipt with `ORDER BY seq DESC LIMIT 1`, and a scalar scoped `COUNT(*)`. They no longer instantiate the full match history. Match validation also reads only the latest receipt, preserving correction validation and append-only writes.
- Materials assistance bypasses the full-history arrival detail reader. Its internal projection fetches at most the most recent **100** match payloads in SQL, then restores chronological order within that bounded window. The latest effective receipt is therefore included even after more than 100 corrections. Original observation/source evidence remains visible. Older receipt-reference history is explicitly unknown in this analysis.
- The existing item `evidence_truncated` and result `truncated` fields become true only when this history exceeds 100 entries; item and result `unknowns` disclose omitted evidence. The exactly-100 boundary remains untruncated. The existing general result truncation message now describes both object-count and per-item evidence limits.
- Public DTO signatures and routes are unchanged. `Arrival.matches`, full arrival detail relations, and existing audit-detail history behavior remain unchanged; no schema migration, frontend, dependency, source scope, inventory, IQC, reservation, quality or external-source mutation was added.

### Review-fix RED/GREEN commands and results

All commands used the worktree and environment prefix documented above:

1. RED before implementation: `tests/workflow/test_authority_assistance.py::test_material_assistance_bounds_arrival_history_without_losing_current_match -q` -> **1 failed in 1.36s**. The real HTTP test recorded 103 match facts through commands; materials assistance returned **103 related targets**, expected 100. The test also checks a distinct newest receipt, original observation, complete history, scoped SQL limits, truncation/unknowns, and exact immutable accounting/application-table snapshots. A subsequent first GREEN attempt exposed a fixture assertion comparing equivalent `+00:00` and `Z` timestamp serialization; expected source comparison was corrected to the original API value.
2. Focused GREEN: `tests/workflow/test_authority_assistance.py tests/workflow/test_arrivals.py -q` -> **17 passed in 6.31s**. Added exactly-100 nontruncation coverage within the regression. Real SQLite trace assertions reject unbounded arrival-history SELECTs during both list-summary and assistance HTTP reads, preventing a load-all-then-slice implementation from satisfying the test.
3. Focused regression GREEN: `tests/workflow/test_authority_assistance.py tests/workflow/test_arrivals.py tests/workflow/test_a1_extensions.py tests/workflow/test_a1_security.py tests/workflow/test_supply.py tests/workflow/test_source_manifest.py tests/workflow/test_source_history_binding.py tests/workflow/test_source_identity_upgrade.py tests/workflow/test_d3_authorization.py tests/workflow/test_action_capabilities.py tests/workflow/test_final_grants.py -q` -> **106 passed in 31.20s**.
4. `git diff --check -- src/manufacturing_platform/workflow/arrival.py src/manufacturing_platform/workflow/assistance.py tests/workflow/test_authority_assistance.py .superpowers/sdd/oem-capabilities/task-3-report.md` -> clean. Historical tracked `.superpowers/sdd/task-1-report.md` remains unchanged. Only the two implementation files, HTTP regression file and this report belong to the fix commit.

No remaining focused failures or blocking concerns. The full-history detail endpoint deliberately retains its existing semantics; the bound applies to assistance projections and summary reads. Parent owns final integrated full-suite verification; no additional broad full suite was run for this fix.
