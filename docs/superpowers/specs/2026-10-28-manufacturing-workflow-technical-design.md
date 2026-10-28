# 制造全流程技术设计与跨任务契约

2026-10-28。依据已获用户“开始吧”授权的[产品范围](2026-10-28-manufacturing-full-workflow-design.md)及[36 组验收矩阵](../../testing/manufacturing-full-workflow-acceptance.md)。本文是实现依据，不是通过报告。工作目录：MF `.worktrees/full-workflow`（基线 `ec41b39`），PF `.worktrees/full-workflow`（基线 `b87d88ac`）。A→B→C→D 顺序交付；每个任务有独立测试与审查。

## 1. 决策与边界

- 新建 `src/manufacturing_platform/workflow/`，不向旧项目 `body` JSON 填入整套 ERP。旧库、七个既有项目、资料包/固定修订/交接/准备、手册全文、旧管理页面全部保留。
- 新域使用显式、独立、持久化 SQLite；模拟权威系统使用第二个独立 SQLite。生产域、演示域、每轮测试各有不同路径及 dataset_id；配置拒绝这两者与 legacy 数据库相同或解析到同一文件。禁止内存库、启动自动种子、删除生产数据的 reset API。
- 新建全流程项目自己的轻量项目范围、S1—S9 协作状态与业务规则。历史项目不自动启用；可选 `legacy_project_id` 仅供有原旧域访问资格的人关联，绝不以新域成员资格读取原项目。暂不做双写迁移。
- 平台只建立协作请求、关联、证据与授权；ERP/MRP/APS/PLM/MES/WMS/QMS 的库存、工单、排程和过账由明确的适配器维护。模拟系统必须真正在自己的库中处理输入、余额、版本及幂等，不能从平台期望结果直接返回 success。
- API 为主验收；前端组件为真实交互验收；浏览器与真实业务角色实操留给用户。不得把 mock、真实系统、用户视觉、生产验收混为一种通过。

## 2. 主机/库协议，不能从旧 router 穿透

旧 `build_router(... authorize=authorize_manufacturing)` 与 `PrivateRoute` 保持原签名和管理角色规则。新库额外导出：

```python
WORKFLOW_API_VERSION = 1

def build_workflow_router(*, database_path: str, authority_database_path: str,
    assets_dir: str, authenticate, resolve_subject, release: str, dataset: dict): ...
# authenticate(request, write=False) -> Awaitable[dict] | dict
# trusted result: {user_id: UUID string, display_name: str,
#                  read_only: bool, configuration_admin: bool}
# dataset: {id: str, mode: 'production'|'demo'|'test', label: str}
```

PF `authorize_workflow_identity` 只从 `request.state.auth_context: AuthContext` 读取 internal_user_id；无 context 返回 401；hard_stale 写返回 503；read_only 包含 hard_stale_read_only 或 Role.MANAGEMENT_VIEWER，即使观察者有业务 grant 仍禁止写入。不读旧 Session、请求头身份、body role、前端角色选项。configuration_admin 仅由平台 owner/admin 派生，**不产生质量/生产/客户签批资格**。每条业务路由再查询新域实时项目成员与动作授权；不能缓存前次权限。

PF loader 将新 router 加在旧 router（含 catchall）之前。只有 `WORKFLOW_API_VERSION == 1` 且三个显式工作流配置有效时才调用新导出；旧模块不接受新 kwargs，继续原调用。新工作流配置缺失/不兼容只使新域 unavailable，不能禁用旧域。新配置：`PLATFORM_MANUFACTURING_WORKFLOW_DATABASE_PATH`、`PLATFORM_MANUFACTURING_AUTHORITY_DATABASE_PATH`、`PLATFORM_MANUFACTURING_DATASET_ID`、`PLATFORM_MANUFACTURING_DATASET_MODE`（production/demo/test）、`PLATFORM_MANUFACTURING_DATASET_LABEL`。production 禁止加载 mock adapter。对未连接的 production 请求显示未接入，不捏造回执。

所有新 endpoint 都位于 `/api/v1/manufacturing/workflow`，**精确 method/template 白名单**见下表。PF `manufacturing_paths.py` 导出 `WORKFLOW_ROUTES` 和完整路径 `WORKFLOW_AUTH_ROUTES`，central authorization 对该集合和精确 shell `/manufacturing`、`/manufacturing/` 允许可信登录身份进入；由域内授权决定业务范围。原 MANUFACTURING_AUTH_ROUTES 去除 shell 后继续 owner/admin，禁止改成 prefix 授权。PF routes_auth.py 当前 manufacturing decorators 与 ai_engineering_shell 共用管理角色 guard，必须拆成独立 manufacturing shell 函数，仅要求可信登录；organization/ai-engineering 保留原管理 guard。未知路径/方法走认证后的拒绝，不落入 SPA。新 unavailable router 也枚举同一集合。未配置/旧库不支持 workflow 的 /access 返回200的 legacy-only Bootstrap；其余新业务路由认证后503。显式配置但数据库/资源损坏时 /access 返回503，不静默回退。签名、Origin、CSRF、no-store 和 hard-stale 中间件均继续作用。

