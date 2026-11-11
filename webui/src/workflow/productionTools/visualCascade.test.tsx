import { readFileSync } from "node:fs";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { createWorkflowApi } from "../api";
import { flush } from "../testHelpers";
import { ProductionToolsWorkspace } from "./ProductionToolsWorkspace";
import { Metric, Panel } from "./visuals";

it("sizes workspace, panels and numbers in a mounted workflow host", async () => {
  // Vitest disables CSS imports, including ?raw: read the actual files explicitly.
  const workflowCss = readFileSync("src/workflow/workflow.css", "utf8");
  const productionCss = readFileSync("src/workflow/productionTools/productionTools.css", "utf8");
  const style = document.createElement("style");
  // jsdom 26 resolves by source order even when specificity differs. Mount the
  // actual files host-first to test computed sizing; host-last is audited separately.
  style.textContent = workflowCss + "\n" + productionCss;
  document.head.append(style);
  const host = document.createElement("div");
  host.className = "mf-root wf-root";
  document.body.append(host);
  const root = createRoot(host);
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ configured: false, capabilities: {} }))));
  const api = createWorkflowApi({ apiBase: "/api/v1/manufacturing", csrfToken: "csrf", readOnly: true });
  try {
    await act(async () => root.render(<div className="mf-console-content"><ProductionToolsWorkspace api={api} readOnly userId="visual-cascade" /><section className="wf-production-tools" data-pt-workspace><Panel title="分析范围"><Metric label="测试记录" value="0" /></Panel></section><h2 className="unrelated">其他模块</h2></div>));
    await flush();
    const workspace = host.querySelector('[aria-label="产测管理工作区"]')!;
    expect(workspace.hasAttribute("data-pt-workspace")).toBe(true);
    expect(getComputedStyle(workspace.querySelector("h2")!).fontSize).toBe("28px");
    expect(getComputedStyle(host.querySelector(".pt-panel h3")!).fontSize).toBe("20px");
    expect(getComputedStyle(host.querySelector(".pt-metric-value")!).fontSize).toBe("32px");
    expect(getComputedStyle(host.querySelector(".unrelated")!).fontSize).toBe("16px");
    expect(workspace.querySelector('nav[aria-label="产测主导航"]')).not.toBeNull();
    expect(workspace.querySelector('[aria-label="数据范围"]')).not.toBeNull();
    expect(workspace.querySelector('[aria-label="调查与查询操作"]')).not.toBeNull();
  } finally {
    await act(async () => root.unmount());
    api.dispose();
    host.remove();
    style.remove();
    vi.unstubAllGlobals();
  }
});
