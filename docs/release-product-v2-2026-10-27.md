# 大制造工作台产品重构发布记录

2026-10-27，项目管理版已部署到 [大制造工作台](https://agent.orbbec.com.cn/manufacturing)。刷新页面后，以平台 owner/admin 登录。默认首页围绕制造项目和待处理事项组织，S1—S9 进入具体项目内部；手册作为独立知识入口。

## 已上线功能

- 工作台：实际在管项目、受阻项目、近七天到期、未完成事项、待确认与阻塞提示、最近动态；没有项目时提供真实空状态和创建入口。
- 制造项目：新建、编辑、列表/看板、内部/外部与业务线筛选，负责人、交付目标、产品/型号、客户/接收方和计划数量，归档与恢复。
- 项目详情：阶段轨道、阶段开始/受阻/完成/重开、推进记录、参与方、设计/BOM/测试版本等交接资料，以及系统关系。阶段和事项各自维护版本，冲突保留草稿。
- 事项中心：任务、问题和确认事项，负责人、目标日期、优先级和状态；可定位到对应项目/阶段。
- 制造手册：复用平台现有 `ArticleMarkdown` 与 `MermaidDiagram`，支持 GFM 表格、代码高亮和 Mermaid；按章阅读、阶段定位、相关流程文档与工作上下文返回。未另建 Markdown 渲染器。

内部包括自研相机（含数采相机）、3D 打印机；外部为 OEM 代工代料。历史流程现状及任务仍可从“流程现状参考”访问。生产未预填客户、项目、产量、良率或演示业务记录。

本版是制造项目协同。ERP/MRP/MES 当前仍为关系登记，真实接口、库存/财务账、MRP 运算和设备过站未接入；负责人登记不会自动创建外部账号或发送消息。

## 实际发布版本

| 项目 | 实际值 |
| --- | --- |
| 平台增量源码 | `73cde12661dca8f15cff7b57fa8aa2ec4bc8afeb` |
| 制造源码 | `0918bb19054b4f58a1b940b0e36666cdc2910e0c` |
| API 镜像标签 | `orbbec-agent-platform:manufacturing-v2-73cde126-0918bb19` |
| API 镜像 ID | `sha256:fcc02c82050f2fda8628397be02c3c2e1180e0ba779ab0ccbce8a13180c35d6c` |
| API 容器 ID | `06d777fc84ed9e574837f3b6231a07e034bcb1b1f86ca966b973f20cb55eee87` |
| 制品 SHA256 | `deab18162a5e26b6db00b4d4809c30f6838e93d4b833acde45094a5c3306c511` |
| 私有发布目录 | `/opt/orbbec-agent-platform/staging/manufacturing-product-v2-20261027` |
| 当前维护入口 | 上述目录的 `future-maintenance.json`，包含完整有序 39 项 Compose 输入 |
| 维护清单 SHA256 | `62c6662b17eada1ad0e6e07ed0c30121072eb82b9c79522ad79e89a47c2537b7` |

镜像从当时真实运行的 `bce8f412…` 派生，仅 COPY 本次一项后端权限路由文件及干净 Git 源码构建的 66 项平台静态文件；保留其他线上补丁和镜像默认配置。制造源码、业务 JS/CSS、两份文档和元数据位于独立不可变版本目录，只读挂载到 `/opt/manufacturing`。

保留原 38 份 Compose 输入并追加本次 overlay；总挂载仍为 15 项，仅替换制造代码挂载的 source。数据挂载 `/data/orbbec-agent-platform/manufacturing/data` → `/app/data/manufacturing`、原有 13 项其他挂载、网络和安全配置保持。未修改或重载 Nginx，其他 29 个容器的 ID/镜像保持。

## 手册持续维护

正文唯一来源为 `docs/manufacturing-system-handbook.md`。本次包含用户最新配色、图例及 16 个流程/架构图，源文件 SHA256 为 `8966c7d91be4387b67271449d1c25b3214a7587a149c26c40c3a39dd035e2dfd`，Git 更新时间 `2026-10-27T04:37:19+00:00`。已用平台现有严格 Mermaid 配置解析全部图块。

后续修改该 Markdown，检查图表并提交后发布制造制品。`deploy/build_artifact.py` 只导出准确 Git 提交中的正文，生成 UTC Git 更新时间、内容摘要和完整 manifest；工作区未提交草稿不会被静默发布。`deploy/install_payload.py` 校验私有制品和不可变目录，构建 COPY-only 候选；`release.py` 执行 prepare → candidate → cutover。

每次发布须重新取得运行基线和完整维护链。手册单独更新时可以没有后端代码差异：构建器保留空 backend COPY 目录，镜像标签包含平台与制造两份提交，避免重标记旧回滚镜像。这个后续工具修正已独立复审和回归，不改变上表已部署应用版本。

## 验证与范围

| 层次 | 已取得的证据 |
| --- | --- |
| 制造 Python | 发布源码合并后 175 项通过，包括业务包 124 项、发布守卫/构建/安装/备份 51 项 |
| 制造前端 | 72 项通过；TypeScript、Vite、实际 IIFE 全局接口与 CSS 检查通过 |
| 平台后端 | 776 项相关桥接/授权测试通过；合并后真实兄弟源码桥接 102 项通过 |
| 平台前端 | 32 项渲染/生命周期/共享组件测试通过；合并后包装器和最新版手册解析 21 项通过，生产构建通过 |
| 评审 | 域模型、产品交互、平台接入和整体两仓库审查通过；放弃草稿动作、成功写入后刷新失败、并发旧快照覆盖均有已复现的回归测试 |
| 真实隔离候选 | network none、UID10001、只读根；实际 `app.main.create_app` 和真实授权/CSRF 中间件；合成 owner/admin/member 身份；项目创建/幂等/冲突、阶段受阻/完成/重开、确认事项、归档恢复、旧记录保留；另一进程读回同一临时 SQLite |
| 文档与资源 | 两份发布文档正文、更新时间、release 和 SHA 对照元数据；私有 JS/CSS MIME、全字节摘要和版本校验；所有内容树与制品 manifest 一致 |
| 生产 | API healthy、重启次数 0；schema 初始化未创建业务记录；新增 dashboard/projects/project-tasks/handbook 匿名均 401/no-store；公网独立核对 shell200/API401；原 SDK 边界及 Office/FAE 资源摘要保持 |

这些正向身份与业务操作验证使用隔离合成主体和临时数据，没有导出员工 Session 或在生产伪造身份。真实账号完整登录、浏览器视觉/交互验收仍由用户完成；这些证据不等于真实 ERP/MRP/MES 业务验收。

## 备份与回滚

切换前以实际 UID10001 调用 SQLite 在线 backup，涵盖已提交 WAL 内容；备份在数据目录的独立 0700 子目录，文件模式 0600。独立 quick_check 和旧 schema 校验通过，备份大小 32,768 字节。具体私有位置与摘要记在发布目录的 `sqlite-backup.private.json` 和 `cutover.json`。

随后仅初始化新增项目表，保留 `stage_records`、`tasks`、`task_operations`。应用回滚使用旧完整 38 项链和原代码源，保留现有数据库及新增表，不用旧备份覆盖后续真实写入。回滚检查包括完整挂载声明、网络配置、环境和内容；无法确认恢复时保留锁。成功发布后 action/input 锁已释放。

历史只读审计曾因打开 WAL 数据库产生空 WAL/SHM 记账文件，未改变主文件/业务行，未删除侧文件；完整事实保存在私有审计报告。本次正式备份使用正常 WAL 协调，而非把在线主文件单独复制或按 immutable 忽略 WAL。
