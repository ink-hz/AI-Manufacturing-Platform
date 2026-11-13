# SAP真实测试环境读取 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 现有计划与物料入口直接查询真实SAP测试工单、组件和MRP供需。

**Architecture:** 原生受控读取→工作流管理员业务路由及本地观察快照→现有料况入口。源系统无业务写入；SAP测试数据始终为独立观察。

**Tech Stack:** Python3.11/FastAPI/SQLite/React19/TypeScript/vitest。

## Global Constraints

- 遵守根AGENTS.md，生产源只读；本轮SAP也只调用已核实的精确读取。
- 凭据及真实业务数据仅私有文件；不入Git/日志/公共报告。不恢复旧演示数据。
- 当前能力不等待75项全部通过；缺权报告具体功能，不绕过权限。
- 原设计与用户开发授权已确认，连续实施。原目录用户修改保留，隔离工作树开发。

### Task 1: 原生SAP单工单适配

Files: `sap_access/production_order.py`, `service.py`, `transport.py`, `registry.py`, `sap_connection.py`; tests `tests/sap_access/test_production_order.py`。

Interfaces: `SapAccessService.production_order(number, plant, actor_id)`输出spec中工单data及request_id/function；`read_context()`返回非敏感source及私有fingerprint；`configuration_matches(fingerprint)`用于读取前后核对。MRP继续`stock_requirements(material,plant,actor_id)`。

- [x] 先写测试并确认失败：固定单号/工厂校验；请求仅抬头/组件，禁止扩展；RETURN错误失败；错单/错工厂/重复组件/501条失败；字符串数量原样；合同结构变动拒绝。
- [x] 实现固定只读适配；工单号限1–12个数字并补齐12位；工厂1–4位字母数字。WSDL以实际捕获的字段为准，不猜字段。
- [x] 测试传输层对新增函数固定请求的逐字段防篡改；旧Z函数仍拒绝；生产环境配置仍拒绝。
- [x] 运行 `PYTHONPATH=src /opt/homebrew/bin/python3.11 -m pytest tests/sap_access -q`；提交仅本任务文件。

### Task 2: 源观察持久化与业务HTTP

Files: `workflow/sap_materials.py`, `sap_material_schema.py`, `api.py`, `service.py`, `schema.py`, `store.py`; tests `tests/workflow/test_sap_materials.py`。宿主 `backend/app/manufacturing.py`, `manufacturing_paths.py`及对应host tests。

Interfaces: spec固定路由及观察响应；`build_workflow_router(...,sap_access_service=None)`由宿主注入同一实例。source={system:'sap',origin:'native',fact_role:'observation',environment,system_id,client,namespace}。

- [x] 编写管理员/非管理员/只读、无配置、精确对象、失败保留、配置切换、并发刷新和旧schema升级测试，并先确认失败。
- [x] 新增schema29表，以fingerprint/kind/对象键唯一。仅最后成功快照持久化；事务在源I/O之外；同键并发以收集开始序号避免较旧请求覆盖较新结果。
- [x] 增加固定GET/POST路由及服务注入。POST拒绝非空body及多余query，错误脱敏，GET不触源。
- [x] 宿主精确注册业务路径并保持原认证、CSRF、只读保护，不开放任意原生函数入口。
- [x] 运行相关workflow和宿主HTTP回归并提交。

### Task 3: 料况入口与真实受控验证

Files: `webui/src/workflow/materialControl/SapMaterialBrowser.tsx`, 对应测试、types/API、`MaterialControlOverview.tsx`；私有验证脚本和脱敏验证记录。

Interfaces: 消费Task2固定业务响应；用户输入工单/工厂，组件按钮以返回的material/plant查询MRP。

- [x] 前端先写失败测试：环境来源/时点、工单组件→MRP、空结果、失败保留、作用域/账号切换后不展示旧异步数据。
- [x] 实现现有入口中的查询及MRP明细，不增加独立导航、演示数据或不可用按钮；MRP采用有中文含义的源字段展示，缺失字段显示未知，不算净缺口。
- [x] 运行组件测试及`npm run build`；运行完整受影响Python回归。
- [x] 使用AI03私有配置和既有真实对象，通过实际生产代码与真实HTTP测试工单和MRP；证据仅私有保存，公开记录脱敏结果/版本/未验证范围。
- [x] 独立代码评审、修复、合并主线。部署按当前宿主安全规则评估准备，生产发布状态如实报告，不将本地通过称为线上。

## 实施结果（2026-11-13）

三个任务完成并通过独立评审；验收模型以spec最后一节为准，撤销补偿方案已移除。当前源测试及发布限制见[验证记录](../../verification/sap-real-test-read-2026-11-13.md)。线上未部署，云端到SAP测试网络尚不通；员工浏览器验收未执行。
