# OEM 发布兼容性保护 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** 防止schema21后将旧schema17工作流错误报告为已恢复，并完成已授权的制造功能发布。

**Architecture:** 发布工具内实现只读兼容性探测与明确恢复状态；不降级或复制数据库。复用现有锁、固定镜像、不可变源码和候选验收。

**Tech Stack:** Python >=3.11、SQLite、现有Docker/Compose发布工具；不新增依赖。

## Global Constraints

- 不修改生产业务源码、旧发布不可变目录、数据集配置、员工会话、Nginx或其他服务。
- 不重置数据库、不还原备份覆盖现库、不修改schema_version来绕过旧代码校验、不删除DB/WAL。
- 仅已证明兼容的旧运行态允许回退；未知和不兼容状态保留部署锁与证据，要求前向修复。
- 探测包含WAL；只读SQLite，不使用immutable=1或可迁移业务Store。
- 发布从已审查并归并的MF main与已在线的PF提交构建，不带用户未提交材料或无关PF主线变更。

## Task 1: 发布兼容性探测与真实回退就绪检查

**Files:** modify `deploy/release.py`, focused `deploy/tests/test_workflow_storage.py` or new `deploy/tests/test_workflow_rollback.py`, `docs/runbooks/workflow-release.md`; `deploy/candidate_fixture.py` and focused fixture tests for direct OEM candidate evidence; `tests/workflow/test_oem_capabilities_flow.py` only to select the validated mounted runtime source when explicitly configured.

**Interfaces:** existing `cutover(e)`, `READINESS_CODE`, `ops.Locks`, `ops.inspect/run/write`, `previous_source(e)`, exact `workflow_configuration(e)`.

- [ ] Write failing tests before implementation: real sqlite probe permits17/refuses21 with WAL and dataset exact; no mutation; sequence and failure states cannot publish restored:true without workflow readiness.
- [ ] Implement a bounded stdlib-only probe constant/helper in existing release module, using pinned previous source schema declaration and approved workflow path/dataset. Execute it independently with pinned image, UID10001, network none and read-only mounts after stopping the verified target on rollback. Reject unexpected runtime ownership or drift; recover the same stopped container on refusal without old Compose. Cover absent/unconfigured workflow behavior separately.
- [ ] Set lock retention before uncertain recovery; persist explicit refusal/recovery results. Run old runtime READINESS_CODE before a successful rollback receipt and clear retention only on full success. Fail closed on probe/readiness/receipt errors. Surface forward-only policy in future maintenance.
- [ ] Update runbook with actual forward migration and recovery contract. Keep source/schema validation strict; no broad refactor or production call in tests.
- [ ] Private fixture exports the committed OEM recipe script dependencies. After the unchanged original36 gate, invoke the existing pure-Python socket OEM cross-project acceptance function in its own evidence subdirectory, using the configured `/opt/manufacturing/src` runtime. Record its result separately from the36-case registry; do not install pytest, weaken assertions, add a fake scenario or put private test assets into the production package.
- [ ] Run targeted new tests and current deployment regression. Commands use `/Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest deploy/tests/test_workflow_storage.py deploy/tests/test_release_upgrade.py deploy/tests/test_workflow_rollback.py -q` where new file exists. Run affected deploy tests needed by changed interfaces; no unrelated business suites.
- [ ] Self-review, commit exact files, write report to canonical `.superpowers/releases/manufacturing-oem-capabilities-20261030/implementation-report.md` with RED/GREEN, exact commands and unresolved limitations. Parent reviews, integrates, builds and executes production release separately.