| Method | 相对 workflow 路径 | 结果/授权 |
| --- | --- | --- |
| GET | /access | 登录后可探测；不泄漏对象。返回下述 Bootstrap |
| GET | /assets/{asset_name} | 仅确切 manufacturing.js/css，有工作流入口权限或 legacy 管理资格 |
| GET | /handbook | 完整既有手册，入口权限；复用原可信资产定位和 Markdown 内容 |
| GET | /dashboard | 所有实时授权项目聚合，支持 project_id；不含未授权对象计数 |
| GET | /projects | 授权范围项目列表 |
| POST | /projects | ProjectCreate，configuration_admin 或显式 creator 资格 |
| GET | /projects/{project_id} | ProjectDetail，项目可读 |
| GET | /projects/{project_id}/members | 项目可读，配置管理者看到授权管理动作 |
| PUT | /projects/{project_id}/members/{user_id} | GrantChange，仅 configuration_admin；UUID 来自已认证账号目录，服务端核验或可信部署清单 |
| GET | /projects/{project_id}/objects/{kind} | 严格枚举 kind 的分页类型化列表 |
| GET | /projects/{project_id}/objects/{kind}/{object_id} | 明确类型的详情、关联、来源、历史、可行动作 |
| POST | /projects/{project_id}/commands | WorkflowCommand discriminated union；项目 CAS + 细分业务权限 |
| GET | /projects/{project_id}/trace | 查询 sn 或 material_lot_id，最多 500 节点，范围内正反向 |
| GET | /projects/{project_id}/exchanges | 含异常、请求/回执分阶段；项目可读 |

Bootstrap = `{allowed,available,workflow_available,can_edit,release,protocol:1,legacy_access,workflow_access,configuration_admin,dataset:{id,mode,label}|null,user:{id,display_name},project_ids:string[]}`。有意未配置或旧库无导出时 workflow_available=false/workflow_access=false/dataset=null/project_ids=[]；管理员 legacy_access=true/allowed=true/available=true，普通成员 allowed=false；host改用旧资产地址。配置成功时 workflow_available=true；真实存储故障保持503。`allowed` 为 legacy_access 或 workflow_access；workflow_access 为有一个有效 grant 或 configuration_admin；project_ids 不含不可读项目。无 grant 的普通成员得到 allowed:false，而不是旧项目泄漏。assets 使用 `/workflow/assets`，避免普通成员触碰旧 admin-only `/assets`；手册同理。PF `manufacturingAccess` 优先新 probe；仅 404（旧 release）才回退旧 `/access`，不吞掉 401/403/503。PF mount 增加可选 `bootstrap`；旧调用不传则进入旧初始化。新 MF App 在 bootstrap.protocol=1 时按 flags 装载新页；只有 legacy_access=true 时才能读取旧 catalog/dashboard/projects/tasks。新域首屏不 Promise.all 请求旧接口。PF sidebar 基于 probe 的 allowed/available，去掉额外 manager 条件。PF routes_auth.py 的 CSP 显式加入同前缀 `/api/v1/manufacturing/workflow/assets/` 源；保持受限脚本源。

安全 bootstrap：新生产域空库只能管理员创建项目、授予配置，不能给自己自动授予质量资格。GrantChange 写明确 user_id、role、qualification、scope 及 evidence；管理员配置资格是可审计配置行为，之后签批仍检验实际 grant。管理员可指定任一真实内部 UUID，PF 增加可信 subject 验证回调（通过现有 control-plane 用户 repository 查询 platform_control.internal_users 中活跃用户）；如现有查询接口不可复用，提供只读精确 `resolve_active_subject(user_id:UUID)->bool`，不创建第二套登录。`build_workflow_router(...,resolve_subject=callback)` 参数明确注入该解析器，签名 `resolve_subject(user_id:UUID)->bool`；MF 独立测试通过 fixture 提供解析器，生产不得跳过校验。PF `build_manufacturing_router(*,resolve_workflow_subject=None)` 接收 main.py 在配置可信 control repository 后注入的解析器；显式启用 workflow 却缺失解析器时新域失败关闭，旧域不受影响。此为 main.py 窄接线变更，不新建全局用户缓存。示范身份只在测试宿主 fixture/本地测试进程存在；生产页面没有角色切换，没有模拟客户登录生产会话。

## 3. 项目、动作和持久化公共契约

