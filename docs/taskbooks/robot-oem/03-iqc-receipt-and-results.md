# T3（P0）真实收货批次接续IQC正式结果，同次检验复用

日期：2026-11-11；更新：2026-11-12。状态：平台IQC任务已有实现；原生收货/结果准入、共享检验与M2任务引用扩展待实现。

**用户动作→输出**：MC在待检需求点击安排检验，看到准确收货/批次、检验对象、位置与联系人；IQC从我的待办接单，打开已核实源入口、更新进展、刷新并引用正式结果。已检部分交后续仓配，待检数量继续办理。

**交付**：
- 原生IQC通过可信采集入口持久保存并投影到准确收货，复用准入/幂等/权限；`MesIqcResults`中的mock/system事实列表不等于已接原生。
- 核对收货行、批次、检验号、单位和数量范围；物料相同不提供本批引用按钮，0条显示本次实际空结果。
- 同项目同次已核实检验对象关联多需求、复用一个任务；撤销一个需求不撤销其他需求的任务；只显示有权关联。
- 未到货显示准备信息；身份/位置不清可交核实责任人，不能迫使虚构到货/结果。未核实源入口不给猜测链接。

**依赖**：T1身份/持久采集；真实收货与检验的关系仍需证据。批次投影、共享关联、缺项办理可用明确测试事实独立完成。

## 评审修订待办：M2解除重复登账

- 任务可引用项目内持久的到场观察或已核实原生对象；按引用范围去重并保存来源身份。保留既有本地收货/IQC任务历史，不要求重新手填供应承诺、收货或批次来解锁协同。
- `arrival.record`只有包裹数和位置，不是正式收货；有包裹观察但身份不足时创建可分派、接手、反馈的**核实任务**，完成条件为有据核实/有原因结论。不能将这种任务伪装成检验完成，不能隐式增加库存或合格数量。
- 收货行、批次、单位、检验对象及关联需求已核实时，直接引用观察/原生身份安排IQC；后台的引用投影不另造一套正式原账。结果准入仍逐项校验，不因“任务可创建”而放宽。
- 无原生收货契约时先完成核实协同路径；原生IQC生产准入继续等待真实映射证据。平台原有例外声明入口就地可达且明确用途，不作为所有用户的必经前置。
- **验收增加**：只有到场观察、没有本地收货时也能派人核实；原生对象核实后安排检验无需重录正式数量；观察重放/错误批次/跨项目/撤权不串任务。核实完成不消待检数量；合格12/待检8保留8，合格12/拒收8可结束本次已检范围但保留补料问题。

**验收**：同物料异到货/批次/单位排除；20件合格12+拒收8可完成该次已检范围，补料问题保留；合格12+待检8保留8待检；更正/重放按当前源版本；两个需求共享任务不重复检验；接手不写成MES已检验，不授予质量放行。

**文件**：`src/manufacturing_platform/mes_access/{registry.py,service.py}`；`src/manufacturing_platform/workflow/integrations/{core_projections.py,core_admission.py,core_models.py,browse.py}`；`src/manufacturing_platform/workflow/{material_tasks.py,material_task_models.py,material_task_schema.py,material_task_reader.py,material_control.py,supply.py}`；`webui/src/workflow/materialControl/{MesIqcResults.tsx,MaterialTaskOpen.tsx,MaterialTaskPanel.tsx,MaterialTaskList.tsx}`；`webui/src/workflow/GlobalTasks.tsx`；`tests/workflow/test_material_tasks.py`、`webui/src/workflow/materialControl/MesIqcResults.test.tsx`。
