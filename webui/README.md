# Manufacturing browser library

Install and build independently:

```sh
npm ci
npm test
npm run test:bundle
```

`dist/` contains exactly `manufacturing.js` (IIFE) and `manufacturing.css`.
Load both through the authenticated platform asset routes. React is bundled;
no CDN, HTML entry, API root, or session token is baked into the assets.

```ts
const handle = window.OrbbecManufacturing.mount(element, {
  apiBase: "/api/v1/manufacturing", // same-origin path, including API prefix
  csrfToken: session.csrfToken,
  readOnly: !access.can_edit,
  onAuthError: () => showAccessDenied(),
  onDirtyChange: (dirty) => {
    manufacturingDirty = dirty;
  },
});

handle.isDirty(); // boolean, current draft or pending write
handle.unmount(); // idempotent; cleans effects, reports dirty=false
```

The required mount options remain `apiBase`, `csrfToken`, `readOnly`.
`onAuthError` and `onDirtyChange` are optional. The callback reports the presence
of unsaved record/relationship changes, task input/edits, or an in-flight write.
The platform adapter must consult this callback or `handle.isDirty()` before
replacing the mount point during SPA navigation. When dirty, the adapter should
keep the workbench mounted if the user cancels, and only call `unmount()` after
an explicit discard choice. `unmount()` itself does not prompt or save.
The library handles its own back navigation and installs `beforeunload` only
while dirty; browsers control the wording and conditions for that native prompt.

API reads/writes use `credentials: same-origin`, `cache: no-store` and CSRF header
`X-CSRF-Token` for writes. `apiBase` must be a same-origin path. Auth failures
clear rendered business state and call `onAuthError` once. API/server and mount
read-only flags both disable editing. A hard-stale directory write rejection
retains local drafts and is shown as an unsaved error.

Save uses whole-record CAS. Conflicts preserve local edits until an explicit
reload/discard decision. Task create retries reuse an operation UUID when the
title is unchanged; deliberately changing the failed title starts a new operation.
The page has no external system connector: system rows are relationship
registration and always show `关系登记，尚未验证连接`.

`npm test` uses Vitest/jsdom component and client tests. `test:bundle` additionally
builds and evaluates the emitted IIFE in jsdom without Node globals; this is not
browser automation or a substitute for the user's desktop/mobile page acceptance.

## 项目管理与平台 Markdown 复用

默认页面为工作台、制造项目、事项、系统协同、制造手册；`LegacyWorkflow` 保留旧流程现状参考。独立管理框架由制造应用提供，包括左侧导航、当前位置和右上角账户区；宿主在 Agent AppShell 之外挂载。新 API 类型见 `src/projects/types.ts`，所有请求沿用 `api.ts` 的同源、CSRF、权限失效和生命周期处理。

宿主可传入 `user: {displayName, roleLabel}`、`onNavigatePlatform()` 和异步 `onLogout()`。展示信息只使用实际 Account，账户动作仍由宿主执行原有登录流程。挂载句柄的 `updateUser(user)` 原地更新显示姓名/角色，不销毁项目草稿或 Markdown 根；授权身份、角色或 CSRF 的变化仍由宿主退役旧挂载后重新创建。旧宿主省略新增选项仍可挂载。

返回平台和退出经过制造应用的草稿确认；确认丢弃后先同步脏状态和卸载前保护，再执行账户动作。退出失败留在当前界面显示错误，重复点击不会产生并发退出。句柄卸载后停止展示更新和外部动作。

`mount` 还接收可选 `renderMarkdown(element, { markdown, headingIds? }) => { unmount() }`。现有平台通过 `manufacturingMarkdown.tsx` 注入真实 `ArticleMarkdown`，后者沿用 `MermaidDiagram`。业务包负责章节、位置、元数据和上下文，未包含另一套 Markdown/Mermaid 依赖。原生渲染句柄按调用拥有独立 DOM 子根，替换时立即退役并延迟释放 React 根，避免旧清理删除新内容。

手册正文从授权 API 读取，不复制进前端包；源文件更新需提交并发布制造制品。文档接口返回发布内容 SHA、Git 更新时间和 release；不匹配版本会拒绝，避免将新文档标成旧版本。
