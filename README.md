# AI Manufacturing Platform

大制造智能平台，面向制造业务的信息化与智能化工作。与 `AI-Agent-Platform` 同级维护，当前从制造知识库开始积累业务、系统、建设方法和行业案例。

## 产品设计

[大制造工作台产品设计 v0.2](docs/manufacturing-workbench-product-design.md)：首版聚焦流程总览与环节工作区，完成「选择业务 → 选择环节 → 记录现状和待办 → 保存 → 继续工作」的使用闭环。

## 系统手册

[大制造数字化系统手册](docs/manufacturing-system-handbook.md)：以五阶段学习路线（入门 → 看懂业务 → 看懂系统 → 会建设 → 精通）为主干的学习与工作手册，每个主题链回知识库详文，并给出各阶段的过关判据与精通验收表。

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

知识库于 2026-10-27 从 `AI-Agent-Platform/docs/manufacturing-knowledge/` 完整迁入，保留全部文章、来源记录和结构化数据。当前为知识整理阶段，尚未接入平台页面或业务系统。
