# 真实MES源工单工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. Steps use checkbox syntax.

**Goal:** 线上零平台项目下能从真实MES工单查看组件、优先级和相关IQC，主业务入口可用。

**Architecture:** 原生固定SELECT/既有只读profile→Mac固定RPC/SSH Unix socket→云selector→带来源的本地观察缓存→主页及工单/物料入口。SAP测试保持独立。

**Tech Stack:** Python3.11、现有FastAPI/SQLite/React、stdlib隔离worker、OpenSSH/launchd、既有API-only发布。

## Global Constraints

- AGENTS生产源只读持续有效；不运行MRP、写MES/SAP/WMS、打印或业务后台任务，不制造源数据。
- 实现以spec精确上下文、操作、字节/行/并发/硬期限为准，不提供任意SQL/URL/函数/目标或自动源重试。
- 源身份、观察、正式事实分别保留；不猜跨系统关联、不创建虚拟项目/工单/需求、不恢复演示。
- 凭据和原始业务证据仅私有600/700；云只收中转令牌。保留根3处用户修改。
- 页面首次实际读取且可失败；管理员范围/CSRF/只读授权保持，不假扮员工浏览器验收。
- 受控API-only切换，原SAP/产测/SDK/全部有序Compose/静态/其他容器和Nginx保全。

### Task 1: 原生工单身份只读目录

Files: mes_access/source_orders.py, service.py, registry.py, parsing.py；tests/mes_access/test_source_orders.py。

Interfaces: read_context()及source_orders(prefix,after,actor_id,*,expected_fingerprint=None)，精确结果见spec。collect_order_materials和query保留兼容。

- [ ] TDD固定SQL、SITE不可覆写、真实字段形状、keyset/5行、无总数、重复/倒退/不符拒绝、精度与来源指纹。
- [ ] 实现并运行MES相关测试；独立评审及提交。

### Task 2: MES固定中转与selector

Files: mes_access/relay_protocol.py, relay_gateway.py, relay_native_worker.py, relay_client.py, selector.py, __init__.py；必要共享worker；scripts/sap_relay_supervisor.py静态profile扩展和mes_relay_supervisor.py；tests/mes_access/test_relay_*.py及supervisor回归。

Consumes Task1 native methods; cloud publicinterface保持query/collect_order_materials/order_materials_configuration/configuration_matches/read_context/source_orders。

- [ ] TDD认证先行、5操作严格参数、上下文/nonce/作用域、无I/O构造、私有配置、独立worker65/70秒、限流、断线/保留错误、ready原子持有和退出。
- [ ] 实现固定云/原生指纹、校验native形状，兼容旧native调用；复用不放宽SAP协议。
- [ ] SSH profile仅两处固定目录和各自context验证，SAP默认回归；独立评审及提交。

### Task 3: 源观察HTTP与缓存

Files: workflow/mes_source.py, schema.py, api.py；tests/workflow/test_mes_source.py；PF backend/app/manufacturing_paths.py及相关host tests。

Interfaces: spec 9routes/status+cache-response、schema30；WorkflowService已有mes_access_service注入复用。仅该9route加入PF精确allowlist。

- [ ] TDD零projects真实注入服务可读；管理员/目录/只读/CSRF、精确query、空/完整/失败旧缓存、配置/刷新竞争、无隐式正式对象、schema迁移。
- [ ] 实现事务外源I/O与最终本地指纹接纳；主机实际router及身份中间件隔离测试。
- [ ] 独立评审及两仓精确提交。

### Task 4: 主入口真实工单与物料旅程

Files: workflow source API/types、MesSourceWorkbench及测试、WorkflowApp/WorkflowHome/OrdersWorkspace/SupplyWorkspace等最小接线。

- [ ] 测试先行：首页/工单入口零平台项目可加载；选中工单到组件、优先级、IQC；页码和工单/物料/账号异步隔离；真实空/离线旧缓存/时间与生产标签。
- [ ] 主页面源入口可用，保留正式台账为次级，不改正式计数或伪造项目。
- [ ] 前端组件/类型检查/构建；独立评审及提交。

### Task 5: Mac服务与线上完整只读验收

Files: deploy/release_guard.py/release.py/build_artifact.py/install_payload.py及测试、运维与验收文档；私有部署控制文件不入Git。

- [ ] TDD MES两env/严格私有配置及socket存储校验，兼容原SAP/产测及Compose保护。
- [ ] 安装独立Mac MES固定服务/隧道，先真实本地再云查询列表/组件/priority/IQC，受控保留证据，不切SAP。
- [ ] 整分支评审、归并推送主线；精确API-only候选37/OEM与29→30迁移/保全；零projects隔离HTTP全旅程与己方隧道停恢复。
- [ ] 受控切换，实际线上source API数据与健康保全，记录版本、范围、未验员工浏览器及恢复路径。
