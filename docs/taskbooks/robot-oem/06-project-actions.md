# T6（P1，可独立先做）项目总览直接进入今天要办的对象

日期：2026-11-11；更新：2026-11-12。状态：已拆分，待进入实施；先交M6完整物料事项及M3料况直达，再扩展项目总览。

**用户动作→输出**：负责人默认看有未完成生产/交付的授权OEM项目，按物料影响生产/急料待检/已发未实收/资料待核实筛选；数字直接进入准确工单/需求/批次/分笔并看当前责任/行动。项目内分别展示有来源的计划、执行、质量、入库、发运事实。

**交付**：已有事实先形成问题分类、全范围汇总/下钻；缺阶段数据展示具体缺项，不造健康分。当前工单与历史区分。需求数、在办急料需求数、待检对象数、未接收分笔数口径分别明确。显示当前计划范围、读取时间及覆盖/陈旧；状态未知项目单列，不默认为完成或无风险。T1/T3/T5随后补原生与阶段事实。

**依赖**：当前项目/订单/工单/任务足够先交可用行动总览；T2补问题索引。缺原生产能/排程不阻止独立开发，也不推算新承诺交期。

## 评审修订待办：M6完整物料责任事项

复用现有“事项”作为跨项目岗位入口；项目料况保留项目内关联列表。首期完整集合至少包含：本人待接手/处理中IQC任务、本人待接手/处理中查料任务、指定给本人的待签收交接、本人作为交出人需处置的差异。M2新增核实任务接续同一责任查询。

按当前项目授权、实际责任及可执行动作**先筛选，再全范围计数和稳定分页**。不能将每项目50条截断结果拼接后称为全部，也不能用所有人的物料任务台账代替本人待办。按项目＋对象＋责任事项去重，交接与差异不被只有material_task的独立台账漏掉。其他业务的历史有界查询可以保持原口径并单独标明范围；完整物料事项的统计不受其截断影响。

**验收增加**：单项目超过50、跨多个项目和末页仍能找到所有应办物料事项；同一人多职责不重复；转交待接手与现责任显示准确；已结束不再列入；撤权/只读/跨项目无泄露。列表进入准确任务/交接后可实际接手、反馈、签收或处理差异，返回原筛选和页码。M3从侧栏默认进料况，授权项目选择支持完整分页，台账保留次级入口。

**验收**：51+项目/需求分页仍为全范围统计，或明确样本/下界；多单位不强合计；两急料共享检验只计一个待检对象；旧resolved短收仍计未实收；下钻与分类数字一致；返回保留过滤/页码；撤权无泄露。

**文件**：`src/manufacturing_platform/workflow/{material_control.py,material_control_models.py,material_control_api.py,service.py,progress.py,readiness.py,execution.py,delivery.py}`；`webui/src/workflow/{WorkflowHome.tsx,GlobalTasks.tsx,navigationContext.ts,homePresentation.ts}`；`webui/src/workflow/materialControl/{MaterialControlOverview.tsx,MaterialControlWorkspace.tsx,types.ts,api.ts}`；`tests/workflow/test_material_control.py`、`webui/src/workflow/materialControl/MaterialControlOverview.test.tsx`。
