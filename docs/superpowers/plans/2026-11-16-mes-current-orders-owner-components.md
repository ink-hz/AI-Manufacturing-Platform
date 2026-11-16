# MES近期工单及所属组件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** 默认展示近期真实工单，按所属工单准确取得MES组件，SAP独立查询不混入当前MES旅程。

**Architecture:** 两个私有固定SELECT profile和类型化原生方法→兼容旧模式的5操作RPC→v2观察缓存→近期目录/空组件与独立SAP入口。

**Tech Stack:** 既有Python/FastAPI/SQLite/React；不增依赖。

## Global Constraints

- AGENTS生产只读；子代理不得调用源、SSH、Docker或launchctl，运维仅父代理。
- 无任意SQL/URL/表列/站点输入；新SQL代码持有、值绑定、每页5，完整组件100行/20页；2MiB/65秒/4并发不放宽。
- 不猜MES生产与SAP测试映射，不自动正式对象或回写。不将组件空等于需求0。
- legacy native及无模式RPC保持；先Mac再新云。私有v2缓存键失效旧投影但保留旧行。
- 保留根三个用户修改；凭据/原始业务证据私有600/700；员工浏览器不冒充。

### Task 1: 原生固定profile

Files: mes_access/registry.py、parsing.py、service.py、source_orders.py、order_materials.py、store.py及对应tests。

Produces: spec同名两个新方法；registry私有名source_order_components/source_orders_recent。legacy保持。新collector复用完整性逻辑，使用私有profile允许首轮0行，row_count审计、所有页request_ids仍有。

- [ ] TDD反例所属工单有行而legacy空；新固定SQL及精确owner、页码/计数/重复/变更/100上限/0行/精度；不能通用query调用。
- [ ] TDD近期日期顺序/NULL日期/编号tie/前缀/锚点绑定/无NULL参数/游标/原始timestamp+nanos；执行本地MES测试并精确提交。

### Task 2: RPC、selector和缓存

Files: mes_access/relay_protocol.py、relay_gateway.py、relay_client.py、selector.py；workflow/mes_source.py及tests。

Consumes: Task1两个新方法及新items形状。无模式旧调用仍legacy，新selector调用新方法；可选模式仅固定recent/owner。空结果只对owner允许，至少1个成功页UUID。

- [ ] TDD新旧两模式精确字段/拒绝未知/认证先行/nonce/context/scope、近期列表形状/顺序/0组件/来源与审计关联；不增加operation。
- [ ] TDDv2缓存不误用旧投影、保留旧行、零正式对象，原并发缓存/失败/权限边界；相关MES+工作流测试，精确提交。

### Task 3: 用户旅程

Files: webui/src/workflow/mesSource/types.ts、MesSourceWorkbench.tsx/tests、WorkflowApp.tsx及entry测试。

- [ ] TDD目录创建日期及has_components真/假/未知，0组件友好空状态与禁止需求0；保留异步/并发缓存修复。
- [ ] TDD默认不挂载SAP浏览器、显式按钮才加载，MES选单不自动打开或复制编号；原来源和正式台账身份仍正确。相关前端测试及构建，精确提交。

### Task 4: 真实只读及发布

- [ ] 独立评审全部分支；父代理本机新方法真实两页及三个精确组件案例；失败保留、未知不猜。
- [ ] Mac服务先升级并证明legacy仍可用，再云探针/隔离HTTP和React新旅程；v2缓存保全、零源/正式业务写入。
- [ ] 归并主线精确构建，固定37及OEM与三库保全；受控切换、实际只读源和静态/健康验收，记录未验员工浏览器及恢复路径。