`workflow/contracts.py`：Pydantic v2 extra='forbid'，严格整数/布尔，长度上限，UUID、带时区 ISO8601、日期校验。Quantity 在 JSON 为规范十进制字符串（例如 "100"、"1.250"），在 Python 为 Decimal，SQLite 存固定 scale 的整数 q_atoms；不以 float 运算。Unit 定义 `{code,scale}`，scale 0..6；超过精度拒绝，不四舍五入。产品 SN 数量必须整数，所有物料与成品匹配单位；本轮没有隐式换算，明确有版本的换算记录后才允许转换。

```python
class CommandBase(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_id: UUID
    expected_version: Annotated[int, Field(strict=True, ge=1)]  # project CAS

class WorkflowCommand(CommandBase):
    action: WorkflowAction  # finite Literal names in commands.py

class AllocateOrder(WorkflowCommand):
    action: Literal['order.allocate']
    order_line_id: UUID
    work_order_id: UUID
    quantity: Quantity
    unit: str

# Domain DTOs extend WorkflowCommand, overriding action with one Literal.
# CommandRegistry.register(Model, roles=set(...), qualifications=set(...), handler=dispatch)
# compiles Annotated[Union[registered models], Field(discriminator='action')].
# parse(payload) returns the concrete strict DTO; unregistered actions remain unsupported.
# Registration is trusted Python composition at startup, never exposed over HTTP.

class CommandResult(BaseModel):
    operation_id: UUID
    project_id: UUID
    project_version: int
    object_type: str
    object_id: UUID
    exchange_id: UUID | None = None
    replayed: bool = False
```

具体公共函数（所有任务严格使用这些名称）：

```python
class WorkflowService:
    def execute(self, actor: Actor, project_id: UUID, command: WorkflowCommand) -> CommandResult: ...
    def create_project(self, actor: Actor, value: ProjectCreate) -> ProjectDetail: ...
    def detail(self, actor: Actor, project_id: UUID) -> ProjectDetail: ...
    def objects(self, actor: Actor, project_id: UUID, kind: ObjectKind, *, limit:int=50, offset:int=0) -> ObjectPage: ...
    def object_detail(self, actor:Actor, project_id:UUID, kind:ObjectKind, object_id:UUID) -> ObjectDetail: ...
    def dashboard(self, actor:Actor, project_id:UUID|None=None) -> Dashboard: ...

class WorkflowStore:
    def transaction(self, *, write:bool=False) -> ContextManager[sqlite3.Connection]: ...

# Domains expose dispatch(tx, context:CommandContext, command:their union)->MutationResult.
# CommandContext is a frozen dataclass:
# actor:Actor, project_id:UUID, project_version:int, now:datetime (UTC),
# dataset:Dataset(id,mode:production|demo|test,label), exchange_service:None in A1.
# B2 supplies its typed exchange capability when implemented; A1 performs no external I/O.
# MutationResult(object_type:ObjectKind|Literal['project'], object_id:UUID, exchange_id:UUID|None=None).
# Central service owns result, project version increment, operation hash and audit in one transaction.
# Per-registration roles are any-of; qualifications are all-of, read live before replay and mutation.
# configuration_admin never bypasses that policy; additional business/source conditions belong to handler.
```

`Actor(user_id,display_name,read_only,configuration_admin)` 是可信后端值。`ProjectCreate(operation_id,name,line_id,product,customer_id,mode:'internal'|'oem',unit,quantity,contract,legacy_project_id=None)`；contract 是严格 `ContractPolicy(customer_approval_required,customer_release_required,acceptance_required,customer_revision,internal_revision,material_ownership_rules)`，不明值为 unknown，不能当 false。创建项目 CAS 1，创建者只有 project_owner grant（不自动质量）；configuration_admin 只创建配置不自动读其业务项目以外数据，legacy_admin 可读旧域与手册仍无新域签批。

A4 增加 `ProjectDetail.allowed_actions: list[str]`：详情和项目列表按当前 actor 的实时 active project grant、只读状态及注册动作的 any-role/all-qualification 规则派生；`CommandRegistry.permits` 同时用于执行授权和只读能力枚举，枚举不写拒绝日志。此字段只表示动作权限，不承诺来源、数量、业务前置或版本条件已满足；执行时仍重新验证。创建/重放返回的详情可为空列表，客户端随后重读项目详情取得当前权限。

前端 `WorkspaceProps={api,project,onChanged(result),onOpen({projectId,kind,id}),onDirty(key,dirty),readOnly}` 不接受角色或 actor 切换。`CommandFields` / `WorkflowCommand` 和 `DomainValue` 为当前 A 的严格联合；B/C 通过增加真实 DTO 与工作区扩展。`MountOptions.findSubjects?(query,signal)` 仅配置管理员获得，PF 复用 `listManagedUsers(signal)` 过滤 active 账号，真实显示名选择；取消/换账号即退役，无额外身份服务。

`ProjectDetail.stages` 始终是严格类型的列表，元素为 `{stage:S1..S9,status:pending|active|blocked|complete,reason?:string}`。D1 建立真实阶段事实之前返回空列表，不能预填完成状态。订单和项目的已知零数量以规范字符串 `"0"` 返回；数量字段拒绝非数字、负数、NaN、Infinity 和非规范指数表示。

