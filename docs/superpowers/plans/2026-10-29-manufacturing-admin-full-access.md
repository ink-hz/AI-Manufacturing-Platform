# Manufacturing administrator full access

> Execute with superpowers:subagent-driven-development. User has explicitly authorized the global administrator policy and its rollout; continue without additional permission gates.

**Goal:** Make trusted platform owners/admins automatically authorized for all current/future manufacturing projects and all business actions.

**Architecture:** One effective actor/project permission policy feeds reads, capabilities and mutations. Existing trustedActor.configuration_admin is the global privilege; no database grant seeding or new client flag. Keep ordinary member policy and business-state validation.

**Tech:** Current Python/FastAPI/Pydantic/SQLite/React contracts, existing actual-host HTTP and36scenario harness.

## Global constraints

- Scope is manufacturing only, allowner/admin identities, not a name-specific XuLiang grant.
- Centralize current/future project visibility, allregistry roles/qualifications, variant release kinds, delivery issue owner rules, object actions/tasks and exchange initiation/admission. No scattered partial overrides.
- read_only/hard_stale, authentication/CSRF, target-directory liveness, correctobject/project, unknowncommand, business guards/CAS/idempotency/freeze/receipts andactualactor audit stay effective.
- Nonadmin member/grant/revocation rules stay; old admin-denial tests must be revised under the explicit new policy while preserving their ordinary-member negative coverage. Do not change historical frozen-source expectations.
- Target responsibility membership is not fabricated. Bound real name/profile lookup stays; current privileged actor may use implicit own project membership. No new directory enumeration or invented grant rows.
- Modify only MF isolated worktree. PF source requires no change unless a concrete necessary integration is found and reviewed; report before expanding. Canonical user drafts remain untouched.
- No browser/CUA/employee session use, new dependencies, realmodel/ERP calls, reseeding, production business writes, Nginx actions or unrelated services.
- Preserve first failures. Root owns production/precise receipts, finalsameimage36/datafingerprints/backups/archives/ownedcleanup.

### Task1 — complete effective authorization and behavioral coverage

Files: authorization.py (shared effective permissions), service.py (scope, capability,execute), quality.py (release signatory policy), delivery.py (issue resolution policy and honest responsible profiles), precise API/model/registry changes onlyifneeded. Add tests/workflow/test_admin_full_access.py and meaningful regression cases; update relatedexisting policy expectations plus tests/workflow/d3/case_authorization.py (realhostE29). Update docs/manufacturing-workbench-product-design.md current behavior. Do not touch canonical untracked docs/manufacturing-platform-architecture.md.

Interfaces: Actor(user_id,display_name,read_only,configuration_admin) remains server-owned. `require_project(tx,actor,project_id)` must require a realproject. Introduce one shared effective-permissions helper returningroles/qualifications from actualgrant or the trustedglobaladmin policy. Registry allowed_actions/permits consume the same values. If constants are extracted, registry registration validation and effectiveadmin must consume the same vocabulary. Preserve service APIs and response schemas when possible.

- [ ] Read all direct project_grants actor checks, describe actor vs target checks in taskreport beforeediting.
- [ ] Add second privileged `admin` fixture identity without changing existing deterministic IDs (append new identity). Alltrustedtestfixture configs useowner/admin only; ordinaryoutsider staysnonadmin. Example API regression:

```python
def test_admin_sees_existing_and_new_projects_without_grants(workflow):
    first = workflow.create_project()
    client = workflow.client("admin")
    assert first["id"] in client.get(BASE + "/access").json()["project_ids"]
    second = workflow.create_project(name="Created later")
    assert set(client.get(BASE + "/access").json()["project_ids"]) == {first["id"], second["id"]}
    with workflow.db() as db:
        assert db.execute("SELECT COUNT(*) FROM project_grants WHERE user_id=?", (str(USERS["admin"]),)).fetchone()[0] == 0
```

- [ ] Run this/newmeaningful casesRED with `PYTHONPATH=src <PFvenv>/python -m pytest tests/workflow/test_admin_full_access.py -q` into unique .superpowers/admin-access/*red*.log. Assert actual allowedcommand audit, quality variants, deliveryother-owner resolution, adminreadonly/CAS/idempotency andnonadmin isolation. No tests that mirror constants without behavior.
- [ ] Implement centralized effective roles/qualifications and project enumeration; use it in projectdetails, objects, tasks, commands, qualitysigning and deliveryissue authorization. Make nonexistent resources fail404evenforadmins. Keep actual business blockers after permission passes; avoid broadfake success.
- [ ] Update previously intentional adminnoquality/adminnoscope assertions to the new rule, retaining real member/noqualification denial. E29 must now positively prove actual hostadmin with no projectgrant can read and execute a valid action, then retain ordinary negative scope/CSRF/revocation matrices. Unknownmissingbusinessobjects should still fail as business validation, not403permission.
- [ ] GREEN targetedtests and related workflow regressions; actual local E29 with TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform. Build currentMFwebui if fixture requires dist; root-owned node_modules symlink must never be staged/deleted by implementer. No unrelated PF fullsuites or browser.
- [ ] Update current product architecture text to new explicit adminpolicy. Selfreview allraw project_grants actor predicates for inconsistent bypasses. Commit source/tests/doc only; report alltestcounts/firstfailures/capabilityscope/remaininglimits to .superpowers/admin-access/task-report.md.

### Controller gates

- [ ] Independent task BOTH spec/quality review, fix/review then wholebranch authorization/rollout review.
- [ ] Capture actualproductionimage/source/currentreceipt/chain/all3DBmaps/workflowconfig/protectedcontainers; do not assume localPFmasterequalsruntime.
- [ ] Merge exact reviewedMFsource, build immutableactualcurrentPFsource with zerooverlay if unchanged. RetainlatestFAE/securityoverlays, currentNode runtime and fullscope36 including updatedE29.
- [ ] VerifiedthreeDB backups then guardedsource/imagecutover. Allcurrenttables/config/importmanifest andothercontainers/Nginx preserve.
- [ ] Read-only production XuLiang actualrole->globalproject/capability check; normaloutsider denies, readonly stripswrites. Verifyexactdeployedsource/staticmaps andsource-onlyrollback.
- [ ] Archive failures, candidate36, receipts andaccuratepublicrelease record; cleanup onlyownedcandidatefilesystem/worktree/link/mergedbranch, preserveuserdrafts.
