# Task 1 report — OEM material handoff backend

Status: DONE
Base: `40271fd`
Worktree: `/Users/neo/.codex/worktrees/a065/AI-Manufacturing-Platform`
Commit: `15b51d4417479b175f8e6ffeea7836f4e0a0b0b4`

## Delivered behavior

Implemented the four registered actions `material_handoff.record`, `.receive`, `.resolve`, `.cancel` and the `material_handoff` object kind. Creation is OEM-only and requires warehouse/supply/production authorization. Receipt requires the exact designated receiver and a current warehouse/supply/production/project_owner role; administrators cannot sign for another identity. Sender or current project_owner/configuration_admin can resolve/cancel, still subject to live role and read-only policy.

Authorization runs before operation replay. State validation runs inside handlers after replay, so a canonical replay survives subsequent state progression. Creation extends the existing bounded member-profile path: policy/replay/CAS checks precede trusted host I/O, I/O occurs outside workflow transactions, live membership/receiver roles are rechecked in the write transaction, and authorization/replay/CAS retain precedence over a competing profile-service failure. No client-provided display names or source evidence are accepted.

Receipt discrepancies (short, over, zero, or location deviation) require a nonblank note and become `disputed`. Original facts are retained when resolving/cancelling. Business time defaults to the trusted business clock, forbids future/backwards receipt times, and is preserved in the generated manual source and audit. Same-lot splits remain distinct records. Pending summary locations explicitly describe intended, unconfirmed destinations.

Only the new handoff table, existing project version, operation receipt, and audit are written. Stock, receipt, IQC, reservation, consumption, ownership-bearing material-lot rows, existing engineering `handoffs`, source correction/confirmation rows, and all authority tables are unchanged by every tested lifecycle path.

## Interfaces and DTO

Existing routes are reused:

- `POST /projects/{project_id}/commands` with the four typed actions.
- `GET /projects/{project_id}/objects/material_handoff` and `.../{id}`.
- `GET /objects/material_handoff` for the global ledger.
- Existing project/global tasks; pending belongs to receiver and disputed belongs to sender, category `business`.
- Existing `GET /projects/{project_id}/members` continues to provide trusted `display_name`; no new directory endpoint.

Commands:

- `RecordMaterialHandoff`: `material_lot_id`, optional `work_order_id`, `quantity`, `unit`, `from_location`, `to_location`, `receiver_id`, optional `occurred_at`, `note`.
- `ReceiveMaterialHandoff`: `handoff_id`, `received_quantity`, `received_location`, optional `occurred_at`, `note`.
- `ResolveMaterialHandoff`: `handoff_id`, `resolution`.
- `CancelMaterialHandoff`: `handoff_id`, `reason`.

`MaterialHandoff` provides `id`, `kind`, `state`, `material_lot_id`, nullable `work_order_id`, service-generated `handoff_number`, `quantity`, `unit`, `from_location`, `to_location`, `sender_id`, `sender_name`, `receiver_id`, `receiver_name`, `occurred_at`, `recorded_at`, `note`, `source`, nullable `receipt`, `resolution`, `cancellation`. The generated manual source's external identity is the handoff object ID.

`receipt` provides `received_quantity`, `received_location`, `note`, `actor_id`, trusted `actor_name`, `occurred_at`, `recorded_at`. Resolution has `resolution`, actor ID/name, recorded time; cancellation has `reason`, actor ID/name, recorded time. Creation snapshots use trusted directory profiles. If a receiver name is unavailable, `receiver_name` retains the real receiver UUID string. Trusted Actor display name is used as the sender fallback and for receipt/resolution/cancellation actors; this can differ in capitalization from the directory snapshot.

`next_actions` and capability DTOs filter by state, current role, read-only status, OEM applicability, and party identity. Project-wide receive capability also requires a designated pending record. SQL task selection filters current authorization before its existing 51-row bound; normal task limits/truncation are preserved. Object pagination is SQL-scoped and ordered before projection. Detail history uses the existing bounded audit reader.

## Files

New:

- `src/manufacturing_platform/workflow/material_handoff_models.py`: typed commands and read facts.
- `src/manufacturing_platform/workflow/material_handoff_schema.py`: additive schema22 table/index definitions.
- `src/manufacturing_platform/workflow/material_handoffs.py`: authorization and transitions only.
- `src/manufacturing_platform/workflow/material_handoff_reader.py`: scoped projections and object registry composition.
- `tests/workflow/test_material_handoffs.py`: 35 real HTTP/SQL/runtime tests.
- `tests/workflow/fixtures/schema21.sql`: frozen actual schema21 boundary exported from base before implementation, so migration tests do not merely relabel a schema22 database.

Modified:

- `commands.py`, `contracts.py`: four action literals and object kind.
- `schema.py`, `store.py`: fresh schema22 and transactional 21→22 migration.
- `service.py`: trusted profile orchestration, party-aware capabilities, bounded responsibility tasks, handoff business audit timestamps; legacy action audit invocation shape preserved.
- `tests/workflow/test_a1_extensions.py`, `test_admin_full_access.py`, `test_authority_assistance.py`: exact registry/schema/capability assertions reflecting the real additions.

No frontend source or unrelated user documents were changed or staged. The existing frontend build was run solely to supply ignored `webui/dist` artifacts required by restart/PF-host tests.

## RED evidence

Command:

```sh
PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform python3.11 -m pytest -q tests/workflow/test_material_handoffs.py
```

Observed before production code:

```text
15 failed, 11 passed in 4.02s
AssertionError: {"code":"UNSUPPORTED_ACTION","message":"Unsupported action",...}
```

The 11 passing cases were invalid-input cases already rejected by the unsupported-action boundary. All valid lifecycle/non-accounting/replay/migration cases failed for missing functionality. Raw local log: `/tmp/task1-red.log`.

An additional executable test exposed broad project-level receive capability after the first implementation; its RED was `material_handoff.receive` incorrectly present for admin. This was corrected using a bounded designated-pending query. Test harness assumptions were also corrected to trigger lazy migration through the real API, and to distinguish the list's paginated query from scoped per-ID capability reads.

## GREEN and regression evidence

Focused:

```sh
PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform python3.11 -m pytest -q tests/workflow/test_material_handoffs.py
```

```text
35 passed in 6.39s
```

Task-specified regression, with the existing sibling platform interpreter that contains the PF host dependencies:

```sh
PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q tests/workflow/test_material_handoffs.py tests/workflow/test_arrivals.py tests/workflow/test_bounded_queries_history.py tests/workflow/test_admin_full_access.py tests/workflow/test_action_capabilities.py tests/workflow/test_restart.py
```

```text
61 passed in 17.41s
```

Additional exact registry/schema regression:

```sh
PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform python3.11 -m pytest -q tests/workflow/test_a1_extensions.py tests/workflow/test_authority_assistance.py
```

```text
23 passed in 5.19s
```

`git diff --check`: clean.

Before the final regression, the task command using plain Homebrew `python3.11` showed `59 passed, 2 failed`: restart/PF-host first lacked `webui/dist`; after `npm run build` (successful), it exposed absent `cryptography` in that interpreter. Private PF stderr established the exact missing dependency. Parent supplied the existing platform virtualenv; the complete required regression then passed without changing dependencies. An extra legacy atomic-audit regression initially found that unconditional new keyword arguments broke its existing `*args` wrapper; only handoff actions now pass the new time keywords, and the existing atomic rollback test passes unchanged.

## Self-review and concerns

- Confirmed every new relational lookup uses both project and object identity in SQL.
- Confirmed party authorization precedes replay; transition checks follow replay; revocation/read-only continue to reject old receipts.
- Confirmed trusted host lookup is bounded to two identities and remains outside transactions using a real competing HTTP commit test; competing canonical replay precedes profile error, while actor revocation still rejects it.
- Confirmed actual receipt facts cannot be replaced or cancelled after receipt; concurrent distinct receipt operations commit exactly one receipt.
- Confirmed same-batch splits remain independent, pending destination is never described as actual arrival, and all short/over/zero/location discrepancies require explanation.
- Confirmed project/global SQL list pagination and SQL task project/responsibility/limit boundaries by statement capture, including task truncation and role revocation.
- Confirmed frozen schema21 upgrade preserves existing rows and engineering handoffs and adds schema22 support; restart reads persisted facts/tasks.
- Confirmed there is no stock balance inference, inventory write, authority write, deployment, or real WMS/MES/ERP/PDA integration claim.
- No unresolved implementation concerns. Full repository test suite was not requested or run; the required targeted regression and changed exact-registry/schema tests passed. PF-host tests require the sibling virtualenv plus built frontend assets, as recorded above.

## Independent review fix — trusted blank actor names

Review: `.superpowers/sdd/task-1-review.md`, one Important finding. Verified that `Actor.display_name` permits empty/whitespace strings while handoff sender/lifecycle DTO fields use nonempty `Name`; a successful command could therefore persist facts that detail, list, and task readers reject.

Added eight real HTTP regressions with the trusted authentication callback supplying `""` or `" \t "`, covering creation with the directory unavailable, receipt, discrepancy resolution and cancellation. Assertions cover retained actor UUIDs, valid persisted names, detail reads, project/global list reads, and all applicable receiver/sender tasks.

RED command:

```sh
PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q tests/workflow/test_material_handoffs.py -k blank_trusted_actor_names
```

Observed before the fix:

```text
8 failed, 35 deselected in 1.76s
AssertionError: {"code":"PROTOCOL_DENIED",...}
assert 422 == 200
```

All eight commands succeeded first, then their committed detail projections failed. Local raw evidence: `/tmp/task1-review-red.log`.

Minimal fix: a single `trusted_name(user_id, *names)` helper strips and selects the first usable trusted name, then falls back to the real UUID string. Creation prefers the directory snapshot, then trusted Actor display name for the sender. Receiver names and receipt/resolution/cancellation actor facts use the same fallback. Existing nonblank directory-name preference is preserved. The helper stays local to the handoff domain; shared service/authentication/schema/frontend code was not changed.

Checked upstream bounds: `contracts.Actor.display_name` is capped at 200, and `delivery_models.MemberProfile.display_name` is capped at 200 and requires a non-whitespace character. These match handoff `Name`'s 200-character maximum. No truncation policy was introduced.

GREEN command:

```sh
PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q tests/workflow/test_material_handoffs.py
```

```text
43 passed in 9.30s
```

`git diff --check`: clean. The complete handoff suite covers the locally shared fallback and all affected write/read paths; no unrelated shared code changed, so the earlier passing broader targeted regression was not repeated. Self-review checked that only service-authenticated names/IDs and already validated directory profiles enter the helper, UUID fallback preserves attribution, and replay/state/permission/accounting behavior is unchanged. No unresolved concerns.

Fix commit: `10bc873` (`fix(workflow): retain handoff identities for blank trusted names`).