权限最小矩阵：project_owner 需求/评审/承诺/履约关闭；engineering 资料/校准依据/ECO，readiness.record 另需项目范围内有效的 readiness_verification 资格（核验设备/人员依据，不声称核验者执行校准）；planner 计划/工单/分配/准备/开工请求；supply 供应与到货协同；production 执行登记、异常、制造放行；quality 严格资格 inspection+disposition+quality_release；warehouse 发运及签收登记；customer_confirmation、external_receipt 只允许经配置的来源适配器或明确人工证据登记动作，不能用 production/IT 身份冒充外部主体。所有角色可读其项目，外部客户维度按 project.customer_id 与关联 customer_id 同时检查。GrantScope = {kind:'project',project_id:UUID}，必须匹配 URL project_id，禁止 wildcard/global。GrantChange = operation_id,expected_version,scope:GrantScope,roles[],qualifications[],active,evidence；GrantView/ScopeGrantView 包含 scope,user_id,roles[],qualifications[],active；配置 revocation 递增 project.version 并审计；每次 read/write重新检查。

事务顺序：先身份/项目可见性→校验 schema→BEGIN IMMEDIATE→实时 ACL→按 dataset+actor+operation_id 查 canonical payload SHA256→相同输入返回原结果（仍需当前授权），不同内容409 IDEMPOTENCY_CONFLICT→project CAS→域规则和所有数量链接→写业务/事件/outbox/操作结果与项目 version+1→commit。跨项目不可见返回404，已知无角色403；无登录401；schema422；业务前置409 PRECONDITION_FAILED（含字段和阻断项）；CAS409 VERSION_CONFLICT（current_version）；外部未确认202 pending可由CommandResult.exchange_id查询；真实 I/O 503。失败必须没有业务成功事件；授权/协议拒绝进入独立有界安全日志，校验拒绝不创建成功操作结果。审计 append-only，不截断旧事实。

核心表（有 project_id 与 FK；跨表关联在同事务再次比对 project_id；dataset 单库单实例）：

| 模块文件 | 规范化表及关键字段 |
| --- | --- |
| store.py, schema.py | schema_version,dataset_metadata,projects(id,version,contract columns,legacy_project_id),project_grants(user_id,role,qualification,active),operations(actor_id,operation_id,payload_hash,result),audit_events(actor,action,object_id,occurred_at,recorded_at,typed_payload) |
| orders.py, order_models.py | demands(kind,quantity,unit,source),reviews(demand_id,dimension,decision,evidence),order_lines(demand_id,external_ref,quantity,original_due,current_due,status),commitment_changes(old/new quantity/due,reason,impact,disposition),allocations(order_line_id,work_order_id,q_atoms) |
| engineering.py, engineering_models.py | engineering_revisions(package_id,revision,customer_revision,internal_revision,route/test/firmware versions,hash),revision_items,handoffs(revision_id,status,received_revision,evidence),equipment(valid_until),work_orders(external_ref,quantity,revision_id,plan dates,state),readiness_checks(kind,target,evidence,valid_until),eco_changes(old/new revision,effective boundary),eco_impacts(type,object_id,disposition,evidence) |
| supply.py, supply_models.py | plans(source/input versions,cutoff),requirements(work_order_id,execution_scope,material_id,owner_id,quantity,unit),supply_commitments(original/current due,type,owner_id),receipts(source receipt,batch,quantity),iqc_results(receipt_id,accepted,rejected),material_lots(material_id,owner_id,expiry,state,unit),reservations(request_id,work_order_id,lot_id,requested,confirmed,source_version) |
| execution.py, execution_models.py | start_requests(mode:'trial'|'bulk',quantity,receipt_id),units(sn UNIQUE,work_order_id,revision_id,state),execution_events(unit_id,station,program_version,material_lot_id,quantity,source_seq,first/rework route),material_consumption(unit_id,lot_id,quantity,owner_id),interruptions(reason,started_at,resolved_at,plan_id),first_articles(work_order_id,unit_ids,inspection_id),rework_orders(unit_id,route,status),freeze_requests(scope,unit_ids/lot_ids,requested_state,receipt_id),freeze_states(object_id,source_seq,state) |
| quality.py, quality_models.py | tests(unit_id,attempt,program/limit version,measurement,unit,lower/upper,outcome),nonconformances(test_id,disposition,evidence),releases(kind,unit_id,decision,condition,authority,evidence),scrap(unit_id,reason) |
| delivery.py, delivery_models.py | shipment_requests(order_line_id,unit_ids,box_ids,exchange_id),shipment_items(unit_id UNIQUE accepted shipment,project_id,order_line_id),delivery_receipts(shipment_id,signed qty,accepted qty),acceptance_issues(owner,required,resolved),closures(kind:'fulfillment'|'quality'|'cost',source,status) |
| feedback.py, feedback_models.py | rmas(unit_id,shipment_id,reason),capas(rma_id,containment,root_cause,correction,verification,eco_id,status),ownership_reconciliations(owner_id,received,consumed,scrapped,returned,balance) |
| exchanges.py, exchange_models.py | exchanges(source,mode,business_key,direction,source object/version,request hash,occurred/collected/received/processed times,phase,error),exchange_receipts(exchange_id,stage,sequence,payload),reconciliation_differences(detail keys,expected,actual,resolved),exceptions(owner,kind,linked_object,status) |

