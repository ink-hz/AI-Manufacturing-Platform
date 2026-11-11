# T1（P0）同一项目绑定真实源工单并刷新完整需求

日期：2026-11-11。状态：开发中，当前先交付MES工单关联与完整组件查看。实施计划：../../superpowers/plans/2026-11-11-oem-native-order.md。

**用户动作→输出**：有权项目负责人选择来源、环境、工厂/站点和工单，查看组件预览、冲突及关联依据后建立绑定；计划员点击「刷新工单料况」，取得当前工单完整组件范围、读取时点、覆盖情况和具体缺项。普通岗位办理不填写内部技术来源编号。

**交付**：
- 增量保存带环境身份和核实依据的项目/工单绑定，更正/失效有历史；同号不自动绑定，测试/生产和不同站点不撞身份。
- 以现有原生服务实现业务用途的有界分页采集，保留总数、已取页、重复/变动/失败/上限；未取全不能表示完整需求。
- 完整刷新成功才更新已验证读取版本；失败保留旧事实及旧时点，未读行不删除；取消、重试、旧响应均不能覆盖新版本。
- 原字段、源数量语义、单位、工序/组件身份保留；未核实剩余需求语义前不直接套平台净需求算法。

**依赖**：真实启用需要OEM工单、工厂/站点和平台项目关系；绑定模型、UI、采集器和失败行为可立即开发。维持原生允许项、授权和固定查询边界，不开放任意URL/SQL。

**验收**：12行/3页完整样本显示12行；跨页重复、总数变动、第二页失败、同号异环境、撤权、旧响应/源重放不误报完整且不覆盖新事实；错误绑定不产生需求/质量/库存事实；重启后绑定和读取范围可查。真实验收另用实际OEM对象，不把当前不匹配样本修成一致。

**文件**：`src/manufacturing_platform/mes_access/{registry.py,service.py,api.py}`；`src/manufacturing_platform/sap_access/{service.py,stock_requirements.py,api.py}`；`src/manufacturing_platform/workflow/{store.py,schema.py,material_control.py,material_control_api.py,orders.py,supply.py}`；`src/manufacturing_platform/workflow/integrations/{contracts.py,core_admission.py,core_projections.py}`（核对复用边界，不把mock执行当原生）；`webui/src/workflow/materialControl/{api.ts,types.ts,MaterialControlWorkspace.tsx}`；`tests/mes_access/`、`tests/sap_access/`、`tests/workflow/test_material_control.py`。绑定/采集职责可新增独立模块。
