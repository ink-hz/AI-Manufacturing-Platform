# T5（P1，可独立先做）分笔发料追踪与剩余物料最后确认位置

日期：2026-11-11。状态：已拆分，待进入实施。

**用户动作→输出**：仓库/MC从需求打开发料追踪，按单据/批次/交接号找分笔，同时看打印/拣配/回执/过账及交出/领取/送达/实收；指定接收人从该笔签收，差异沿原笔发起现有寻料任务。

**交付**：
- 增加发料单据行、数量范围及实际分笔关联；人工stage标记保持人工说明，无真实凭据不变SAP过账事实。现有原生registry无完整实际发料接口，先交付平台关联/视图/缺项，核实源接口后接入。
- 连续交接有上游/下游关系和数量，直接仓库→产线有效，不强制物流步骤。每笔显示双方/时间/位置/未确认量/待办。
- 同批多位置分别表达；剩余2不套已收18位置；查明事实、保管人、追查负责人分别呈现，复用既有签收/寻料规则。
- 当前缺有类型的正式差异处置证据，继续保留未解决；正式退回/转交/损失处置必须先有可信来源类型，不靠文字说明补实收。

**依赖**：平台分笔关系/视图可先做；原生发料/回执/过账映射及保管关系依实际凭据，不承诺未知接口。

**验收**：20交出/18实收/2找到未签收仍待收2；后续指定人真签收2才消差额；多位置分笔正确；源单重放不重复交接；回执/过账不冒充实收；合法直接路径能办；管理员不能代签。

**文件**：`src/manufacturing_platform/workflow/{issue_mark_models.py,issue_marks.py,material_handoff_models.py,material_handoffs.py,material_handoff_schema.py,material_handoff_reader.py,material_control.py,material_tasks.py}`；`src/manufacturing_platform/workflow/integrations/{core_custody.py,core_wms.py,core_sap.py}`（核对既有边界）；`webui/src/workflow/materialControl/{MaterialFlowPanel.tsx,MaterialTaskPanel.tsx,types.ts}`；`webui/src/workflow/{MaterialHandoffWorkspace.tsx,details/MaterialHandoffDetails.tsx}`；`tests/workflow/{test_issue_marks.py,test_material_handoffs.py,test_material_tasks.py,test_material_control.py}`。
