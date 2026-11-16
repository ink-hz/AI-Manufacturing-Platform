# 线上功能实测与产测空历史修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** 修复已复现的产测空历史503，并用逐功能结果替代“候选通过即全部可用”的交付判断。

**Architecture:** 保留现有路由、授权、SQL及读取边界。QuestDB固定单项目MAX查询真实返回零行时，沿用既有`latest_at: null`空历史契约；异常、格式不符、多行和读取失败继续报错。真实身份/源读取、隔离业务写入、组件测试分别统计。

**Tech Stack:** 现有Python/FastAPI/SQLite/QuestDB与React/Vitest，无新依赖。

## Global Constraints

- MES/WMS、SAP/MRP生产只读；不写源业务、不创建正式项目/工单来验收；平台观察缓存可按已有授权刷新。
- 源凭据、单据、原回包、失败批次和临时身份仅留私有700/600目录。员工浏览器验收按仓库规则由用户完成。
- 保留MF05d640d0已上线Logo、MES近期/所属组件修复；宿主按实际在线版本核对，不夹带其他会话变更。
- 原始失败必须保留。HTTP200还要核对业务错误、snapshot、完整性与来源，不将缓存GET冒充实时读取。
- 根三个用户修改不动；当前已复用干净链接工作树，分支`codex/real-function-audit-20261116`，基线d677a00。

### Task 1: 空历史契约修复

Files: `src/manufacturing_platform/production_tools/analytics.py`，`tests/production_tools/test_analytics.py`，`tests/production_tools/test_analytics_api.py`。

- [x] 先运行现有analytics相关测试得到基线；让Reader对无输入的单项目MAX真实返回`[]`，运行既有空历史HTTP用例，确认原代码返回503而非200。
- [x] 增加单项目空历史API断言：200、`latest_at is None`、既有source/captured_at和no-store保留；确认过量行、错误字段、坏时间与传输异常仍拒绝。
- [x] 在`_latest`移除“非batch必须恰好一行”的假设；`_read`仍限制最多一行，逐行字段/时间校验保持。返回空映射由既有`.get(project_id)`投影为None。不得用捕获异常返回None。
- [x] 运行`PYTHONPATH=src python3.11 -m pytest tests/production_tools -q`及相关工作流回归；保留红绿结果并独立评审。

### Task 2: 前端测试旅程校正

Files: `webui/src/workflow/navigation.test.tsx`，`webui/src/workflow/materialHandoffHttp.test.tsx`（以实际文件名为准）。

- [x] 将3项旧入口预期对齐既有源浏览设计：管理员首页无本地demo badge；计划物料下先展开“平台正式台账”再进入物料交接。不删除原有筛选返回及切换后的断言。
- [x] 复测完整后半旅程；全前端重新统计通过/失败/跳过。E30/E33只在其隔离真实HTTP验收环境运行，缺环境明确列未执行。

### Task 3: 逐功能实测与交付

Files: 私有`.superpowers/platform-live-audit-20261116/`探针与证据，`docs/reviews/2026-11-16-real-function-audit.md`。

- [x] 线上已完成48个真实部署handler读取、MES四类实时刷新、17个产测项目当日overview、空项目summary；记录临时身份/进程内HTTP边界，保留availability503原始证据。
- [x] 用已有真实SAP测试证据选取精确工单/物料/工厂，在当前S4D300只读接入复核两项产品查询；没有真实对象的功能标为未验证，不编造编号。
- [x] 核对产测七种分析、目录/记录/统计/既有证据与当前前端请求契约；每类首错保留，缺对象/历史的条件旅程明确标记。
- [x] 后台全量隔离回归、受控37+OEM候选，修复后定向复核同一线上失败项目；发布时保全现有数据、共享宿主/Nginx/其他容器。
- [x] 交付清单逐项列通过/失败/未执行，分别报告版本、源环境、临时测试身份与员工登录差异、浏览器未验收范围；不再声称“全量真实闭环已通过”。

### Task 4: 源检出验收的完整静态工件绑定

Files: `tests/workflow/scenarios/provenance.py`。

- [x] 保留已复现的4项D3/重启测试红灯：配置有效宿主后报`Private PF release differs from bound source: webui/dist/master-logo-v2.png`。生产构建及candidate pin已含PNG，仅live_git来源清单仍只登记JS/CSS。
- [x] 在`source_manifest`的固定build文件元组中加入`webui/dist/master-logo-v2.png`与`webui/dist/app-icon-v2.png`，继续以真实字节哈希绑定，不采用通配符、不删除D3制品校验。
- [x] 使用完整隔离宿主环境定向重跑原4项及22项原环境失败所在的5文件；随后固定Linux候选执行包含E30/E33的37项，明确普通pytest条件跳过和候选实际执行的差别。

2026-11-16：本轮审计及空历史修复已发布fc6cc8bf，并完成原对象200/null与有历史对照复验。以上勾选表示本计划的排障/验证动作完成，不表示日志404、真实WMS、跨系统身份关联及真实员工闭环已完成；未验收范围见[逐功能记录](../../reviews/2026-11-16-real-function-audit.md)。
