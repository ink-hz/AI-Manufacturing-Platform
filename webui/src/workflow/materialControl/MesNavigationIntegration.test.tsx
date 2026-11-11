// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { MesOrderMaterials } from "./MesOrderMaterials";
import { MaterialControlWorkspace } from "./MaterialControlWorkspace";
import { project as base, workflowView } from "../testHelpers";

const project = { id: "p", version: 3, allowed_actions: [] };
const requirement = {
  id: "r", material_id: "齿轮", work_order_id: "w", unit: "EA",
  required: "1", receipt_ids: [], handoff_ids: [], expedite_ids: [],
};
const result = {
  project_id: "p", project_version: 4, object_type: "work_order",
  object_id: "w", operation_id: "op", replayed: false,
};
function api() {
  return {
    objects: vi.fn().mockResolvedValue({ items: [{ id: "w", title: "工单" }], total: 1 }),
    mesOrderMaterials: vi.fn().mockResolvedValue({ work_order_id: "w", can_manage: true, binding: null, snapshot: null }),
    materialProject: vi.fn().mockResolvedValue({ requirements: [requirement], work_orders: [{ id: "w", title: "工单" }], total: 1, receipts: [], handoffs: [], expedites: [], source_modes: [] }),
  };
}
async function select(host: HTMLElement, value = "w") {
  await act(async () => {
    const s = host.querySelector('[aria-label="平台工单"]') as HTMLSelectElement;
    s.value = value;
    s.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
async function edit(host: HTMLElement) {
  await act(async () => {
    const e = host.querySelector('[aria-label="MES工单号"]')!;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(e, "DRAFT");
    e.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
it("temporary readOnly preserves an unsaved MES draft after cancel", async () => {
  const host = document.createElement("div"), root = createRoot(host);
  const p = { api: api(), project, readOnly: false, onDirty: vi.fn(), onChanged: vi.fn() };
  try {
    await act(async () => root.render(<MesOrderMaterials p={p as any} leave={f => f()} />));
    await select(host);
    await edit(host);
    await act(async () => root.render(<MesOrderMaterials p={{ ...p, readOnly: true } as any} leave={f => f()} />));
    await act(async () => root.render(<MesOrderMaterials p={p as any} leave={f => f()} />));
    expect((host.querySelector("input") as HTMLInputElement).value).toBe("DRAFT");
  } finally { await act(async () => root.unmount()); }
});
it("confirmed local requirement navigation clears discarded MES fields", async () => {
  const host = document.createElement("div"), root = createRoot(host);
  const dirty: Record<string, boolean> = {};
  let pending: (() => void) | undefined;
  const leave = (f: () => void) => { if (Object.values(dirty).some(Boolean)) pending = f; else f(); };
  const p = { api: api(), project, readOnly: false, onDirty: (k: string, v: boolean) => { dirty[k] = v; }, onChanged: vi.fn(), onOpen: vi.fn(), requestLeave: leave, requestLocalLeave: leave };
  try {
    await act(async () => root.render(<MaterialControlWorkspace {...p as any} />));
    await select(host);
    await edit(host);
    await act(async () => [...host.querySelectorAll("button")].find(b => b.textContent === "齿轮")!.click());
    expect(pending).toBeTruthy();
    expect((host.querySelector('[aria-label="MES工单号"]') as HTMLInputElement).value).toBe("DRAFT");
    await act(async () => { for (const k in dirty) delete dirty[k]; pending!(); });
    expect((host.querySelector('[aria-label="MES工单号"]') as HTMLInputElement).value).toBe("");
    expect((host.querySelector('[aria-label="平台工单"]') as HTMLSelectElement).value).toBe("w");
    expect(dirty["MES工单关联"]).toBe(false);
  } finally { await act(async () => root.unmount()); }
});
it("acknowledges a successful refresh after selection changes without replacing the new view", async () => {
  const host = document.createElement("div"), root = createRoot(host);
  let resolve!: (v: typeof result) => void;
  const a = api();
  a.objects.mockResolvedValue({ items: [{ id: "w", title: "工单" }, { id: "w2", title: "第二工单" }], total: 2 });
  a.mesOrderMaterials.mockImplementation(async (_p: string, id: string) => ({ work_order_id: id, can_manage: true, binding: { id: "b", shop_order: id === "w" ? "FIRST" : "SECOND", environment: "test", site_code: "1" }, snapshot: null }));
  const changed = vi.fn();
  const p = { api: { ...a, command: vi.fn().mockReturnValue(new Promise(r => { resolve = r; })) }, project, readOnly: false, onDirty: vi.fn(), onChanged: changed };
  try {
    await act(async () => root.render(<MesOrderMaterials p={p as any} leave={f => f()} />));
    await select(host);
    await act(async () => [...host.querySelectorAll("button")].find(b => b.textContent === "刷新组件")!.click());
    await select(host, "w2");
    await act(async () => resolve(result));
    expect(changed).toHaveBeenCalledWith(result);
    expect((host.querySelector("select") as HTMLSelectElement).value).toBe("w2");
    expect(host.textContent).toContain("SECOND");
    expect(host.textContent).not.toContain("FIRST");
  } finally { await act(async () => root.unmount()); }
});
it("keeps the saved MES result visible after successful bind in WorkflowApp", async () => {
  const oem = { ...base, mode: "oem" as const };
  const v = await workflowView({ initial: "制造项目", options: { onNavigatePlatform: vi.fn() }, readProjects: async () => [oem], readProject: async () => oem });
  const original = globalThis.fetch;
  let bound = false;
  vi.stubGlobal("fetch", vi.fn(async (input, init) => {
    const url = String(input);
    if (url.includes("/objects/work_order?")) return new Response(JSON.stringify({ items: [{ id: "w", title: "工单" }], total: 1 }));
    if (url.endsWith("/mes-materials")) return new Response(JSON.stringify({ work_order_id: "w", can_manage: true, binding: bound ? { id: "b", shop_order: "MES", environment: "test", site_code: "1" } : null, snapshot: bound ? { id: "s", collected_at: "time", total: 1, components: [{ component_key: "1:1", material_id: "MAT", required_quantity: "1", withdrawn_quantity: null, unit: "EA", storage_location: null }] } : null }));
    if (url.endsWith("/commands")) { bound = true; return new Response(JSON.stringify({ ...result, project_id: base.id })); }
    return original(input, init);
  }));
  try {
    await v.click("供应与物料");
    await v.field("平台工单", "w");
    await v.field("MES工单号", "MES");
    await v.click("返回 Agent 平台");
    await v.click("继续编辑");
    expect((v.host.querySelector('[aria-label="MES工单号"]') as HTMLInputElement).value).toBe("MES");
    await v.click("关联MES工单");
    expect(v.host.querySelector('[aria-label="MES工单物料"]')).not.toBeNull();
    expect((v.host.querySelector('[aria-label="平台工单"]') as HTMLSelectElement).value).toBe("w");
    expect(v.host.textContent).toContain("MAT");
  } finally { await v.dispose(); }
});
it("keeps the newer command retry identity when an older command finishes", async () => {
  const host = document.createElement("div"), root = createRoot(host);
  let resolveFirst!: (v: typeof result) => void;
  const a = api();
  a.objects.mockResolvedValue({ items: [{ id: "w", title: "工单" }, { id: "w2", title: "第二工单" }], total: 2 });
  a.mesOrderMaterials.mockResolvedValue({ work_order_id: "w", can_manage: true, binding: { id: "b", shop_order: "MES", environment: "test", site_code: "1" }, snapshot: null });
  const command = vi.fn().mockReturnValueOnce(new Promise(r => { resolveFirst = r; })).mockRejectedValueOnce(new Error("network")).mockResolvedValue(result);
  const p = { api: { ...a, command }, project, readOnly: false, onDirty: vi.fn(), onChanged: vi.fn() };
  const refresh = async () => act(async () => [...host.querySelectorAll("button")].find(b => b.textContent === "刷新组件")!.click());
  try {
    await act(async () => root.render(<MesOrderMaterials p={p as any} leave={f => f()} />));
    await select(host);
    await refresh();
    await select(host, "w2");
    await refresh();
    await act(async () => resolveFirst(result));
    await refresh();
    expect(command.mock.calls[2][1].operation_id).toBe(command.mock.calls[1][1].operation_id);
  } finally { await act(async () => root.unmount()); }
});
