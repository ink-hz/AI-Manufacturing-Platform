# AI Manufacturing Platform

OEM 制造数字化平台，面向奥比 OEM 代工制造业务的统筹、需求讨论与系统建设。与 `AI-Agent-Platform` 同级维护，包含 OEM 业务文档体系、工作台软件与制造知识库。**当前业务目标已确认只做 OEM**（2026-11）：按客户提供产品定义、制造方承接制造展开；原自有相机与 3D 打印机业务的软件能力转为复用资产评估。

建议阅读顺序：①[OEM AI 制造平台设计](docs/oem-ai-manufacturing-platform-discussion.md)（完整设计文档：现状、需求、架构、场景）→ ②[OEM 制造数字化系统手册](docs/manufacturing-system-handbook.md)（业务与系统主手册）→ ③[总体架构](docs/manufacturing-platform-architecture.md)与[流程总览](docs/workflows/manufacturing-process-overview.md) → ④[产品设计](docs/manufacturing-workbench-product-design.md)。

## OEM 需求与材料

- [OEM AI 制造平台设计 v1.0](docs/oem-ai-manufacturing-platform-discussion.md)：当前完整设计文档——现状分析（系统格局、物料链路现状、EX001 依据）、需求分析（P01—P15 定位到原始单元格、R01—R13 及验收）、架构设计（平台／现有系统／AI Agent 层、职责三分、身份映射）、五个端到端场景工作流、建设路线与待决策项 D01—D12，全程配彩色流程与架构图。
- 原始材料：《系统能力介绍_20261029_V2 (1).pptx》（IT 系统现状与界面证据）、《奥比中光机器人代工制造方案-CEO汇报(1).pptx》及[文字整理](docs/robot-oem-manufacturing-ceo-presentation.md)（业务方向与建设建议，目标值非承诺）、《OEM业务物料痛点.xlsx》（15 条已报告问题，未经现场复核）。
- [系统资料与权限对接清单](docs/manufacturing-system-information-and-access-request.md)：现状核实所需的资料、账号与接口权限安排。
- [文档修订交接单](docs/oem-handbook-revision-handoff.md)：2026-11-03 本轮联动修订的依据与验收标准。

## 系统手册

[OEM 制造数字化系统手册](docs/manufacturing-system-handbook.md)：供制造负责人及业务、IT 团队理解和统筹 OEM 业务与系统的主手册。第一部分全景（OEM 端到端工作流总图、公司系统现状图〔依据 IT 材料逐页证据〕与候选目标图、系统辞典与逐能力复用判断〔沿用/配置/集成/扩展/新建〕、三条贯穿数据流）；第二部分沿 S1—S9 逐节点展开（每节点：干什么 / 流程图 / 要懂的知识 / 公司现状与痛点〔P01—P15 定位〕/ 涉及系统 / 核心数据 / OEM 合同要点 / 常见断点），重点展开 S3—S6 物料链路；第三部分整体集成（公司对象分工待核实表、已有集成连线与契约、数据/BI/AI、OEM 候选建设路线）。附车间行话、指标口径、工艺环节（含机器人适用模板）三份速查。通识参考、材料所述现状、候选方案与待核实项全书分别标注。

## 架构设计

[OEM 制造系统总体架构设计](docs/manufacturing-platform-architecture.md)：从 OEM 制造业务场景（S1—S9）推导的目标架构，落在公司现状基线上（§1.1），止步于业务语义层。第一部分从五条分化轴推导系统形状：分层与跨界契约、版本中枢（客户版/厂内版映射）、执行核心与过账纪律、实物身份与库存事实、权威与共存（执行能力三分：现有系统沿用/平台缺口/单独论证的改造；§7.5 已有 MES 追溯与平台单台档案关系）、四层数据结构与已有 BI 复用、授权模型、执行事实可信度、智能层、验收分层与失败归因，每张图附可检验的不变式；第二部分沿 S1—S9 展开场景工作流，含试产/返修退货/委外三条支线、OEM 合同与客户差异收敛表、十类角色、断点家族；第三部分是对象目录与四契约、OEM 候选建设批次（零：现状核实 → 一：物料闭环试点 → … → 五：智能层，每批附知识准备表与业务验收判准）及决策点清单。

## 制造业务流程

