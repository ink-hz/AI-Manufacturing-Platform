# 大制造信息化知识库

面向刚开始负责制造信息化的读者，整理制造业务、信息系统、建设方法与企业案例。先建立内容充分、来源可追溯的资料库，再根据实际工作提炼学习重点。初版整理于 2026-10-27。

本版包括 **22 篇专题、知识地图、134 条术语和 74 个按 URL 去重的一手来源**。另附访谈、数据盘点、已采购 MRP 核查模板，以及案例披露数字对照。资料是通用知识和公开研究，不代表公司现状；教学数据与企业披露数据分别标注。

## 从这里进入

- [知识地图](00-learning-map.md)：把需求、工程、物料、生产、质量与交付串起来。
- [术语表](glossary.md)：按业务模式、计划、工程、质量和系统分类查阅。
- [来源索引](sources/README.md)：回到官方文档、原始披露和行业资料。
- [知识来源与维护规则](source-policy.md)：理解事实、分析、教学假设和公司专属知识的区别。

## 制造与计划基础

| 专题 | 主要内容 |
| --- | --- |
| [制造过程](01-foundations/01-manufacturing-process.md) | 离散与流程制造、NPI、工程发布、备料、加工装配、测试标定、出货与返修 |
| [计划与控制](01-foundations/02-planning-and-control.md) | MTS/MTO/ATO/ETO、S&OP、MPS、MRP、能力计划与 APS 的关系 |
| [MRP 逐期演算](01-foundations/03-mrp-worked-example.md) | 六周、多层 BOM、共享组件、库存与预计接收、净需求、提前期及逾期例外 |
| [ERP 业务交易](01-foundations/04-erp-business-transactions.md) | 订单到回款、采购到付款、计划到生产、库存状态与核算关系 |
| [主数据与工程变更](01-foundations/05-master-data-and-engineering-change.md) | 编码、单位、EBOM/MBOM/BOP、路线、替代、生效条件与实际制造配置 |

## 系统全景与集成

| 专题 | 主要内容 |
| --- | --- |
| [系统全景](02-systems/01-system-landscape.md) | ERP、MRP、PLM、MES/MOM、APS、WMS、SRM、QMS、SCADA、IIoT 与 BI |
| [流程与系统边界](02-systems/02-process-and-system-boundaries.md) | 一笔订单跨系统流转、字段维护职责、库存状态、重复记账与跨系统核对 |
| [集成与数字主线](02-systems/03-integration-and-digital-thread.md) | 标识与版本、API/事件/批量/CDC、幂等、顺序、单位、对账、离线与 IT/OT |

## 建设与业务验收

| 专题 | 主要内容 |
| --- | --- |
| [现状评估与建设路线](03-implementation/01-assessment-and-roadmap.md) | 业务问题、流程、主数据、已有系统、试点、迁移、切换与验收 |
| [指标与业务验收](03-implementation/02-metrics-and-business-acceptance.md) | OTD/OTIF、一次通过率、OEE、库存准确率与周转、明确分母的教学计算 |
| [AI 在制造中的位置](03-implementation/03-ai-in-manufacturing.md) | 知识、分析、事务 Agent 与工业控制的区别；权限、版本、回执与完整任务评价 |

## 企业案例与披露数据

| 专题 | 主要内容 |
| --- | --- |
| [嘉立创](04-cases/01-jlc-electronics-platform.md) | 集团及平台身份、EDA/DFM、PCB/PCBA 订单、BOM 与备料、历史生产组织披露、开放平台 |
| [海尔郑州热水器工厂](04-cases/02-haier-connected-factory.md) | 大规模定制、供应商协同、工厂与平台边界 |
| [三一北京桩机工厂](04-cases/03-sany-heavy-industry.md) | 重型离散制造、焊接、物料与搬运、设备能力和制造运营协同 |
| [施耐德 Le Vaudreuil](04-cases/04-schneider-lighthouse.md) | 既有设备采集、IT/OT、工厂运营与能源管理 |
| [案例比较与迁移](04-cases/05-comparison-and-transfer.md) | 比较业务模式、工程复杂度、数据条件和可迁移机制 |
| [原始披露数字对照](04-cases/06-reported-metrics-and-evidence.md) | 保留发布者、时间、原指标与未披露口径，呈现冲突数字及解释边界 |

## 接手工作与现场调研

| 专题 | 主要内容 |
| --- | --- |
| [访谈与现场观察](05-fieldwork/01-takeover-interviews.md) | 12 类访谈对象、50 个问题及调研交付物 |
| [系统与数据盘点模板](05-fieldwork/02-data-and-system-inventory.md) | 系统、业务对象、字段、接口、问题与抽样台账 |
| [已采购 MRP 核查](05-fieldwork/03-purchased-mrp-review.md) | 产品身份、合同/上线/使用范围、计算输入、四类样本与结果排查 |
| [质量 精益与测试数据](05-fieldwork/04-quality-lean-and-test-data.md) | 规格与过程、Cp/Cpk、抽样、质量工具、电子装联、测试记录与价值流 |
| [标准与资料阅读指南](05-fieldwork/05-standards-and-reading-guide.md) | 中国场景与成熟度资料、体系架构、质量与精益的一手阅读入口 |

## 内容与来源数据

[catalog.json](catalog.json)列出文章标题、主题、关键词和关联来源；[glossary.json](glossary.json)提供术语结构化数据；[sources/index.json](sources/index.json)按 URL 合并来源并保留编号别名。原始来源记录按[基础](sources/foundations.json)、[系统与建设](sources/systems.json)、[案例](sources/cases.json)、[调研与补充阅读](sources/research.json)保存。当前共 76 条专题来源记录，对应 74 个不同 URL。

这些文件便于后续整理、检索与接入工作台，目前是内容数据，不包含已运行的搜索或 RAG 服务。平台页面与生产服务没有因本资料库而改变。

## 公司专属部分的下一份输入

用户已提及 IT 部采购过 MRP 相关系统。后续需要确认产品名、厂商、版本、模块与使用范围，再结合一笔真实业务整理本公司的操作、流程与接口知识。组织职责、实际产线与系统现状仍需[现场调研](05-fieldwork/01-takeover-interviews.md)，不由行业案例推定。
