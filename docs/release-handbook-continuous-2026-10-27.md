# 制造手册连续阅读修正

后续已发布[架构产品化 v0.4](release-architecture-product-2026-10-27.md)，当前维护入口与完整 41 项 Compose 链以新记录为准。本文保留手册连续阅读修正的历史事实。

2026-10-27，已发布至[大制造工作台](https://agent.orbbec.com.cn/manufacturing)。手册完整正文一次交给平台原有 Markdown/Mermaid 组件，从头到尾连续阅读；目录和项目的“了解这个阶段”只滚动定位，不截取正文或切换章节。原始手册内容未改动。

目录定位等待原生组件的异步渲染，每次打开使用独立请求标识；切换手册与流程总览分别保留阅读位置，旧阶段定位不会覆盖返回位置，也不会穿透到新的打开请求。文档内部的标题链接保持可用。

## 实际发布版本

| 项目 | 实际值 |
| --- | --- |
| 制造源码 | `161292be7c01038cc7c25b5f36aea04577c19823` |
| 平台源码 | `59f97fee18dd04155810890a7fe930124979e78d` |
| API 镜像标签 | `orbbec-agent-platform:manufacturing-v2-59f97fee-161292be` |
| API 镜像 ID | `sha256:4d98690675b1e8623a04be44f1e950735d05ef69c598bd8f68c02133f20fb381` |
| API 容器 ID | `d6c694ac0c8eb3e33f2e34dc1666e76eb79057c63b406353db18a539e39f9245` |
| 制品 SHA256 | `0eba01430b4574a55e5259149d06ee1c941899d817983ee37630d66d3c11908d` |
| 制造 JS SHA256 | `0adf90b54bec24360827dd8fdd97ef08ae1ede5db405d2b58a39c587dbe13cec` |
| 手册原文 SHA256 | `8966c7d91be4387b67271449d1c25b3214a7587a149c26c40c3a39dd035e2dfd` |
| 当前维护入口 | `/opt/orbbec-agent-platform/staging/manufacturing-handbook-continuous-20261027/future-maintenance.json` |
| 维护清单 SHA256 | `f192c3a409c0b0e4e9e2d82c97bc0be5723be269db0959f8eddb2df28a11418f` |

由已合并主线的准确 Git 提交构建两仓库前端；平台后端增量为零。从原运行镜像 `fcc02c82…` 派生，保留旧补丁与默认配置。本记录为发布后的文档提交，不改变上表实际运行源码。

## 验证与运行维护

- 制造前端 77 项测试通过；新增连续正文、异步阶段定位、文档独立位置、过期定位清理及源行号回归。TypeScript、Vite、IIFE 全局接口和 CSS 约束检查通过，独立代码复审无遗留问题。
- 真实隔离候选通过：实际应用与权限/CSRF 中间件、合成身份、临时 SQLite、另一进程持久化读回、整篇手册及元数据摘要核对；不使用员工 Session，不写入生产业务记录。
- 生产 API healthy、重启 0；完整制造内容树与 manifest 一致，原文摘要保持。公网页面与健康接口 200，匿名手册 API 401 且 `private, no-store`。
- 原有 39 项 Compose 输入保留并追加本次 overlay，维护链现为 40 项。仅替换制造源码只读挂载的版本目录；数据挂载、其他挂载、网络与安全配置保持。其他 29 个容器 ID/镜像不变；未修改或重载 Nginx。
- 切换前 SQLite 一致性备份已核验：`/app/data/manufacturing/backups/837fac5db0a84cd6bf9a054bcbcf7300/workbench.sqlite3`，SHA256 `871ccd9f49825604f620ce73c1da6f317e5d128b3acb9cd7cc23c73e1c827a29`。回滚应用继续保留现有数据库，不回灌旧备份或删除 WAL/SHM。

浏览器实际滚动、视觉与真实账号验收未由 Agent 执行，依平台既有约定由用户完成。正文仍只维护 `docs/manufacturing-system-handbook.md`，提交后重新构建发布；后续发布从上表当前维护入口取得完整基线，不复用旧 39 项维护链。
