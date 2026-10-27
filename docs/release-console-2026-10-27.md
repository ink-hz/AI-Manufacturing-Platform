# 大制造独立管理平台 v0.5 发布记录

2026-10-27，独立管理平台已发布到 [制造入口](https://agent.orbbec.com.cn/manufacturing)。该路由在 Agent AppShell 外呈现自己的业务导航、顶栏和工作区，复用企业登录。当前权限仍为平台 owner/admin。

## 本轮行为

- 左侧为奥比大制造业务导航：工作台、制造项目、事项、系统协同、制造手册，支持收起；事项数量来自实际数据。窄屏使用抽屉导航。
- 顶栏展示当前位置和当前项目；右上角展示真实登录姓名、首字头像与角色，菜单可返回 Agent 平台或退出登录。
- 外部动作先处理未保存草稿；确认丢弃后再同步离开保护并执行。退出失败留在页面提示，防止重复提交；授权失效后旧回调退役。
- 主区展开显示现有项目、阶段、工程资料、生产准备和交接记录，移除 Agent 外壳和旧横向主导航。
- 制造手册仍为整篇连续阅读，复用共享 Markdown/Mermaid；项目草稿、手册返回位置、权限及只读提示保留。

详见[产品设计](manufacturing-workbench-product-design.md)和[独立框架设计](superpowers/specs/2026-10-27-manufacturing-console-design.md)。本轮没有后端业务/API/schema 变更，没有新增 ERP/MRP/MES 连接。

## 实际运行版本

| 项目 | 实际值 |
| --- | --- |
| 制造源码 | `19b58607dc75708999a4706d488eff7b9db96f44` |
| 平台源码 | `22f65f19b5c9ff740c05de5a30ae4f1c5c237ef6` |
| 镜像标签 | `orbbec-agent-platform:manufacturing-v2-22f65f19-19b58607` |
| 镜像 ID | `sha256:3a1b7d5b6e56104240ede3bad045cc11194014726514103c80984e56ff23c42b` |
| API 容器 ID | `4c27bc95174d20ee5d9b1f122589a6256b52ac2833e81788dd808daff9495ec3` |
| 制品 SHA256 | `a1cea91b0136be87a31c63069a3e3116742596f2fd483ed1bbaef53bc0724ca4` |
| 制造 JS SHA256 | `73e85e8f7ab2711ada3851cddff55150c8af1ba1768a989010027962a188b5f3` |
| 制造 CSS SHA256 | `616d19c6122ccc06db1c3e06faea47ea2d25728ebc3c362774a6107bb3d739e1` |
| 手册 SHA256 | `8966c7d91be4387b67271449d1c25b3214a7587a149c26c40c3a39dd035e2dfd` |
| 维护入口 | `/opt/orbbec-agent-platform/staging/manufacturing-standalone-console-20261027/future-maintenance.json` |
| 维护清单 SHA256 | `9849fcb5658218e8dc7f01527b653efa3c3b2d813667ce99883d22f5677db943` |

两仓库评审后快进归并主线，从上述准确提交干净导出、构建。候选镜像在实际旧镜像上仅 COPY 66 项前端静态产物，后端 delta 为 0。部署记录及随后文档提交不改变上表运行源码。

## 验证证据与边界

| 层次 | 结果 |
| --- | --- |
| 合并后制造前端 | 133 项通过、0 失败、0 跳过；涵盖现有业务回归及新账户/草稿/抽屉行为 |
| 合并后平台受影响前端 | 47 项通过、0 失败、0 跳过；包含独立路由、授权、账户更新/退役、真实手册 16 个 Mermaid 图表解析 |
| 制品 | TypeScript/Vite 构建通过；准确导出制品的 IIFE 全局及作用域 CSS 检查通过；完整 manifest/静态摘要匹配 |
| 独立评审 | 任务与整分支评审均通过，无 Critical/Important；记录一项非阻塞改进：补充实际宿主与业务库组合的脏草稿→丢弃→返回平台无二次确认测试，目前由分层测试与调用顺序审查覆盖 |
| 隔离候选 | 实际应用工厂、真实授权/CSRF 中间件、合成身份；network-none、只读根、UID10001、临时 SQLite；项目/版本/回执/准备核对/替代/问题/审计及独立进程读回通过 |
| 回退兼容 | 挂载实际旧 `430fdca3` 不可变源码，只读写临时数据库，随后当前代码读回通过；不挂载生产业务库 |
| 生产检查 | API healthy，重启 0；入口及 health 200，匿名私有制造 API/资源 401 且 no-store；其他入口边界保持 |
| 数据与运行边界 | 切换前后 13 张业务表行数和内容摘要逐表一致；保留 7 个项目，其中 6 个为演示项目；另 29 个容器 ID/镜像及 Nginx 摘要不变 |

平台测试保留既有 Node 26 localStorage 实验性警告，构建保留既有大 chunk 警告，不作为新故障隐藏。原实现者的前置 RED 执行未独立恢复，最终 GREEN、主线复核及候选检查有实际执行证据。本轮未重复无关后端全量套件。浏览器桌面/手机视觉与实际业务角色实操验收由用户完成，尚未执行；候选合成身份不冒充生产员工验收。

## 数据与维护

切换前使用 UID10001 执行 SQLite 在线一致性备份，quick_check 通过：`/app/data/manufacturing/backups/8280b151ad1247acbf34f812a36a90ab/workbench.sqlite3`，987,136 字节，SHA256 `861ac43039e519bcfc408faf7967ae8e6189d626a716dd23d750b2d5ecaeafa3`。没有导入、重建或修改演示/真实业务记录。

完整旧 41 项 Compose 输入追加本轮 overlay，当前 **42 项**；15 项生产挂载及原网络、安全配置保持，只替换制造源码挂载。Nginx 未修改、未重载。回滚使用完整旧链、原镜像与现有业务数据目录，不用旧备份覆盖之后用户写入。后续从本记录维护入口与实际容器状态重新取得基线；发布详细收据在该私有目录的 `candidate-validation.json`、`cutover.json` 和备份记录中。
