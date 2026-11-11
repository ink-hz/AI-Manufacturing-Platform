# T3（P0）真实收货批次接续IQC正式结果，同次检验复用

日期：2026-11-11。状态：已拆分，待进入实施。

**用户动作→输出**：MC在待检需求点击安排检验，看到准确收货/批次、检验对象、位置与联系人；IQC从我的待办接单，打开已核实源入口、更新进展、刷新并引用正式结果。已检部分交后续仓配，待检数量继续办理。

**交付**：
- 原生IQC通过可信采集入口持久保存并投影到准确收货，复用准入/幂等/权限；`MesIqcResults`中的mock/system事实列表不等于已接原生。
- 核对收货行、批次、检验号、单位和数量范围；物料相同不提供本批引用按钮，0条显示本次实际空结果。
- 同项目同次已核实检验对象关联多需求、复用一个任务；撤销一个需求不撤销其他需求的任务；只显示有权关联。
- 未到货显示准备信息；身份/位置不清可交核实责任人，不能迫使虚构到货/结果。未核实源入口不给猜测链接。

**依赖**：T1身份/持久采集；真实收货与检验的关系仍需证据。批次投影、共享关联、缺项办理可用明确测试事实独立完成。

**验收**：同物料异到货/批次/单位排除；20件合格12+拒收8可完成该次已检范围，补料问题保留；合格12+待检8保留8待检；更正/重放按当前源版本；两个需求共享任务不重复检验；接手不写成MES已检验，不授予质量放行。

**文件**：`src/manufacturing_platform/mes_access/{registry.py,service.py}`；`src/manufacturing_platform/workflow/integrations/{core_projections.py,core_admission.py,core_models.py,browse.py}`；`src/manufacturing_platform/workflow/{material_tasks.py,material_task_models.py,material_task_schema.py,material_task_reader.py,material_control.py,supply.py}`；`webui/src/workflow/materialControl/{MesIqcResults.tsx,MaterialTaskOpen.tsx,MaterialTaskPanel.tsx,MaterialTaskList.tsx}`；`webui/src/workflow/GlobalTasks.tsx`；`tests/workflow/test_material_tasks.py`、`webui/src/workflow/materialControl/MesIqcResults.test.tsx`。
