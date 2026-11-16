# MES读取失败修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** 真实查询成功时准确呈现工单结果，处理并发过期响应并去除源工作台的错误演示身份。

**Architecture:** 后端保留原并发序列契约；前端对superseded响应仅执行一次缓存GET，所有结果继续按来源/账号/作用域接纳。台账身份与源身份分别渲染。

**Tech Stack:** 现有React19、TypeScript、Vitest；原FastAPI/SQLite与API-only发布。

## Global Constraints

- AGENTS生产只读有效；子代理不得调用源、SSH、Docker或launchctl，运维仅父代理执行。
- 不更改后端序列契约，不自动重复源POST，不轮询；不修改数据集身份或源业务数据。
- 不隐藏真实失败，不接受跨账号/来源/对象异步结果，不展示私有异常或任意message。
- 保留根三个用户修改；真实单据和凭据仅私有600/700；员工浏览器验收不冒充。

### Task 1: 页面读取契约及来源身份

Files: `webui/src/workflow/mesSource/MesSourceWorkbench.tsx`及测试；`webui/src/workflow/WorkflowApp.tsx`、`webui/src/workflow/mesSource/entry.test.tsx`。

Interface: `mesSourceQuery(kind,scope,refresh,signal):Promise<MesObservation>`不变。核心控制为：
```ts
if (value.refresh_error?.code === 'MES_REFRESH_SUPERSEDED') {
  // One cache read; never another source refresh.
  value = accept(await api.mesSourceQuery(kind, scope, false, c.signal));
}
```

- [ ] TDD复现带有效snapshot的superseded响应错误显示；POST后只多一次GET，显示其更新结果或真实错误；缓存仍空时提示更新中。验证源POST不重试及账号/来源切换、卸载和失败缓存保留。
- [ ] TDD验证真实源入口不显示demo总标签，进入正式台账仍显示原dataset身份；零项目路径保持可用。
- [ ] 最小实现，运行`npm test -- src/workflow/mesSource`及相关工作台测试，`npm run build`；独立评审后精确提交。

### Task 2: 真实缓存前端接纳与受控发布

- [ ] 父代理私有保存实际线上缓存和范围状态，用实际React/API消费验证；后端并发用例复核，保留原失败。
- [ ] 分支评审、归并推送；从精确主线构建API-only候选，保全SAP/MES/产测配置及既存Compose/静态/SDK/其他容器/Nginx。
- [ ] 固定37项与OEM候选验收；已有schema30副本初始化保全，零业务行改写；受控切换并核对实际静态字节、服务健康及只读入口，记录员工浏览器未验。
