# T1（P0）同一项目绑定真实源工单并刷新完整需求

日期：2026-11-11；更新：2026-11-12。状态：本轮MES工单关联与完整组件查看已完成本地开发和联调；SAP对照与联合需求准入继续接续。M5契约mock已补[专项spec](../../superpowers/specs/2026-11-12-sap-mrp-contract-mock-design.md)，尚未实现。[已有实施计划](../../superpowers/plans/2026-11-11-oem-native-order.md)、[验收记录](../../verification/oem-native-order-2026-11-11.md)。

**用户动作→输出**：有权项目负责人选择来源、环境、工厂/站点和工单，查看组件预览、冲突及关联依据后建立绑定；计划员点击「刷新工单料况」，取得当前工单完整组件范围、读取时点、覆盖情况和具体缺项。普通岗位办理不填写内部技术来源编号。

**交付**：
- 增量保存带环境身份和核实依据的项目/工单绑定，更正/失效有历史；同号不自动绑定，测试/生产和不同站点不撞身份。
- 以现有原生服务实现业务用途的有界分页采集，保留总数、已取页、重复/变动/失败/上限；未取全不能表示完整需求。
- 完整刷新成功才更新已验证读取版本；失败保留旧事实及旧时点，未读行不删除；取消、重试、旧响应均不能覆盖新版本。
- 原字段、源数量语义、单位、工序/组件身份保留；未核实剩余需求语义前不直接套平台净需求算法。

**依赖**：真实启用需要OEM工单、工厂/站点和平台项目关系；绑定模型、UI、采集器和失败行为可立即开发。维持原生允许项、授权和固定查询边界，不开放任意URL/SQL。

**验收**：12行/3页完整样本显示12行；跨页重复、总数变动、第二页失败、同号异环境、撤权、旧响应/源重放不误报完整且不覆盖新事实；错误绑定不产生需求/质量/库存事实；重启后绑定和读取范围可查。真实验收另用实际OEM对象，不把当前不匹配样本修成一致。

## 评审扩展：SAP MRP契约mock（M5，依赖M4）

**交付**：按真实测试WSDL、固定`BAPI_MATERIAL_STOCK_REQ_LIST`请求和共用解析链构造模拟SOAP；只替换传输，保留物料＋工厂查询范围。七场景为现货足够、缺料、迟到、部分到货、空结果、业务拒绝、超时。隔离项目料况内查看供需对照；场景选择在联调管理区。

**前置与边界**：T2逐项来源契约先行，mock身份在API、页面和证据中持续保留；默认关闭、受信配置启用、失败不自动切mock。现有SAP传输仅支持开发/测试环境，不在这项任务中开放生产。与生产MES观察不自动合并，不产生真实库存、质量、预留或生产齐套。

**验收**：脱敏真实契约fixture结构一致、所有场景经过现有解析器、无真实网络；51行/非法字段/响应超限准确失败；来源、环境、日期、单位和精度保留；失败保留旧事实及旧时点；跨项目、撤权、旧响应、宿主精确路由和旧版本不可用均验证。后续真实SAP环境与同单映射单独验收，不因mock通过勾完T1联合需求。

**文件**：`src/manufacturing_platform/mes_access/{registry.py,service.py,api.py}`；`src/manufacturing_platform/sap_access/{service.py,stock_requirements.py,api.py}`；`src/manufacturing_platform/workflow/{store.py,schema.py,material_control.py,material_control_api.py,orders.py,supply.py}`；`src/manufacturing_platform/workflow/integrations/{contracts.py,core_admission.py,core_projections.py}`（核对复用边界，不把mock执行当原生）；`webui/src/workflow/materialControl/{api.ts,types.ts,MaterialControlWorkspace.tsx}`；`tests/mes_access/`、`tests/sap_access/`、`tests/workflow/test_material_control.py`。绑定/采集职责可新增独立模块。