Typed payload JSON is allowed for immutable structured audit/request/measurement snapshots, never a replacement for quantities, FKs, uniqueness, current state or source version columns. External object uniqueness is (source_system,object_type,external_number), event identity adds source event key; display names are never keys.

## 4. Domain action catalogue (stable wire names and required fields)

All commands include operation_id/expected_version; fields below are in addition to `action`. UUID links always resolve inside the project. `source` is `SourceRef(system,object_type,external_id,version:int,mode:'manual'|'file'|'mock'|'api',occurred_at,collected_at,cutoff,evidence)`; inbound api/mock source is assigned by the trusted adapter, never blindly trusted from a user body. Manual facts remain manual, cannot supply authoritative post/receipt stages. `evidence` is bounded nonempty text/reference; no automated outbound messaging.

| Task | Action | Required business fields and effect |
| --- | --- | --- |
| A2 | demand.record | kind inquiry/forecast/firm,product,quantity,unit,due_date,source,supersedes_demand_id?; preserve original commitment |
| A2 | demand.review | demand_id,dimension technical/material/capacity/commercial/quality,decision approved/rejected/unknown,evidence; independent decisions |
| A2 | order.register | demand_id,source,quantity,unit,due_date; formal ERP/manual document reference; firm+five approved reviews |
| A2 | order.change | order_line_id,new_quantity,new_due_date,cancel,reason; saves pending change and computed allocations/receipts/WIP/shipment impacts |
| A2 | order.resolve_change | change_id,dispositions[{object_type,object_id,decision,evidence}]; cannot reduce below executed/delivered quantity, must resolve remaining committed allocation through explicit authoritative cancellation |
| A2 | order.allocate | order_line_id,work_order_id,quantity,unit; sum allocations ≤ effective order and workorder quantities |
| A3 | engineering.revision | package_id,revision,customer_revision,internal_revision,items:[existing strict PackageItem],route_steps[],test_spec,firmware_version; immutable fixed snapshot, cannot patch bound revision |
| A3 | engineering.handoff | revision_id,to_system,received_revision,decision,evidence; received revision must match, incorrect receipt retained as exception |
| A3 | engineering.customer_approval | revision_id,decision,customer_id,evidence; manual registration records receiver actor and named external signatory, cannot claim api receipt |
| A3 | work_order.register | source,quantity,unit,revision_id,planned_start,planned_end,purpose trial/production,trial_quantity; formal external number unique; no forecast authorization |
| A3 | readiness.record | work_order_id,kind equipment/people,reference,evidence,valid_until,decision; version/material/customer/first_article derived from facts, not checkbox overrides |
| B1 | plan.receive | source,input_revision_ids[],input_order_versions[],requirements[] with work_order/execution_scope trial|bulk|common/material/owner/q/unit; missing/stale versions become exception, not confirmed plan |
| B1 | supply.commit | requirement_id,type purchase/customer,owner_id,quantity,unit,original_due,current_due,source; append revised promise |
| B1 | supply.receive | commitment_id,material_lot_id,quantity,unit,source; trusted WMS/ERP source or manual receipt separately labeled |
| B1 | supply.inspect | receipt_id,accepted,rejected,evidence; quality qualification, accepted+rejected ≤ receipt, immutable IQC original |
| B1 | material.define | material_id,unit,owner_id,expiry,lot_id,source; no silently granted stock, quantities from receipts |
| B2 | reservation.request | work_order_id,requirement_id,lot_id,quantity,unit; local request only, actual balance accepted by authority |
| B2 | exchange.dispatch | exchange_id; authorized initiating role, only pending or unresolved phases; persist pending then send outside main transaction |
| B2 | exchange.query | exchange_id; consult authority using same business key before retry; apply valid receipts in separate idempotent transaction |
| B2 | source.pull | system,object_type,external_id；从已配置适配器读取原始事实，不接受body中的伪造权威payload |
| B2 | source.import | object_type,rows:[严格对应领域的入站 DTO]；仅可信/显式人工来源，走同一业务验证 |
| B2 | source.import_file | object_type,format json/csv,content_base64（解码最大1MB）；解析错误不写成功，全部行验证后应用 |
| B2 | exchange.reconcile | source,object_type,source_version,details[]; compare stable detail keys AND quantities/totals, record differences |
| B3 | production.start | work_order_id,mode trial/bulk,unit_ids,quantity; bounded trial excludes first-article prerequisite; external receipt required to enter running |
| B3 | execution.record | source,work_order_id,sn,station,route_version,program_version,firmware_version,material_uses[{lot_id,quantity,unit}],result,occurred_at; unknown SN/out-of-range/incorrect route rejected |
| B3 | unit.register | work_order_id,sns[]; bounded by workorder quantity, immutable revision snapshot and globally dataset-unique SN |
| B3 | production.interrupt | work_order_id,reason,kind shortage/equipment/quality,occurred_at; creates linked owned exception |
| B3 | production.resume | interruption_id,plan_id,evidence; material/readiness and authoritative resume receipt required |
| B3 | first_article.record | work_order_id,unit_ids,test_ids; quality evidence links trial units; result derived from complete measurements, failures preserved |
| B4 | eco.open | old_revision_id,new_revision_id,effective_work_order_ids/effective_sn_ids,reason; enumerate PO/stock/WIP impacts |
| B4 | eco.disposition | eco_id,impact_id,decision use_old/rework/return/scrap,quantity,evidence; no silent snapshot rewrite |
| B4 | eco.switch | eco_id,target_work_order_id,new_revision_id,evidence; only unexecuted scope or new split WO with explicit allocation transfer; requires approvals/handoff/readiness invalidation |
| B4 | eco.close | eco_id; only after all dispositions and actual switch receipts, customer approval if required |
| C1 | test.record | source,unit_id,attempt,program_version,limit_version,measurements[{name,value,unit,lower,upper}],rework_order_id?; outcome calculated, initial test retained |
| C1 | nonconformance.open | test_id,defect,evidence; linked owned issue |
| C1 | nonconformance.disposition | nonconformance_id,decision rework/scrap/concession,route_id?,condition?,evidence; quality-qualified |
| C1 | rework.complete | rework_order_id,execution_event_ids,test_ids; independent route and matching successful retest, no overwrite |
| C1 | release.decide | kind manufacturing/quality/customer,unit_ids,decision approved/rejected/conditional,condition?,evidence,customer_id?; qualifications/source-specific; all units explicit, conditional policy validated |
| C2 | shipment.request | order_line_id,unit_ids,boxes[{box_id,unit_ids}],quantity,unit; ready qualified outputs allocated to same order, no duplicate pending or accepted SN |
| C2 | delivery.sign | shipment_id,quantity,source; authoritative accepted shipment required, does not imply acceptance |
| C2 | delivery.accept | shipment_id,quantity,source,issues[{title,owner_id,required}]; ≤signed, additive immutable records |
| C2 | delivery.resolve_issue | issue_id,evidence; owner/project_owner, no lost remaining quantity |
| C2 | closure.record | kind fulfillment/quality/cost,source,evidence; independent predicates, cost only ERP receipt/manual labeled fact |
| C2 | ownership.reconcile | owner_id,material_id,received,consumed,scrapped,returned,balance,source; compare against consumption/returns and expose differences |
| C3 | freeze.request | unit_ids,lot_ids,state frozen/unfrozen,reason; local safety pending blocks new dispatch while display distinguishes authority confirmation |
| C3 | rma.open | unit_id,shipment_id,reason,source; delivered chain preserved |
| C3 | capa.update | capa_id?,rma_id,step containment/root_cause/correction/verification,description,evidence,effective:bool?,eco_id?; ordered evidence with immutable history |
| C3 | capa.close | capa_id; successful effectiveness verification; when corrective action requires engineering change, linked ECO must be executed/closed; supplier/training/process actions use their own verified implementation evidence; failed verification remains open |
| D1 | project.stage | stage S1..S9,status,reason; collaboration hint only, cannot waive business predicates |

