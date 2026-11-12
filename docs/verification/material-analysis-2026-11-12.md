# 工单料况分析与急料实收核对验证

日期：2026-11-12。对应[实施计划](../superpowers/plans/2026-11-12-material-analysis-and-resolution.md)、[T2](../taskbooks/robot-oem/02-material-analysis.md)、[T4](../taskbooks/robot-oem/04-expedite-coordination.md)。

计划员可在当前项目全范围搜索物料、按工单与问题筛选，结果先过滤再分页。每条需求并列显示缺料、急料、待检、未实收和待核实卡点，显示实际与拟接手人；点击进入对应批次、交接或已有任务。需要时间可带依据修改、重置为明确标记的工单开始代理并查看历史。时间风险独立于已发起急料。

接收人签收时选择中转或线边用途；线边实收必须选择相容的当前需求。物料列表、详情及签收选项明确区分试产、量产、共用；缺少或未知范围不可用于实收归属选择。老签收默认用途待核对，只允许原指定接收人补充一次用途，保留原签收人、时间、数量与位置。催办结束前显示当前需求、相关批次合格量、有效预留、线边实收及剩余待收，阶段数量分别展示；后台在事务中重新核对，成功后保存当时的证据。过期、冻结、当前质量不足、归属不明、多段或无关联的独立交接均不能凭文字强行结束。

## 已执行的自动化验证

- 前端普通回归：`npm test -- --exclude src/workflow/acceptanceNavigationHttp.test.tsx`，58文件、603项通过。包含真实WorkflowApp导航、全范围筛选、准确对象动作、需要时间历史、旧版草稿、撤权、切换项目/API后的异步结果隔离；包括收料用途和结束核对的针对性用例。
- 前端构建：`npm run test:bundle`通过，包含TypeScript检查及产物验证。专用HTTP验收不混入缺少宿主环境的普通测试。
- 受控完整流程：`tests/workflow/test_material_resolution_journey.py`，1项通过。通过受权业务API建立确认需求20→发起急料→到货20→IQC接单/正式结果→有效分配→交出20/指定人实收18→寻料找到2仍不可结束→补签2但未关联仍不可结束→独占补收关联→核对结束。急料、待检、未实收分类随后均清零；交接与协调没有改变库存、IQC或预留事实。
- 跨宿主HTTP E30：`WORKFLOW_ACCEPTANCE_CASES=E30 TEST_PLATFORM_SOURCE_ROOT=<现有PF隔离工作树> PYTHONPATH=src <PF虚拟环境python> -m pytest tests/workflow/test_acceptance.py::test_e30 -q`，1项通过。使用真实回环HTTP及现有宿主路由；签收回执修正后重跑仍通过（3.00秒）。
- 后端关联回归：`PYTHONPATH=src /private/tmp/manufacturing-contract-py311/bin/python -m pytest tests/workflow/{test_material_analysis,test_material_control,test_material_handoffs,test_material_tasks,test_expedites,test_expedite_tasks,test_expedite_fulfillment,test_material_resolution_journey,test_supply,test_exchanges}.py -q --tb=short`，196项通过（59.59秒）。覆盖质量修正、有效期、冻结、共享储备、重排、旧需求、幂等/CAS及当前权限等边界。
- 相邻开工/执行回归：同一解释器执行`tests/workflow/test_engineering_readiness.py tests/workflow/test_execution.py`，66项通过（23.94秒），确认批次可用性调整不破坏现有开工和执行路径。

后台、接收用途/结束核对、页面及完整流程均已完成独立任务审查。页面审查发现的超出200条预览的办理选项缺失、签收回执导航问题已先复现再修正，并经复审通过。最终整分支审查通过；审查发现的试产/量产需求不可区分问题已修正，46项相关后台、31项定向页面及603项普通页面回归和构建通过。本地主线合入及原目录复核完成，记录如下。

## 真实源与交付边界

完整流程使用隔离测试项目、受权业务API与明确的MockAuthorityAdapter，未用SQL伪造成功事实。它证明平台功能间的可执行闭环；不等于SAP、MES、IQC、WMS的现场同单闭环。当前已知SAP/MES测试样本的组件和身份不匹配，未强行绑定。真实验收仍需能互相核对的机器人OEM项目、MES工单、SAP工单/工厂、收货批次、检验和发料对象。

本次未变更源系统适配代码，未重复执行源读取或写入源系统；此前真实源联调证据保持各自边界。IQC任务分派在平台内生效，不代表已向外部系统或人员发送通知；原生IQC结果准入、WMS分笔/回执/过账、任意多段物流关系、采购跟进与协调负责人转交仍按任务书接续。浏览器/现场验收待用户执行。仅本地代码合入，不推送、不部署。

## 本地主线复核

功能代码`91012c6`经最终复审通过后，连同验证文档以`d1d2750`快进合入原制造目录的本地main。本段为验证后文档补记，未改变已验功能代码。宿主继续使用既有接口，本次没有宿主代码变更。

在原项目目录重新执行上述10份后台关联测试，196项通过（67.37秒）；普通前端58文件、603项通过（31.90秒），TypeScript、Vite与IIFE/CSS构建检查通过。专用E30通过当前宿主的真实回环HTTP重跑，1项通过（3.21秒）。

原目录与开发工作树产物逐字节一致：`manufacturing.js`727282字节，SHA256`5f68c428a95dfcd07dce3248b6a87351b36e929ad0f7d969411ce8d8e29789d0`；`manufacturing.css`75752字节，SHA256`015fd2b459481a4b175b1d26895ffc8fbf275f4a8e75b290f9e0049bc948dcb5`。

合入前743项原文件预映像全部匹配，新增文件无未跟踪路径冲突；排除本次计划修改的50项文件后，693项未涉及的原文件在合入和验证后逐字节一致。用户原有`.gitignore`、`README.md`、`knowledge/README.md`未提交改动及其他历史资料保留；开发工作树保留。未推送或发布线上环境。