[OEM 制造业务流程总览 v0.3](docs/workflows/manufacturing-process-overview.md)：OEM 主线的业务流程底稿——业务入口与承诺程度、S1—S9 主流程与交接表、物料链路现状图（按痛点表原生流程形状，含 P01—P15 断点位置）、八类分支的候选走法与核实条件、异常回流表、待核实清单。历史版本（内外部双入口底稿、2026-10-29 软件候选状态）保留日期与性质。

## 产品设计

[OEM 制造业务管理工作台产品设计 v0.8](docs/manufacturing-workbench-product-design.md)：产品目标、角色与模块统一为 OEM；R01—R13 候选需求与实现状态对照表（已实现/待调整/待接入/候选新增）；客户门户、多客户隔离、事务 Agent 的目标与当前实现分开说明。现有已发布软件能力（订单、版本、供应、执行、测试标定、质量、交付、复用资产）保持事实描述。

## 知识库

从[知识库目录](knowledge/README.md)或[知识地图](knowledge/00-learning-map.md)进入。

- 22 篇专题：制造流程、MRP、ERP、工程数据、系统集成、建设与业务验收。
- 134 条术语、50 个接手调研问题，以及系统与数据盘点模板。
- 嘉立创、海尔、三一、施耐德四组案例及 15 项公开披露数据。
- 74 个按 URL 去重的一手来源，保留出处、核验日期和证据范围。

结构化数据包括[内容目录](knowledge/catalog.json)、[术语](knowledge/glossary.json)和[来源索引](knowledge/sources/index.json)。

## 目录

```text
AI-Manufacturing-Platform/
├── README.md
├── 系统能力介绍_20261029_V2 (1).pptx
├── 奥比中光机器人代工制造方案-CEO汇报(1).pptx
├── OEM业务物料痛点.xlsx
├── docs/
│   ├── oem-ai-manufacturing-platform-discussion.md
│   ├── oem-handbook-revision-handoff.md
│   ├── robot-oem-manufacturing-ceo-presentation.md
│   ├── manufacturing-system-information-and-access-request.md
│   ├── manufacturing-workbench-product-design.md
│   ├── manufacturing-platform-architecture.md
│   ├── manufacturing-system-handbook.md
│   └── workflows/
│       └── manufacturing-process-overview.md
└── knowledge/
    ├── 00-learning-map.md
    ├── 01-foundations/
    ├── 02-systems/
    ├── 03-implementation/
    ├── 04-cases/
    ├── 05-fieldwork/
    ├── glossary.md
    ├── glossary.json
    ├── catalog.json
    ├── source-policy.md
    └── sources/
```

知识库于 2026-10-27 从 `AI-Agent-Platform/docs/manufacturing-knowledge/` 完整迁入，保留全部文章、来源记录和结构化数据。

## 工作台开发与发布

`src/manufacturing_platform/` 提供持久化业务 API，`webui/` 提供独立管理框架与 React 资源；Agent 平台负责企业登录、权限和资源生命周期，在自身 AppShell 之外挂载制造平台。当前开放平台 owner/admin，使用 SQLite 独立持久存储。软件实现含相机、3D 打印机和 OEM 业务线对象（历史实现事实，发布记录保留）；业务目标已统一为 OEM，既有能力按复用资产评估（见产品设计 v0.8 的 R01—R13 状态表），业务线对象的调整与数据迁移属后续代码工作。

项目支持列表/看板、交付目标、阶段推进和事项；工程资料包按版本核对与修订，交接有独立回执，生产准备可逐项核对并创建关联问题。“系统协同”明确系统/载体、数据归属和未完成交接；首页显示真实缺项待办。手册复用平台 Markdown/Mermaid 整篇连续阅读，旧流程现状保留为参考。平台人工核对与外部正式批准分开；真实 ERP/MRP/MES 接口需按厂商资料、契约和数据责任逐条接入。

前端构建和嵌入接口见 [webui/README.md](webui/README.md)。生产约束见 [部署审计](docs/deployment-audit.md)；`deploy/release.py` 按 `prepare → candidate → cutover` 执行，仅更新现有 API，保留完整旧 Compose 链。当前版本与 42 项维护链见 [独立管理平台发布记录](docs/release-console-2026-10-27.md)；[架构产品化](docs/release-architecture-product-2026-10-27.md)、[手册连续阅读](docs/release-handbook-continuous-2026-10-27.md)、[产品重构](docs/release-product-v2-2026-10-27.md)和[首版](docs/release-2026-10-27.md)记录保留历史。

线上入口：[大制造工作台](https://agent.orbbec.com.cn/manufacturing)（初始开放平台 owner/admin）。
