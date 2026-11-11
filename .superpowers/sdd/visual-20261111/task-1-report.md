# Task 1 report — shared visual system and workspace hierarchy

Status: DONE. Implementation base `f46d7026e48c747b4c529c9bc73bee32084ca2b2`; code commit `50db3c9` (`feat(production-tools): establish scoped workbench visual foundation`). Code review range: `f46d7026e48c747b4c529c9bc73bee32084ca2b2..50db3c9`. This report follows in a documentation-only commit.

## Scope and result

Owned files only: `ProductionToolsWorkspace.tsx`, `productionTools.css`, new `visuals.tsx`, `visuals.test.tsx`, `visualCascade.test.tsx`, and the explicitly authorized date-only correction in `ProductionToolsWorkspace.test.tsx`. No boards, details, investigations, API, navigation, persistence, source queries or dependencies changed. The task did not run browser automation, external sessions, production writes or deployment.

The workspace now has the `data-pt-workspace` boundary, a 28px page title, a distinct header with an eyebrow and description, grouped board navigation, a compact investigation/query action group, a named range panel with a primary apply action, and a separate named search panel. Existing button textContent, handlers, navigation guards and recovery behavior remain intact.

The shared primitives export the required `Tone`, `Badge`, `Metric`, `Panel`, `ResultBadge`, `EmptyState` and `boundedPercent`. Metrics preserve exact count strings, expose label/value text, differentiate null from zero, keep zero failures neutral, and use native buttons for drills. Result badges recognize only actual source codes 1/2 (numbers or strings); raw PASS/FAIL strings remain visibly unknown under the existing source protocol. `boundedPercent` rejects malformed decimal inputs with RangeError; valid zero denominators return0. It divides exact BigInts to hundredth-percent fixed point and only converts that bounded result to Number. Unknown counts must be filtered by callers before normalization.

The complete scoped foundation establishes neutral canvas/surface/group layers, 20px panel headings, 32px metric values, semantic color roles, readable tables and overflow, focus-visible treatment, form boundaries, section/actions, metadata, facts, empty/alert states, investigation and drawer bases, 760px single-column layouts, and reduced-motion behavior. The main content container is transparent so panels are visually distinct rather than white cards nested inside another white card.

## Red/green evidence and corrections

All npm commands below ran from `/Users/neo/.codex/worktrees/6f75/AI-Manufacturing-Platform/webui`, except the explicitly recorded cwd mistake.

1. First reproduce the baseline date failure:
   `npm test -- src/workflow/productionTools/ProductionToolsWorkspace.test.tsx -t 'expands history independently'`
   Exit1; 1 failed,77 skipped. Assertion at original line1222: expected `原症状命中`, but the live2026-11-11 problem window excluded the static2026-11-10 source fixture. This is the same failure preserved in baseline.md.
2. Pin only that test's Date with `vi.useFakeTimers({toFake:["Date"]})` and existing `now`; restore in finally. No setTimeout/setInterval mocking or product date change. Repeat the exact command: exit0; 1 passed,77 skipped.
3. Write both new presentation test files before `visuals.tsx` exists. Run:
   `npm test -- src/workflow/productionTools/visuals.test.tsx src/workflow/productionTools/visualCascade.test.tsx`
   Exit1; 2 failed suites,0 collected tests, both fail resolving the intentionally absent `./visuals`. This is the first missing-feature evidence, retained rather than replaced by a later green run.
4. After the first implementation, the mounted test exposed test-environment issues: Vite/Vitest CSS and `?raw` CSS imports returned empty strings, producing browser-default1.5em rather than28px. The test now reads both real CSS files with node:fs. An import.meta URL attempt then failed `The URL must be of scheme file` under Vitest; use paths relative to the configured webui cwd. A broad `h3` query subsequently selected the new16px range heading rather than the20px Panel heading; scope the assertion to `.pt-panel h3`. These were test harness corrections, not lowered product expectations.
5. The coordinator clarified the existing result-source protocol and malformed-count behavior. Refine tests first and run:
   `npm test -- src/workflow/productionTools/visuals.test.tsx`
   Exit1; 2 failed,3 passed. Failures correctly identify the initial PASS/FAIL alias inference and malformed counts silently returning0. Remove aliases and throw RangeError for malformed counts. Valid max0 still returns0.
