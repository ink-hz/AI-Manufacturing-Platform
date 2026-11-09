# Task 3 report — mock MES shortage (C)

Status: implemented and focused verification passed. Base: `30751fb`, branch `codex/oem-expedite-batch2`.

## Scope and behavior

- Added closed typed `MesShortage` / `MesShortageFact` models carrying `requirement_id`, `reason`, and `impact`, included in `OperationPayload` / `FactPayload`.
- Registered `mes.shortage` as a MES operation producing `mes.shortage` with the `expedite.open` policy; explicitly pinned its policy and the expanded existing `mes->wms` edge in contract tests.
- MES source preparation uses the existing `CoreSystem.prepare` fact construction and immutable source commit shell. MES transition admits shortage without quantity effects. Shared `validate_open_case` runs before source commit and again before platform writes, enforcing OEM applicability, requirement ownership, and the one-open-case constraint.
- The platform projector translates a shortage to the existing strict `OpenExpedite` business command and shared lifecycle. Trusted internal `source` / deterministic `object_id` arguments preserve the actual MES source; client commands still forbid a source field. Details and summaries expose `mes/mock`, including the summary title.
- Existing source rejection behavior is preserved: domain 422/409/404 failures become immutable rejected source receipts with no facts/outbox effects. A source accepted before a later business conflict remains accepted; platform application rejects without a new projection or replacing the existing case.
- Shortage travels on the existing MES-to-WMS edge. Existing WMS consume fallthrough intentionally creates only the durable inbox receipt; it emits no owned physical/accounting fact.
- Existing projection caching handles identical source-key replay before invoking the business write. Replaying an original fact after close or restart returns the original projection and cannot reopen the case.

## Changed files

- `src/manufacturing_platform/workflow/expedite.py`
- `src/manufacturing_platform/workflow/integrations/catalog.py`
- `src/manufacturing_platform/workflow/integrations/contracts.py`
- `src/manufacturing_platform/workflow/integrations/core_mes.py`
- `src/manufacturing_platform/workflow/integrations/core_models.py`
- `src/manufacturing_platform/workflow/integrations/core_projections.py`
- `src/manufacturing_platform/workflow/integrations/operations.py`
- `tests/workflow/integrations/test_contracts.py`
- `tests/workflow/integrations/test_mes_shortage.py`
- This task-specific report.

No schema/version changes, generated frontend types, real adapters, documentation changes, preview/walkthrough script edits, or deployments were made by this task.

## Tests and evidence

All commands ran in `/Users/neo/.codex/worktrees/814b/AI-Manufacturing-Platform`.

RED (before production changes):

```sh
PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q tests/workflow/integrations/test_mes_shortage.py -x
```

Result: **1 failed in 0.50s**. The real source command failed because `mes.shortage` was absent from the closed operation discriminator (`union_tag_invalid`), establishing the missing feature before implementation.

Final focused GREEN:

```sh
PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q tests/workflow/integrations/test_mes_shortage.py tests/workflow/integrations/test_contracts.py tests/workflow/test_expedites.py
```

Result: **145 passed in 6.05s**, exit 0.

Integration compatibility GREEN:

```sh
PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q tests/workflow/integrations tests/workflow/test_expedites.py
```

Result: **343 passed in 91.81s**, exit 0. An earlier integration compatibility run, before the additional immutable observation test, passed 342 tests.

`ruff check tests/workflow/integrations/test_mes_shortage.py`: passed. Ruff fatal (`F`) checks on all nine code/test files: passed. `git diff --check`: passed.

The ten shortage tests cover actual source operation preparation/commit, causal delivery and durable WMS acknowledgment before platform projection, open-case source and evidence linkage, identical delivery replay, unchanged original projection on repeated source keys, shared progress/close lifecycle, close/restart replay, a distinct source operation conflicting with an existing source-backed case, immutable source rejection replay, admission changes after source commit (OEM/ownership/open conflict), role removal, actual inactive grant revocation, read-only actors, HTTP rejection of manual source spoofing, and immutable source-observation tampering. Accounting snapshots include workflow quantity tables, every legacy authority table backed by real preexisting receipt/IQC inventory, WMS/SAP physical/accounting facts, WMS physical balance, and SAP accounting balance before/after each relevant phase.

## Review and boundaries

Manually inspected the diff against Task C and the existing source receipt/projection cache conventions. No subagents were spawned. Root owns full-suite verification and the final real socket HTTP evidence; root separately reported an exit-0 TCP walkthrough through shortage/WMS acknowledgment, mes/mock case opening, two integration pull replays, and process restart in `.superpowers/sdd/expedite-batch2/e2e-final2`, with its final post-commit rerun pending.

No unresolved Task C concern identified. Source receipt acceptance, causal inbox acceptance, business projection, and SAP posting remain separate evidence types; shortage produces coordination urgency only.
