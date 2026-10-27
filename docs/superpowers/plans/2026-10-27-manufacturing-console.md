# Manufacturing Management Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the authorized `/manufacturing` entry a full-page management console with a business sidebar and actual account menu.

**Architecture:** The platform routes manufacturing outside AppShell and supplies actual account display information and authenticated actions. The manufacturing library owns console layout/navigation and preserves all existing business views and dirty-draft lifecycle.

**Tech Stack:** Existing React 19, TypeScript, Vite, Vitest/jsdom; no added dependencies.

## Global Constraints

- `/manufacturing` renders outside Agent AppShell, without the Agent header, sidebar, footer or panorama frame.
- Preserve all current business APIs, database records, CAS, authorization, read-only behavior and demo data.
- Preserve the continuous handbook and reuse the shared Markdown/Mermaid renderer; do not edit handbook source.
- Actual account information comes from Account. No invented users, notification counts, connector success or unimplemented settings.
- Account display updates must preserve drafts and Markdown ownership. Both external actions must honor the draft guard without a second confirmation after discard.
- No new dependencies, no Nginx changes, no employee session extraction, and no agent browser automation.
- Use the two isolated worktrees only. Preserve unrelated user files in canonical checkouts.

---

### Task 1: Implement and verify the standalone console across the host/library boundary

**Files:**
- Modify manufacturing `webui/src/App.tsx`, `types.ts`, `index.tsx`, `App.test.tsx`, `index.test.tsx`.
- Create manufacturing `webui/src/console/ConsoleShell.tsx`, `console.css`, and focused component tests as needed.
- Modify platform `webui/src/App.tsx`, `pages/ManufacturingPage.tsx`, its tests; create focused `App.manufacturing.test.tsx` and host CSS if needed.
- Update the existing product-design doc to describe the implemented console; do not rewrite the handbook.

**Interfaces:**
```ts
export interface WorkbenchUser { displayName: string; roleLabel: string }
// All three extensions optional for compatibility with the previous host.
interface ConsoleOptions {
  user?: WorkbenchUser;
  onNavigatePlatform?: () => void;
  onLogout?: () => Promise<void>;
}
interface MountedConsole {
  unmount(): void;
  isDirty(): boolean;
  updateUser?(user: WorkbenchUser): void;
}
```
The platform passes names/role labels from the current Account. `onLogout` calls existing `logoutAccount(csrf_token)` and follows the existing login redirect only on success; `onNavigatePlatform` returns to `platformPath('/')` through the existing router. Manufacture resolves dirty confirmation before either callback. Metadata changes use `updateUser` without remounting. Authorization changes retain the existing retirement/remount rules.

- [ ] **Step 1: Write failing behavior tests and run them.** Add a real App route test with mocked page bodies/auth boundaries, asserting the authorized manufacturing route renders its page but has no `.platform-shell`, `.topbar`, or Agent navigation. Add real manufacturing component tests verifying actual account label, a working menu, sidebar navigation and external-action guard. Extend mount tests so `updateUser` changes display while a dirty project form persists. Tests must assert user-observable results, not merely callback presence.

```tsx
expect(box.querySelector('.platform-shell')).toBeNull();
expect(box.textContent).toContain('测试制造经理');
expect(box.querySelector('nav[aria-label="制造工作区"]')).not.toBeNull();
// Click account menu, then return while a draft is dirty.
expect(onNavigatePlatform).not.toHaveBeenCalled();
// Click “放弃并离开”; flush React effects.
expect(onNavigatePlatform).toHaveBeenCalledTimes(1);
```

Run `npm test --prefix webui -- src/App.test.tsx src/index.test.tsx` in the manufacturing worktree and the corresponding focused tests in the platform worktree; record expected missing-feature failures before production edits.

- [ ] **Step 2: Implement the integration.** Extract the console chrome from the large App into a focused component. Feed it current view/project state and call existing `go`, new-project and handbook functions; remove old horizontal navigation and hero. Build scoped CSS for a 232px sidebar, 64px sticky topbar, expanded content, keyboard-operable menu and mobile drawer. Use inline SVG icons (existing dependencies only), true data for any badges, and no fake controls. Return platform/menu callbacks resolve after guard/effect cleanup, handle async logout failure and reject repeated submission. Keep auth-denied output private-data-free.

```tsx
// A dedicated route branch follows existing account/failure/permission checks.
if (route.name === 'manufacturing') {
  if (!routeAllowed) return <AccessState title="无权访问" description="该页面不在你的后端授权范围内。" />;
  return <>{account && <AccessEventReporter account={account} route={route} />}{productPage(route, account ?? undefined)}</>;
}
```

Within the library mount implementation, render the same App/root on `updateUser`, retaining stable lifecycle wrappers; retire updates after unmount. In the host, keep account display data current through refs plus the mounted handle, including data changing while private assets load. Do not make display-name changes re-own Markdown or clear drafts. Reuse the pre-existing script/CSS version cache and auth lifecycle unchanged.

- [ ] **Step 3: Run focused and existing affected tests.** Run `npm test --prefix webui` and `npm run test:bundle --prefix webui` in manufacturing; run platform ManufacturingPage, ManufacturingNavigation, manufacturingHandbook, new manufacturing App tests and App.documentTitle tests, then `npm run build --prefix webui`. Preserve the existing 127 manufacturing frontend regressions. Investigate any failures from a minimal reproduction; do not weaken assertions to obtain a pass.
- [ ] **Step 4: Self-review and commit.** Check scoped CSS at desktop/mobile breakpoints by source, landmark/focus semantics, menu cleanup, async callback retirement, dirty confirmation, whole-handbook preservation and authorization changes. Commit only explicit files in each isolated worktree. Write the complete report to the supplied report path, with exact commands, pass/fail counts, commits and remaining limitations.
- [ ] **Step 5: Independent review.** Controller generates diff packages for both repositories from their recorded base commits. A fresh reviewer assesses specification and quality without rerunning passed suites. Resolve Important/Critical findings with focused failing tests and a fix report, then re-review.

### Task 2: Integrate and deploy the reviewed console

**Files:** Existing `deploy/build_artifact.py`, `install_payload.py`, `release.py`, deployment documentation and both READMEs.

**Interfaces:** Task 1 produces reviewed frontend commits in the two worktrees. Existing release tooling consumes exact merged manufacturing/main and platform/master source SHAs, a freshly verified production baseline and the current ordered Compose chain.

- [ ] **Step 1:** Complete final whole-branch review, recheck both canonical main branches and user changes, and merge only reviewed commits without resets.
- [ ] **Step 2:** Read current running image/source commits/Compose chain/current maintenance manifest and compare with prior baseline. Export exact merged commits with `deploy/build_artifact.py`, with `approved_backend_files: []` since this task changes frontend only.
- [ ] **Step 3:** Install into a new private staging directory, run existing `prepare` then isolated `candidate`; preserve actual live DB and demo data. On passing candidate, run authorized `cutover` with the existing backup and rollback procedure. Never mutate Nginx.
- [ ] **Step 4:** Check actual image/source and asset hashes, health, unauthenticated private API rejection, independent public entry, existing manufacturing record counts and other container IDs. Record evidence in release docs; do not claim user browser acceptance.
- [ ] **Step 5:** Commit release records, push authorized platform master, remove only this task's clean merged worktrees after inspecting unique commits and untracked files. Final response links the entry and succinctly describes the new management layout and outstanding user visual acceptance.