6. Initial `npm run test:bundle` caught a missing required `readOnly` option on the test API fixture: TypeScript TS2345. Add `readOnly:true` to that fixture. No production option change.
7. One command was mistakenly launched from the repository root after writing CSS: npm exit254 ENOENT for root package.json. No tests ran in that invocation. Subsequent commands use webui as required.

## Final verification

After the final CSS boundary-contrast correction and JSX formatting:

- `npm test -- src/workflow/productionTools/visuals.test.tsx src/workflow/productionTools/visualCascade.test.tsx src/workflow/productionTools/ProductionToolsWorkspace.test.tsx src/workflow/productionTools/shell.test.tsx`
  Exit0; **4 files passed,86 tests passed**, duration4.65s, start09:24:48 Asia/Shanghai2026-11-11. Covers exact huge counts, null/zero distinction, accessible/native metric action, source result states, semantic panels, invalid decimal validation, mounted hierarchy, existing workspace workflows and shell entry/exit.
- `npm run test:bundle`
  Exit0; TypeScript and Vite pass,111 modules transformed. CSS54.33kB(gzip9.33kB), JS641.18kB(gzip185.44kB). Bundle checker: `IIFE global and scoped CSS verified without Node globals or browser automation.`
- `git diff --check`
  Exit0; no whitespace errors.

## Cascade evidence and limits

The mounted test injects both actual workflow.css and productionTools.css and renders the actual ProductionToolsWorkspace under `.mf-root.wf-root .mf-console-content`; it also mounts shared Panel/Metric components and an unrelated host heading. Computed sizes are28px page,20px panel,32px value,16px unrelated heading. It verifies the workspace boundary and the named navigation/range/action groups. It does not assert CSS source strings.

The actual build loads productionTools.css before workflow.css. The host title selector `.mf-root.wf-root .mf-console-content :is(h2,h3)` has specificity(0,3,1); the local `.mf-root.wf-root .wf-production-tools[data-pt-workspace] h2` has(0,4,1), and class-specific local panel rules are stronger still. Therefore the local declarations outrank a later host stylesheet under the browser cascade, without !important. Every production CSS rule remains within the mandated root; global navigation and unrelated module headings retain their host styling.

**Known jsdom26 limitation:** a minimal standalone JSDOM using the actual files and a matching h2 returns28px when host CSS is first, but16px when host CSS is last despite the local selector's greater specificity. jsdom is resolving these matches by source order. The mounted test intentionally uses host-first to provide honest computed-sizing coverage; it does not claim to validate the real host-last browser cascade. The coordinator accepted the mounted test plus explicit specificity audit rather than a custom cascade engine or prohibited browser/dependency addition. User browser acceptance remains outstanding and was not claimed.

## Contrast and downstream hooks

The coordinator independently calculated paired contrast ratios: body14.28:1, muted5.35:1, info5.87:1, success5.22:1, warning6.14:1 and danger5.93:1. Form and neutral button boundary color was corrected from the original pale border to `#74839a`,3.85:1 on white; disabled controls are inactive. Decorative panel borders remain subtle. Status text is explicit and status colors have no power to infer missing data as PASS, offline or zero.

Task2/3 consumers should use:

- `pt-metrics` and `Metric`: desktop4 columns, intermediate2,760px single column.
- `pt-panel`, `pt-section-heading`, `pt-panel-body`, `pt-section-description`, `pt-eyebrow` for named analysis/detail sections.
- `pt-badge[data-tone]`, `pt-empty`, `pt-meta` for semantic states and source context.
- `pt-button-primary`/`pt-button-quiet` or `data-variant="primary"/"quiet"` for action hierarchy.
- `pt-chart`/`pt-chart-legend`, `pt-table`, existing facts/table/drawer/investigation bases for specialized surfaces.

Task2/3 CSS must keep the full scoped root specificity, including `[data-pt-workspace]`, to win host rules reliably. Exact source count labels remain caller responsibilities; normalize known complete values only. The fallback `pt-counts strong` is now neutral rather than painting all counts as failures. Task-specific status, row-attention and activity encoding belongs to the following owned tasks.

## Self-review

Reviewed the owned diff and interfaces against the brief: required exports present, no Number conversion of source counts, strict result-source protocol, null/zero preserved, existing labels unchanged, no business/control-flow modifications, no new package, no browser or deployment claim, responsive/focus/motion primitives present. All six code/test files were staged explicitly and committed; no unrelated files were included. Remaining limitation is visual acceptance in a real browser and the already documented jsdom specificity gap, not a passing-test claim about browser rendering.