ObjectKind enum: demand,order_line,commitment_change,work_order,revision,plan,requirement,commitment,material_lot,reservation,unit,interruption,eco,test,nonconformance,rework,release,shipment,closure,rma,capa,exception. Domain models define typed detail unions using kind discriminator; list `ObjectPage(items:[ObjectSummary],total,limit,offset)` summaries contain id,kind,project_id,title,state,quantity?,unit?,source?,version,blocking_reasons[],next_actions[]. `ObjectDetail[V]` = summary:ObjectSummary,value:V,relations:[ObjectRelation],evidence:[ObjectEvidence],history:[ObjectHistory]. V extends strict DomainValue and declares kind:Literal of its registered ObjectKind; the registry compiles the kind-discriminated union and revalidates the concrete DTO before returning it. ObjectRelation = relation,project_id,kind,id (same-project only); ObjectEvidence = reference,source:SourceRef|None; ObjectHistory = event_id,actor_id,action,occurred_at,recorded_at,evidence[]; both timestamps require timezone-aware ISO strings/datetime values and retain their supplied offset, using the same awareness validation as SourceRef. No user-editable raw JSON. `OBJECT_REGISTRY.register(kind, Model, count=count_reader, summaries=page_reader, detail=detail_reader)` is trusted Python composition. count(tx,project_id)->int (exact nonnegative count via SQL aggregate); summaries(tx,project_id,limit,offset)->list[ObjectSummary] applies deterministic SQL ORDER BY and LIMIT/OFFSET before materializing at most limit rows; detail(tx,project_id,object_id)->ObjectDetail[Model]|None. The registry rejects oversized page results; full-table materialization followed by slicing is not a valid reader. Services verify reader scope and object identity. `Dashboard` = project_ids,project_count,counts:dict[ObjectKind,int],cards:[ObjectSummary]. Counts and cards query the same registered domain tables in a consistent authorized read transaction; object pages pass the requested limit/offset to the SQL page reader and obtain total separately from count; counts include only implemented kinds, empty registries produce counts:{} (no invented future metrics), cards are capped at 100 and each has project_id,kind,id destination. Dashboard counts every authorized project/kind with the count reader, requests summaries with only the remaining 100-card budget (offset 0), and skips all further summary reads once the budget is exhausted. List pagination retains the exact count independently of the requested page.

