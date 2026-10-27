# AI Manufacturing Platform

大制造智能平台，面向制造业务的信息化与智能化工作。与 `AI-Agent-Platform` 同级维护，包含制造项目协同、事项管理、系统手册和制造知识库。

## 产品设计

[大制造工作台产品设计 v0.4](docs/manufacturing-workbench-product-design.md)：以工作台、制造项目、事项和制造手册组织产品。围绕具体项目推进阶段、协调问题与确认事项，S1—S9 作为项目内部模板。

## 系统手册

[大制造数字化系统手册](docs/manufacturing-system-handbook.md)：以制造工作流为主线的翻查手册。第一部分全景（端到端工作流总图、工厂系统分层架构图、系统缩写辞典、三条贯穿数据流）；第二部分沿 S1—S9 逐节点展开（每节点：干什么 / 节点流程图 / 要懂的知识 / 涉及系统 / 核心数据 / 自有产品与 OEM 差异 / 常见断点），节点编号与制造流程底稿一致；第三部分整体集成（数据权威与接口清单、数字化平台与 AI 架构、建设次序）。全书 16 张架构与流程图，附车间行话速查。

## 制造业务流程

[内部业务与外部 OEM 制造流程总览](docs/workflows/manufacturing-process-overview.md)：按内部相机（含数采相机）、3D 打印机和外部 OEM 代工代料业务线，梳理共用制造管理主流程及工程、供料、测试和交付差异。当前为待结合实际业务记录核对的工作底稿。

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
├── docs/
│   ├── manufacturing-workbench-product-design.md
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

`src/manufacturing_platform/` 提供持久化业务 API，`webui/` 提供独立 React 资源；现有 Agent 平台负责登录、权限、导航和页面外壳。当前开放平台 owner/admin，支持相机、3D 打印机和 OEM 业务线，使用 SQLite 独立持久存储。

项目支持列表/看板、交付目标、阶段推进和事项；工程资料包按版本核对与修订，交接有独立回执，生产准备可逐项核对并创建关联问题。“系统协同”明确系统/载体、数据归属和未完成交接；首页显示真实缺项待办。手册复用平台 Markdown/Mermaid 整篇连续阅读，旧流程现状保留为参考。平台人工核对与外部正式批准分开；真实 ERP/MRP/MES 接口需按厂商资料、契约和数据责任逐条接入。

前端构建和嵌入接口见 [webui/README.md](webui/README.md)。生产约束见 [部署审计](docs/deployment-audit.md)；`deploy/release.py` 按 `prepare → candidate → cutover` 执行，仅更新现有 API，保留完整旧 Compose 链。当前版本与 41 项维护链见 [架构产品化发布记录](docs/release-architecture-product-2026-10-27.md)；[手册连续阅读](docs/release-handbook-continuous-2026-10-27.md)、[产品重构](docs/release-product-v2-2026-10-27.md)和[首版](docs/release-2026-10-27.md)记录保留历史。

线上入口：[大制造工作台](https://agent.orbbec.com.cn/manufacturing)（初始开放平台 owner/admin）。
