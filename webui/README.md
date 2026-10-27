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
