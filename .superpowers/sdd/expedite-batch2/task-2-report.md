# Task 2 implementation report — issue marks and receipt urgency

Date: 2026-11-09. Worktree: `/Users/neo/.codex/worktrees/814b/AI-Manufacturing-Platform`. Branch: `codex/oem-expedite-batch2`.

## Result and scope

Implemented Task A+B against section 0, Task A and Task B of `docs/superpowers/specs/2026-11-09-oem-expedite-batch2-tasks.md` and design §3.3/§3.4. `issue.mark` writes a new immutable coordination object for each observation, including repeated and historically backfilled stages. `printed`, `picked`, `receipted`, and `posted` are observations, without progression or accounting effects. The command uses current role/OEM authorization, same-project requirement ownership, trusted authenticated actor identity/name, a generated manual SourceRef, business-clock defaults, and aware historical event times. Issue audit history uses the same event/recording times as the fact.

The existing project objects route accepts optional `requirement_id` only for `issue_mark`. Ownership is checked, then count and stable sequence pagination execute in SQL against the project/requirement index. Other kinds reject the parameter with 422.

Receipt list/detail summaries show `Expedited: open expedite on linked requirement` first when their linked requirement has an open case. A page makes one project-scoped query bounded to that page's receipt IDs; an empty page skips this query. Ordering, totals, existing IQC/read semantics, and pagination are preserved. Closed or unrelated cases do not flag the receipt.

Schema stays 24. Fresh creation and actual 23→24 migration include `ISSUE_MARK_SCHEMA`. Existing preview24 stores missing the table initialize it additively without changing version or rewriting prior rows.

## Owned files

- New `src/manufacturing_platform/workflow/issue_mark_models.py` and `issue_marks.py`.
- Updated workflow `commands.py`, `contracts.py`, `expedite_schema.py`, `schema.py`, `store.py`, `service.py`, `api.py`, and `supply.py`.
- New `tests/workflow/test_issue_marks.py`, `test_issue_mark_migration.py`, `test_receipt_expedite_flags.py`, and `fixtures/schema23.sql`.
- Explicit action inventory changes in `tests/workflow/test_a1_extensions.py` and `test_admin_full_access.py`.
- This task-specific report. Existing generic/task-1 reports remain untouched.

No frontend, generated frontend types, real adapters, L3 writes, external publication, or accounting/source semantic changes were made. Root-owned preview scripts/tests, verification script, and documentation edits are excluded from this theme commit.

## Frozen schema23 provenance

`tests/workflow/fixtures/schema23.sql` was generated from an archive of historical commit `56e2c514826da3a5662d2dccb3540490d3781e20`, whose own `SCHEMA_VERSION` is 23. The archive's `WorkflowHarness` and `WorkflowStore` created an OEM project and actual HTTP-generated requirement/commitment/receipt/IQC facts. The old factory lacks a `mode` argument, so only its `create_project` method was wrapped to pass `mode="oem"`; historical production source was unchanged. SQLite `Connection.iterdump()` froze that database's actual DDL and rows. No current schema24 database was relabeled 23.

Reproduction outline: extract `git archive 56e2c514826da3a5662d2dccb3540490d3781e20` to an isolated directory; set `PYTHONPATH` to its `src`; import its `tests/workflow/conftest.py` through the historical tests directory; instantiate `WorkflowHarness` in a fresh temporary directory; override `create_project(**fields)` to call the original with `fields | {"mode": "oem"}`; call `material_requirement()`; close the client; assert the stored version is 23; freeze `sqlite3.connect(harness.paths.domain).iterdump()`. The committed fixture contains the source hash and method in its header.

Migration tests load the frozen DDL/rows directly, assert the original stored version is 23 and expedite/issue tables are absent, perform the migration twice, compare every original business table row byte-for-byte (including JSON, operations and audit), and check foreign keys. The separate preview24 test removes only the additive issue table from a genuine existing24 store, checks all prior rows remain unchanged after reopen, and writes an issue mark successfully.

## RED/GREEN evidence

Used the test-driven-development skill. Initial tests were written before production implementation. The first run exposed `UNSUPPORTED_ACTION` for issue.mark, unsupported issue object reads, and the absent receipt urgency annotation. The spoofed-name test construction was corrected to send an actual untrusted JSON field, rather than changing the authenticated test identity.

The two dedicated migration tests then failed with `no such table: issue_marks` for the actual archived23 upgrade and existing preview24 reopen. After the core implementation, the first focused suite passed 32 tests. Added the frozen-business-clock boundary test: it failed because audit history still used wall time, despite the fact using the business clock. Extending the existing fact audit-time hook to issue.mark made both timestamps agree. The final new-feature files passed 16 tests, including unchanged snapshots, idempotent replay/conflicting replay, restart, all four actual roles (project owner exercised without global administrator status), invalid stage/time/spoofed metadata, and no accounting changes.

The first broader run had 161 passes and one existing Task 0 fixture failure: receipt lookup without a commitment constraint sometimes selected the other requirement's receipt. The original Task 1 implementer fixed that fixture scope in commit `58e3f6c`, without loosening business assertions. Task 2 did not edit that file.

Final focused verification command:

```sh
PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q tests/workflow/test_issue_marks.py tests/workflow/test_issue_mark_migration.py tests/workflow/test_receipt_expedite_flags.py tests/workflow/test_expedites.py tests/workflow/test_expedite_tasks.py tests/workflow/test_material_handoffs.py tests/workflow/test_a1_extensions.py tests/workflow/test_admin_full_access.py tests/workflow/test_authority_assistance.py tests/workflow/integrations/test_profile_migration.py tests/workflow/integrations/test_core_compatibility.py tests/workflow/integrations/test_operation_boundary.py tests/workflow/test_bounded_queries_history.py tests/workflow/test_global_ledgers.py tests/workflow/test_supply.py tests/workflow/test_business_clock.py tests/workflow/test_contracts.py
```

Final result: **231 passed in 46.29s**, zero failures. The focused command completed with exit code 0. `git diff --check` passed before final verification.

## Review and limits

The implementation was manually checked against the task requirements and diff. Parent review requested; no subagents were spawned per task instruction. The parent performs the combined full backend suite and real socket HTTP walkthrough after A–D integration. The parent separately reported that its real TCP preview walkthrough passed the A+B steps (receipt flags, issue writes/accounting snapshots, filtered pagination, close cleanup), with evidence under `.superpowers/sdd/expedite-batch2/http-after-ab`; it then stopped at the not-yet-implemented mes.shortage command. This report does not claim the combined full suite or complete A–E walkthrough is already complete. No unresolved Task A+B design concerns identified.
