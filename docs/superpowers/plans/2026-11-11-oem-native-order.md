# OEM MES 工单关联与组件查看 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 项目中关联经过MES精确查询核实的工单，保存完整组件读取结果，让计划员直接查看物料需求和MES已提料。

**Architecture:** 原生MES服务提供固定、受审计的完整组件读取；工作流以增量表保存关联历史和类型化读取版本。网络操作在CAS写事务外完成，源配置、项目授权、重放与版本在提交前再次检查。宿主共享同一个可信MES服务，页面只通过业务API读关联及读取结果。

**Tech Stack:** Python/FastAPI/Pydantic/SQLite；React/TypeScript/Vitest；现有MES原生只读服务。

## Global Constraints

- 机器人OEM代工代料；保留既有急料、IQC、寻料、指定实收与项目授权，不能重造其事实。
- 原生MES只读，固定`order_materials`和精确`shopOrder`；不接收任意接口、URL、过滤器、原始JSON或客户端核实证据。
- MES工单核实仅建立MES身份；不能声明SAP等价、库存可用、齐套、质检放行或线边实收。
- 组件采用`SHOP_ORDER`精确校验；身份为`RSNUM`+`RSPOS`，物料`MATNR`、需求`BDMNG`、已提料`ENMNG`、单位`MEINS`、位置`LGORT`。数量保留精确十进制字符串；不把已提料当签收。
- 单次采集最多100行、20页、每页5行（配置更小则使用配置上限并受20页限制）；总数稳定且每页预期行数准确、组件不重复、所有行身份/数量/单位有效才保存；集合读取不是源事务快照。超过范围或任一页失败保留旧读取结果。
- 关联和刷新仅允许同时具备`configuration_admin`和项目`project_owner`或`engineering`权限且非只读的有效用户；项目读权限用户只能读已批准保存的关联及结果，无源查询入口。授权/重放/CAS先于私有配置与源I/O，并在提交时重查。
- 稳定源命名空间取可信配置的规范化base_url、environment、site_id、site_code，排除密码；完整配置指纹仅在服务端临时用于采集中及提交前防变化，不返回或持久化。密码轮换不改变工单身份；切换环境/站点拒绝旧关联刷新，需明确更换关联。
- 不修改用户原有dirty/untracked资料、私有配置或源业务数据；不在主线直接开发，不推送/部署。界面使用岗位业务名，错误不泄露凭据、地址或原始上游内容。
- 接口优先；前端组件自动化由开发验证，浏览器验收交用户。合成服务测试不得写成真实SAP/MES业务闭环。

---

### Task 1: 原生完整采集与持久MES工单关联业务API

**Files:** Create focused `mes_access/order_materials.py`, `workflow/native_material_{models,schema,service}.py`, `tests/workflow/test_native_materials.py`; modify `mes_access/{service,parsing}.py`, `workflow/{schema,store,commands,service,api}.py` and current schema assertions; use existing authorization/command patterns.

**Interfaces:** `build_workflow_router(..., mes_access_service=None)` and `WorkflowService(..., mes_access_service=None)`. Source service exposes trusted `collect_order_materials(shop_order, actor_id)` and a cheap configuration recheck mechanism, sharing audited query implementation. Project GET `/projects/{project_id}/work-orders/{work_order_id}/mes-materials` returns `{work_order_id, can_manage, binding, snapshot}`; unbound uses null binding/snapshot. Binding includes `id, shop_order, environment, site_code, verified_at`; snapshot includes `id, collected_at, total, components` with `component_key, material_id, required_quantity, withdrawn_quantity, unit, storage_location`. No source URL/config hash/raw rows in DTO.

Commands through existing `/projects/{id}/commands`:

```json
{"action":"mes_order.bind","operation_id":"UUID","expected_version":1,"work_order_id":"UUID","shop_order":"OEM-001","replace_binding_id":null,"reason":null}
```

```json
{"action":"mes_order.refresh","operation_id":"UUID","expected_version":2,"work_order_id":"UUID","binding_id":"UUID"}
```

Bind requires nonempty exact source rows. Existing association requires explicit current `replace_binding_id` and nonempty business reason; save supersession history. Refresh uses stored source order and namespace. Result is normal CommandResult of `work_order`, no new universal object kind. One active binding per work order; same configured source namespace+shop_order cannot bind to a second platform work order even across projects. New read versions append; failed refresh never clears prior approved snapshot.

