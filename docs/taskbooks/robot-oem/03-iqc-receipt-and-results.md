# T3（P0）真实收货批次接续IQC正式结果，同次检验复用

日期：2026-11-11；更新：2026-11-12。状态：M2引用核实与已准入收货直接安排IQC已实现，验证与交付见[记录](../../verification/material-task-references-2026-11-12.md)。T3剩余为原生收货/结果准入及无证据跨工单共享检验。

**用户动作→输出**：MC在待检需求点击安排检验，看到准确收货/批次、检验对象、位置与联系人；IQC从我的待办接单，打开已核实源入口、更新进展、刷新并引用正式结果。已检部分交后续仓配，待检数量继续办理。

**T3整体目标（包含后续工作）**：
- 原生IQC通过可信采集入口持久保存并投影到准确收货，复用准入/幂等/权限；`MesIqcResults`中的mock/system事实列表不等于已接原生。
- 核对收货行、批次、检验号、单位和数量范围；物料相同不提供本批引用按钮，0条显示本次实际空结果。
- 同项目同次已核实检验对象关联多需求、复用一个任务；撤销一个需求不撤销其他需求的任务；只显示有权关联。
- 未到货显示准备信息；身份/位置不清可交核实责任人，不能迫使虚构到货/结果。未核实源入口不给猜测链接。

**依赖**：T1身份/持久采集；真实收货与检验的关系仍需证据。批次投影、共享关联、缺项办理可用明确测试事实独立完成。

## M2交付：解除协同前置的重复登账

- 任务可引用项目内持久到场观察、MES组件及已有准确收货；组件只支持核实，源收货投影当前为明确mock。按稳定范围复用在办任务，保留责任人、原依据和历史；不要求重新手填供应承诺、收货或批次来解锁协同。
- `arrival.record`只有包裹数和位置，不是正式收货；有包裹观察但身份不足时创建可分派、接手、反馈的**核实任务**，完成条件为有据核实/有原因结论。不能将这种任务伪装成检验完成，不能隐式增加库存或合格数量。
- 已有准确收货通过项目、需求lineage/工单/物料/货主/单位/精度校验后可直接安排IQC；观察后来匹配到收货，可在详情按当前真实匹配接续。初始依据保持固定，源别名经现有准入校验后复用实际收货范围。结果准入仍逐项校验。
- 无原生收货契约时先完成核实协同路径；原生IQC生产准入继续等待真实映射证据。平台原有例外声明入口就地可达且明确用途，不作为所有用户的必经前置。
- **本轮验收**：空需求到场观察可分派、接手、反馈和有据结束；保存的MES组件不生成平台需求；已准入mock准确收货直接IQC并复用原任务。跨项目、错误身份/材料/精度、撤权、幂等及陈旧引用分别拒绝；当前关联更正不暗改初始依据或草稿目标。
- **岗位页面**：现有料况就地发起、事项接手、详情办理；无需内部UUID输入。晚到回执与同任务刷新保留新草稿，当前依据未就绪时禁用提交；收货变化须明确重新选择。
- **数量条件**：核实完成不消待检数量；合格12/待检8保留8，合格12/拒收8可结束本次已检范围但保留补料问题。同收货的兼容需求可留上下文关联，不分配数量；无证据跨工单共享待后续。

**验收**：同物料异到货/批次/单位排除；20件合格12+拒收8可完成该次已检范围，补料问题保留；合格12+待检8保留8待检；更正/重放按当前源版本；两个需求共享任务不重复检验；接手不写成MES已检验，不授予质量放行。

**文件**：`src/manufacturing_platform/mes_access/{registry.py,service.py}`；`src/manufacturing_platform/workflow/integrations/{core_projections.py,core_admission.py,core_models.py,browse.py}`；`src/manufacturing_platform/workflow/{material_tasks.py,material_task_models.py,material_task_schema.py,material_task_reader.py,material_control.py,supply.py}`；`webui/src/workflow/materialControl/{MesIqcResults.tsx,MaterialTaskOpen.tsx,MaterialTaskPanel.tsx,MaterialTaskList.tsx}`；`webui/src/workflow/GlobalTasks.tsx`；`tests/workflow/test_material_tasks.py`、`webui/src/workflow/materialControl/MesIqcResults.test.tsx`。
