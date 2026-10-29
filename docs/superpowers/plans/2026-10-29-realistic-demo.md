# Realistic Manufacturing Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Populate the online demo workbench with realistic, linked and actionable simulated manufacturing records.

**Architecture:** An explicit maintenance importer invokes existing WorkflowService commands and MockAuthorityAdapter. It uses a durable, versioned sidecar manifest, stable operation IDs, clearly labelled synthetic service actors, and scoped grants for a caller-supplied trusted existing platform owner. No application/runtime identity bypass or startup seeding.

**Tech Stack:** Python 3.11+, existing Pydantic domain commands, SQLite and standard library.

## Global Constraints

- Code only depends on the production domain package and standard library; no dependency on tests, test authentication, test clocks or copying test databases.
- Refuse dataset modes other than demo. Every fictional project, evidence and external reference must visibly identify simulation.
- Generate successful business states through existing typed domain services and stateful MockAuthorityAdapter, never SQL-insert successful outcomes or disable business gates.
- Preserve every pre-existing project, grant, business record and platform configuration. Never reset databases or restore stale snapshots over user changes.
- Stable operation UUIDs plus durable manifest provide completed-run idempotence and safe, explicit partial-run recovery; a rerun must preserve user edits.
- Caller supplies existing trusted platform-owner UUIDs. Grant only these new demo projects project_owner and ordinary business roles. No inferred inspection, disposition, quality_release or readiness_verification qualifications for real users.
- Synthetic actors and customer evidence must be clearly simulated and restricted to this offline demo import; no employee/session impersonation or authentication changes.
- No Nginx changes, unrelated container changes, real ERP calls or external messages.
- Preserve first failures and run only meaningful relevant verification. Report exact failures and unresolved limitations.

### Task 1: Idempotent realistic demo importer and portfolio

**Files:**
- Create: `scripts/seed_workflow_demo.py` (CLI, orchestration and receipts).
- Create: focused demo scenario modules under `scripts/workflow_demo/` if needed; keep responsibilities small.
- Create: `tests/workflow/test_demo_seed.py`.
- Create: `docs/demo-workflow-2026-10-29.md` (usage, stages and evidence).

**Interfaces:**
- Consume `workflow.store.WorkflowStore`, `workflow.service.WorkflowService`, strict command models/registry and `workflow.adapters.mock.MockAuthorityAdapter` from existing source.
- Produce `python scripts/seed_workflow_demo.py --workflow-db ABS --authority-db ABS --dataset-id ID --dataset-label LABEL --owner-id UUID --manifest ABS` with a machine-readable JSON receipt on stdout. Repeated `--owner-id` may support multiple explicitly selected owners.
- CLI may add a bounded `--verify-only` option to read saved manifest and confirm current data via existing service queries. Root controller owns directory verification, backups and actual production execution.

- [ ] Read service/command/model APIs and current scenario business helpers as reference only. Do not import test modules.
- [ ] Write failing tests for demo-only guard; six linked Chinese fictional projects across four lines; ordinary owner visibility/actionability; no real-user quality qualifications; independent reopen/read; completed rerun after a user edit unchanged; existing sentinel unchanged; safe partial-failure behavior.
- [ ] Run `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/test_demo_seed.py -q --disable-warnings`, retain first failure in `.superpowers/sdd/`.
- [ ] Implement importer. Source commands should read actual current version and submit stable operation IDs. Save each successful step atomically in private manifest; distinguish existing replayable intent from a new command. Complete reruns validate/check provenance and return without changing data. Fail clearly on manifest/dataset/owner mismatch or incomplete recovery conflicts.
- [ ] Create six realistic scenarios: camera shortage, data-camera in production with failed test/NCR/rework where possible, printer pending first article, OEM design/customer-owned material collaboration, partial delivery, and completed delivery with open RMA/CAPA. At least one actual end-to-end order→execution→quality→shipment→acceptance chain. Keep sensible batch quantities and enough SN/detail rows for every workspace without excessive thousands of commands.
- [ ] Use descriptive fictional materials, source documents, units, revisions, suppliers, customer identities and relative real dates. Keep ordinary production quality evidence/gates intact, and ensure rejected failures are intentional and recorded rather than hidden.
- [ ] Run focused tests, CLI on a fresh temporary demo pair and independent verify process; record actual scenario counts, domain-object coverage and timings. Check all created project grants/actors stay within the new demo namespace.
- [ ] Document CLI, safety, stage/next-action table and realistic-but-fictional limitations. Commit implementation and tests. Report exact commits, first-failure/green evidence paths and concerns to controller.

### Controller deployment and acceptance

- [ ] Independent task review of Task 1 (spec + code quality), fix and re-review all blocking findings, then whole-branch review.
- [ ] Read-only exact live image/config/data baseline and trusted active owner lookup without session extraction.
- [ ] Rehearse importer against online-equivalent package/runtime in temporary server storage, preserve sentinel and idempotence evidence.
- [ ] Integrate source to main without changing user drafts. Transfer reviewed maintenance tool separately; no service restart/code rollout unless a verified blocker requires it.
- [ ] Online SQLite backups and baseline row fingerprints. Run reviewed importer as UID 10001 into current demo pair with explicit trusted owner and private manifest.
- [ ] Independent existing-domain query/readback, integrity, preservation, completed rerun unchanged, current image/other containers/Nginx unchanged. Save concise production evidence and tell user where to start.
