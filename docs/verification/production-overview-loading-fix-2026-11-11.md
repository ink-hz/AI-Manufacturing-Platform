# 项目总览持续加载修复验证

应用源码 `43a893ddbda1e30f2fd50e4b0f70888d6371fffc`，修复前基线 `628c274`、实际运行应用 `53958c7`。用户反馈点击项目总览后持续加载。

## 原因与修复

首次总览使用实时读取身份，点击当前项目总览后切换为固定问题范围，但起止时间保持不变。OverviewBoard的读取身份因此从live变为精确结束时间；共用useRead重新生成身份key，而请求effect只依赖查询参数，遗漏身份key。effect没有重启，返回值一直落入身份不匹配的loading分支，即使旧请求完成也不能结束加载。

在useRead的effect依赖中加入已memo的身份key，使身份变化同时取消旧读取并启动新读取。相同身份的重复点击不产生多余请求。没有通过改变按钮行为、自动重试或延长超时掩盖问题，也未改变查询参数、时间边界、授权、来源、持久化或界面内容。

## 复现与证据

- 实际ProductionToolsWorkspace路径：首次显示总览→点击当前项目总览。修复前期望第二次读取、实际仍只有一次，失败复现。
- 共用hook路径：相同查询参数下live→fixed身份变化，旧请求仍在进行。修复前没有替换请求，第二个用例同样失败。
- 修复后验证新请求成功后退出加载、再次点击同一入口不重复读取；旧请求被取消，其迟到结果不能覆盖当前内容。
- RED：`npm test -- src/workflow/productionTools/readLifecycle.test.tsx src/workflow/productionTools/ProductionToolsWorkspace.test.tsx -t 'logical identity|initial project overview'`，2项按预期失败。
- GREEN：`npm test -- src/workflow/productionTools src/workflow/navigation.test.tsx src/workflow/api.test.ts src/api.test.ts`，15文件206项通过；TypeScript/Vite118模块/IIFE/局部CSS检查通过，输出无警告。
- 独立审查确认memo身份稳定、没有新增effect循环，取消及迟到响应保护成立，ReadyToMerge: Yes；没有重复运行已通过套件。

没有修改后台、21条路由、调查控制器、依赖或发布工具。源、项目、过滤与快照身份保持；原目录五份并行未提交修改和未跟踪材料不包含在制品中。浏览器自动化和真实员工登录仍按既有约定不由Agent执行；组件复现不能冒充浏览器验收。

## 发布及并行宿主变更复核

应用提交43a893d已切换上线，本次目标镜像实际36/36候选通过，0失败/跳过，含实际React E30/OEM。证据归档24,727文件，SHA256 `2a80696d582ad17771fe1d7ff58edf365dc15382d74eb21bf65813c44310869b`，服务器及本地逐项校验。

本次切换与初次数据/配置保全完成后，另一工程资料平台发布将PF从f8f36259升级为d32a3b1b，但保留本次MF提交。原final-runtime检查因目标镜像改变失败，旧PF静态清单的工作站核验因新资产键缺失失败，首次输出保留。没有覆写旧收据或回退并行发布；采用新的只读验证锁定当前宿主，明确区分验证范围。

当前API `63f378f9f7a2c6596683da9ff2927607afb6235428372a8020816407a2c116f0` / `sha256:f1d1058feb71cbaf5d5e344f26dca2edc23273c0c60ec1e7e74878460a97fb7e`，PF `d32a3b1bed8e480ba16ed02653d65d9c9e4a3e52`，MF `43a893ddbda1e30f2fd50e4b0f70888d6371fffc`，18:07健康、重启0。当前69项完整链以前68项为前缀；MF只读挂载及144文件与本次准确Git制品逐项一致，JS/CSS完整字节核验通过。当前宿主另经原生源15项目/七类分析/27固定SELECT、普通角色源I/O前拒绝/只读管理员允许、21匿名401/no-store、配置处理器、公开壳及引用资源和公网HTTPS健康200核验。没有员工会话或源业务写入；SDK、原生私有配置、其他34容器及Nginx配置保持，API错误标记0。

当前宿主验证不声称已运行新PF镜像的完整36候选；完整候选对应本次切换镜像。维护时须使用当前69项链与工程资料发布transaction，不能仅凭本次68项MF清单重建。[上线记录](../release-production-overview-loading-fix-2026-11-11.md)保留两次运行身份和最新维护位置。
