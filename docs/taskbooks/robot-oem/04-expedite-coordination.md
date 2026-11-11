# T4（P1，可独立先做）急料并行岗位协同及有依据结束

日期：2026-11-11。状态：已拆分，待进入实施。

**用户动作→输出**：MC打开已有急料，看到需求/需要时间/影响、协调负责人、并行卡点与岗位任务；按卡点交采购/仓配/IQC。责任转交由对方接手后生效；点击核对解决得到满足与未满足条件，满足才以已解决结束。

**交付**：复用案件/任务生命周期，增加协调负责人/拟接手人/历史及明确采购跟进、仓配核实等范围；不把多问题塞一个串行阶段。在办案件/任务直接打开。需要时间、预计完成/受阻进入待协调列表，不臆造班次时限。增加结束核对读侧及服务端条件；误报/替代有适用依据，旧文字结束保留原性质。

**依赖**：可立即基于平台需求、分配、IQC、交接做；T1/T2/T3随后补真实事实。采购和仓库源系统写入不在此任务范围。

**验收**：20仅实收18仍差2不可已解决；IQC完成但分配/接收未解决不关闭；采购与IQC任务并行不代结；转交未接手前原负责人仍在；重复提醒不新增；跨项目/撤权/只读拒绝；旧文字记录不补造证据。

**文件**：`src/manufacturing_platform/workflow/{expedite.py,expedite_models.py,expedite_schema.py,material_tasks.py,material_task_models.py,material_task_schema.py,material_control.py,commands.py}`；`webui/src/workflow/materialControl/{ExpeditePanel.tsx,ExpediteHistory.tsx,MaterialTaskOpen.tsx,MaterialTaskPanel.tsx}`；`webui/src/workflow/{GlobalTasks.tsx,types.ts}`；`tests/workflow/{test_expedites.py,test_expedite_tasks.py,test_material_tasks.py}`。
