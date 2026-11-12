# T4（P1，可独立先做）急料并行岗位协同及有依据结束

日期：2026-11-11；更新：2026-11-12。状态：平台卡点办理与按当前证据结束已实现；完整协调负责人转交和采购跟进范围仍待开发。

**用户动作→输出**：MC打开已有急料，看到需求/需要时间/影响、协调负责人、并行卡点与岗位任务；按卡点交采购/仓配/IQC。责任转交由对方接手后生效；点击核对解决得到满足与未满足条件，满足才以已解决结束。

**交付**：复用案件/任务生命周期，增加协调负责人/拟接手人/历史及明确采购跟进、仓配核实等范围；不把多问题塞一个串行阶段。在办案件/任务直接打开。需要时间、预计完成/受阻进入待协调列表，不臆造班次时限。增加结束核对读侧及服务端条件；误报/替代有适用依据，旧文字结束保留原性质。

**依赖**：可立即基于平台需求、分配、IQC、交接做；T1/T2/T3随后补真实事实。采购和仓库源系统写入不在此任务范围。

**本次交付**：结束前分开核对当前需求、相关批次合格量、有效分配、线边实收和剩余待收；后台在写事务中重新核对并留存证据。20需/18实收不可结束，“找到2”仍不可结束，指定人补签2并核实独占补收关系后才可结束。老记录用途默认为待核对，只有原指定接收人能补充用途，原签名/数量/位置保留；旧文字结束不补造证据。已有IQC/寻料任务继续复用并支持实际责任与拟接手人分别展示。见[验证记录](../../verification/material-analysis-2026-11-12.md)。本次未新增外部通知发送、原生仓库写入或采购任务类型。

**验收**：20仅实收18仍差2不可已解决；IQC完成但分配/接收未解决不关闭；采购与IQC任务并行不代结；转交未接手前原负责人仍在；重复提醒不新增；跨项目/撤权/只读拒绝；旧文字记录不补造证据。

**文件**：`src/manufacturing_platform/workflow/{expedite.py,expedite_models.py,expedite_schema.py,material_tasks.py,material_task_models.py,material_task_schema.py,material_control.py,commands.py}`；`webui/src/workflow/materialControl/{ExpeditePanel.tsx,ExpediteHistory.tsx,MaterialTaskOpen.tsx,MaterialTaskPanel.tsx}`；`webui/src/workflow/{GlobalTasks.tsx,types.ts}`；`tests/workflow/{test_expedites.py,test_expedite_tasks.py,test_material_tasks.py}`。