## 5. Physical and external invariants

Readiness is computed per workorder and mode. Shared gates: frozen engineering revision acknowledged, correct customer revision/approval if contractual, actual planned-date calibration, qualified people, accepted reservation and material ownership/unit/expiry/freeze, valid plan cutoff. Material requirements come from the authoritative plan with execution_scope trial/bulk/common and scoped quantity. Trial checks only its applicable trial/common quantities, never the whole bulk demand; the platform does not calculate a new BOM/MRP expansion. Trial mode additionally limits unit count to declared trial scope; it does **not** require first-article success. Bulk mode requires approved first article on the same revision/route/test/equipment scope. A trial's actual units/consumption count toward workorder quantity; passing them never authorizes producing quantity twice. Revision, calibration, customer requirements or material changes invalidate affected cached readiness results. Readiness UI must explain which input version changed.

Order/workorder allocation ≤ both quantities; executions ≤ accepted authorized start and declared unique SN range; accepted finished output excludes scrap and unresolved defects. Each unit belongs to one workorder and revision; shipment links it to a specific order allocation and consumes remaining eligible quantity. Order 100 / WOs60+40 / shipment60 leaves40 until second batch has signed+accepted as contract requires. Closing fulfillment requires all obligations delivered/accepted and required issues resolved; closing quality requires no open mandatory NC/RMA/CAPA; closing cost is independent. Increasing order quantity requires explicit source revision, decreasing below committed scopes requires disposition/authoritative cancellation, below delivered is rejected.

Execution correction is a new source event linked to superseded event; rejected events do not alter totals. First-pass rate counts first complete test; final good counts final valid passed units less scrap, not a sum of passes. Missing numeric results, units or versioned limits are incomplete even if source text says PASS. Tests compare supplied limits against approved test specification rather than accepting arbitrary easier client limits. Material usage edges are recorded per actual SN/lot and quantity; bidirectional trace traverses order→WO→revision→usage→tests→release→shipment→RMA without guessing from notes.

ECO never mutates existing executed snapshots. Boundary must enumerate workorders/SNs; for partially executed WO retain old scope, create new WO for remaining unexecuted quantity, transfer only remaining allocations after authoritative cancellation/creation receipts, and rerun readiness. Original WIP/stock/PO impacts and disposal evidence remain. Freeze keeps separate requested and authoritative states; pending freeze locally blocks release/shipment, an unconfirmed unfreeze cannot restore eligibility. Source sequence rejects stale freeze/unfreeze.

## 6. Stateful mock and exchange protocol

`adapters/base.py`: `AuthorityAdapter.submit(request:ExternalRequest)->ExternalReceipt`, `query(system:str,business_key:str)->ExternalReceipt|None`, `snapshot(system:str,object_type:str)->AuthoritySnapshot`. `ExternalRequest(id,system,action,business_key,source_version,project_id,typed_payload)` and discriminated typed payloads for reserve/start/resume/cancel/switch/ship/freeze/cost. `ExternalReceipt(receipt_id,business_key,request_hash,source_object_id,source_version,sequence,phase,accepted_quantity,rejected_quantity,details,occurred_at,error)`; phase received/validated/approved/accepted/posted/rejected/unknown. Local requests never directly set posted.

`adapters/mock.py` plus `adapters/mock_store.py` own inventory balances, reservation rows, workorders, shipped SNs, freeze sequences and operation hash/results. Atomic reserve uses BEGIN IMMEDIATE and checks eligible owner/unit/status/expiry plus remaining accepted quality stock; two concurrent requests for80 of100 cannot both succeed. Authority can partial-accept configured quantities; platform computes remaining shortage. No distributed transaction: platform outbox commit→external transaction→receipt apply transaction. Timeout after external commit leaves local unknown; query obtains same receipt without another reservation/start/shipment. Source version and details are validated, late older receipts audited but not applied. File import parses into exactly the same typed input/service; parse failure writes no business success.