- [ ] Write tests before implementation: exact12 rows/3pages; quantity precision; no data/wrong or missing order/duplicate component/bad amount/unit/changed total/short page/over100/second-page failure reject with zero mutations; configured max_rows respected.
- [ ] Exercise command path: admin+project role required before config/I/O, read-only/inactive/cross-project blocked, idempotent retry without source query, changed payload conflict, CAS race/permission revocation/config change after preflight fails, explicit supersession history, namespace uniqueness and restart. GET reads stored snapshot without source I/O.
- [ ] Implement source collector reusing native audit/allowed paths and config policy, freezing one config for all pages and validating unchanged current config. `order_materials` parse_float preserves numeric lexemes as strings, with profile compatibility tests. Validate finite nonnegative amounts, bounded identifiers and required units, preserve component rows separately.
- [ ] Add schema26 transactional migration from25 and freshDB; no fabricated seed. Persist binding history and typed snapshots (not raw source response); unique active indexes. Reuse central command parsing/idempotency/audit/CAS. Do not hold SQLite write/read transaction across source I/O. Recheck source configuration immediately before entering commit and actor/role/replay/version inside commit; resolve_subject checks actor activity.
- [ ] Run `/private/tmp/manufacturing-contract-py311/bin/python -m pytest tests/workflow/test_native_materials.py tests/mes_access -q`, plus relevant command/schema/API tests; record red/green and actual outputs. Commit only owned files. Write DTO/examples and tests in report for Task3.

### Task 2: 宿主共享原生服务与可信注入

**Files:** PF `backend/app/manufacturing.py`, `backend/tests/test_manufacturing_native_access.py` and existing host workflow tests.

**Interfaces:** Consume optional `mes_access_service` keyword from Task1. Build native readers once before workflow factory; return validated routers and service instances from an internal composition helper. Preserve `_native_access_router` wrapper if tests/users rely on it. Pass MES instance only when explicit supported signature; old releases mount without injection, missing/broken MES remains independent503.

- [ ] Add failing host tests proving exact same service instance used by native router and workflow, no config file/network work at mount, missing MES doesn't disable workflow/SAP, old signatures still work, and existing protected-path aliases still block injection.
- [ ] Refactor composition with current cross-source/database/sidecar/production-tools path guards unchanged, inspect explicit keyword capability, no HTTP loopback and no constructor config reads. Guard a reader whose router fails validation: do not inject it.
- [ ] Run focused PF native/workflow route tests using PF `.venv/bin/python`, commit owned files only. Record tests and older-release behavior.

### Task 3: 料况页关联工单、完整组件查看与刷新

**Files:** Create `webui/src/workflow/materialControl/MesOrderMaterials.tsx` and `.test.tsx`; modify `materialControl/{api,types,MaterialControlWorkspace}.ts(x)`, needed existing test fixtures only; rebuild tracked assets through existing bundle task.

**Interfaces:** Use Task1 GET+commands exactly; add API method `mesOrderMaterials(projectId,workOrderId,signal?)`. Consume existing `page.work_orders` picker, existing guarded draft/leave/reload+command handling. No native admin/raw query endpoints on the page.

- [ ] Add failing component tests for human-readable work-order selection, business MES工单 input, unbound/read-only capability, successful bind/read/refresh, exact quantity strings and units, replacement reason, and failure retaining previous saved result.
- [ ] Embed a compact `MES工单物料` section in料况 before requirement table. Pick platform work order by title, admins with `can_manage` may associate/explicitly replace and refresh; others view saved results. Show bound MES order, test/production环境/站点、读取时间、完整组件行数。Table columns: 组件行、物料、需求、MES已提料、单位、仓储位置. No fake shortage/readiness; one concise note explains MES已提料需另核对线边实收.
- [ ] Handle auth loss/project selection/version changes/abort races without stale cross-project results; link selection/form drafts into existing dirty navigation protection. Use current project version after successful command, reset submitted fields; cancellation/discard clears discarded fields. Error gives concrete next action and leaves approved saved result visible.
- [ ] Run focused Vitest plus `npm run test:bundle` and appropriate related workflow tests. Record component/API/browser/production boundaries. Update taskbook status and verification doc after reviews; commit source and generated assets.