Fault configuration exists only in isolated fixture/config file, never arbitrary production API body: timeout_after_commit, reject, partial_quantity, duplicate, stale_sequence, wrong_unit, stale_cutoff, changed_detail_same_total. Customer/supplier mock records carry named external actor and explicit mock source, not a logged-in production role. Demo UI may offer “获取模拟回执” to real authorized initiator, always labeled simulation; it cannot select a business user role or fabricate authoritative human approval locally.


权威接收与人工登记分离：`source.pull(system,object_type,external_id)` 从服务器已配置适配器读取快照/回执，再用同一入站验证器应用。模拟到货/IQC/客户批准的原始外部状态由模拟权威端事件产生，场景可在该明确边界录入，平台必须 pull 后才采用。`supply.receive/inspect` 的人工登记永远标 manual；不能直接增加模拟权威库存。需要模拟库存改变时，在权威库执行 receive/inspect 原子事件，记录源版本，然后 pull 对应原始事实；场景种子不得直接改平台表。文件导入默认 mode=file，仅作为登记依据；没有已验证权威来源契约不能伪装已预留/已过账。此区分保证 E06 的到货/IQC 补料真正改变权威余额，E10 从同一权威余额竞争。

## 7. UI delivery contract

Keep ConsoleShell/account actions, existing Markdown renderer and whole handbook; extend navigation only when real workspace exists. New workflow uses `webui/src/workflow/{types.ts,api.ts,WorkflowHome.tsx,WorkflowProjects.tsx,OrdersWorkspace.tsx,SupplyWorkspace.tsx,ExecutionWorkspace.tsx,QualityWorkspace.tsx,DeliveryWorkspace.tsx,TraceWorkspace.tsx,ExchangeWorkspace.tsx,WorkflowDetail.tsx,ActionForms.tsx,workflow.css}`. Split domain forms into `forms/{Orders,Engineering,Supply,Execution,Quality,Delivery,Feedback}Forms.tsx` rather than an all-fields JSON editor. Useful everyday screens: searchable object lists; order remaining/committed/accepted quantities; material shortage lines and source cutoff; workorder fixed version/readiness reasons/trial-vs-bulk buttons; measurement input+test history; independent release panels; SN/box shipment selection; timeline and trace; RMA/CAPA actions. No “complete phase” button claiming these actions happened.

Each form uses named human labels, appropriate inputs, selectable authorized objects, explicit units, source/evidence, preview of affected quantity, and server-provided next_actions; refresh on mutation uses returned project_version. Distinguish pending request, accepted and posted in visible badges. Dataset/source label remains visible on every new workspace/detail. Legacy management views are grouped as existing projects only for legacy_access users. Handbook navigation preserves in-memory form and scroll; failed CAS keeps edited draft and exposes reload/diff choice; mutations never replace draft on failure. Logout/platform leave integrate existing single pending leave action and clear dirty notification before host guard runs. Auth revocation aborts requests, retires callbacks and clears sensitive data.

## 8. Acceptance, finite handoff and self-review

Plans [A](../plans/2026-10-28-workflow-a-business-identity.md), [B](../plans/2026-10-28-workflow-b-supply-execution.md), [C](../plans/2026-10-28-workflow-c-quality-delivery.md), [D](../plans/2026-10-28-workflow-d-ui-acceptance.md) own implementation. A defines shared contracts; B and C extend explicit command union without changing existing action meaning; D binds all UI and executes 36 scenarios. Each task starts with test failure, implements, verifies once, commits only its files, then receives spec/code review before next task. Follow-up fixes stay in scope without new user approval.

All F/E results remain unexecuted until actual runner evidence exists. Runner and UI must allow seeds other than fixed successful sample, persistent restart and deliberate failure; cannot directly update DB to successful states. DB read-only queries are allowed as verification; fixture may seed **only external authoritative state, isolated trusted identities, project grants**. Business preconditions must run through authorized API. D contains exhaustive case-to-task map and completion gate. Fresh runtime baseline must be captured before candidate release because Office deployment may move running source; no production deployment is implied by local completion.

Self-review performed: S1–S9, internal/OEM, all36 IDs mapped; old router/host exact whitelist respected; no employee Session fallback; empty-domain bootstrap and member shell specified; old projects unchanged; separate databases and immutable source labels; trial avoids circular gate; external quantity state isolated; grants read on every action; current/original promises, old/new revision, source receipt phases, per-SN ownership and freeze races covered; each module has finite scope and named types. No claim of implementation, visual approval, external connectivity or production acceptance is made here.
