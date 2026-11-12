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

for (const editor of [
  { action: "expedite.open", open: "发起催料", field: "催料原因" },
  { action: "material_task.open", open: "安排检验", field: "任务说明" },
]) {
  it(`clears a discarded ${editor.field} draft when changing MES work order, while cancel preserves it`, async () => {
    const host = document.createElement("div"), root = createRoot(host);
    const dirty: Record<string, boolean> = {};
    let pending: (() => void) | undefined;
    const leave = (f: () => void) => { if (Object.values(dirty).some(Boolean)) pending = f; else f(); };
    const p = {
      api: { ...api(), materialAssignees: vi.fn().mockResolvedValue({ items: [] }) },
      project: { ...project, allowed_actions: [editor.action] }, readOnly: false,
      onDirty: (k: string, v: boolean) => { dirty[k] = v; }, onChanged: vi.fn(), onOpen: vi.fn(), requestLeave: leave, requestLocalLeave: leave,
    };
    const click = async (label: string) => act(async () => [...host.querySelectorAll("button")].find(b => b.textContent === label)!.click());
    try {
      await act(async () => root.render(<MaterialControlWorkspace {...p as any} />));
      await click("齿轮");
      await click(editor.open);
      await act(async () => {
        const input = host.querySelector(`[aria-label="${editor.field}"]`)!;
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "DRAFT");
        input.dispatchEvent(new Event("input", { bubbles: true }));
      });
      await select(host);
      expect(pending).toBeTruthy();
      pending = undefined; // Continue editing leaves the callback unexecuted.
      expect((host.querySelector(`[aria-label="${editor.field}"]`) as HTMLInputElement).value).toBe("DRAFT");
      expect((host.querySelector('[aria-label="平台工单"]') as HTMLSelectElement).value).toBe("");
      await select(host);
      await act(async () => { for (const k in dirty) delete dirty[k]; pending!(); });
      expect(host.querySelector(`[aria-label="${editor.field}"]`)).toBeNull();
      expect((host.querySelector('[aria-label="平台工单"]') as HTMLSelectElement).value).toBe("w");
      expect(host.querySelector('[aria-label="物料需求详情"]')?.textContent).toContain("齿轮");
      await click(editor.open);
      expect((host.querySelector(`[aria-label="${editor.field}"]`) as HTMLInputElement).value).toBe("");
    } finally { await act(async () => root.unmount()); }
  });
}
it('acknowledges a delayed need-time command in WorkflowApp after selecting another requirement', async () => {
  const oem = {...base, mode:'oem' as const, allowed_actions:['material.need_time'] as const};
  let version=3, resolve!: (r:Response)=>void;
  const req=(id:string)=>({id,material_id:id,work_order_id:'w',owner_id:'客户',coverage_issues:[],unit:'件',required:'1',reserved:'0',qualified:'0',shortage:'1',received:'0',rejected:'0',in_transit:'0',need_at:null,need_at_basis:'work_order_planned_start_proxy',receipt_ids:[],handoff_ids:[],expedite_ids:[]});
  const page=()=>({project_id:base.id,project_version:version,read_at:'',coverage_issues:[],source_modes:[],work_orders:[],requirements:[req('物料甲'),req('物料乙')],expedites:[],receipts:[],handoffs:[],material_task_counts:{},total:2,limit:50,offset:0});
  const v=await workflowView({initial:'制造项目',readProjects:async()=>[oem as any],readProject:async()=>({...oem,version}) as any,readMaterialProject:async()=>page()});const original=globalThis.fetch; const commands:any[]=[];
  vi.stubGlobal('fetch',vi.fn(async(input,init)=>{const url=String(input);if(url.includes('/objects/requirement/'))return new Response(JSON.stringify({value:{kind:'requirement',need_time_events:[]}}));if(url.endsWith('/commands')){commands.push(JSON.parse(String(init?.body)));if(commands.length===1)return new Promise<Response>(r=>{resolve=r});return new Response(JSON.stringify({...result,project_id:base.id,project_version:5,object_type:'requirement'}));}return original(input,init);}));
  try {await v.click('供应与物料');await v.click('物料甲');await v.click('调整需要时间');await v.field('调整原因','测试原因');await v.click('保存需要时间');await v.click('物料乙');await v.click('放弃并离开');version=4;await act(async()=>resolve(new Response(JSON.stringify({...result,project_id:base.id,project_version:4,object_type:'requirement'}))));await new Promise(r=>setTimeout(r,0));await v.click('调整需要时间');await v.field('调整原因','第二次');await v.click('保存需要时间');expect(commands[1].expected_version).toBe(4);expect(v.host.querySelector('[aria-label="物料需求详情"]')?.textContent).toContain('物料乙');} finally {await v.dispose();}
});
it('does not acknowledge a delayed command after the API identity changes', async () => {
 const oem={...base,mode:'oem' as const,allowed_actions:['material.need_time'] as const};let resolve!:(r:Response)=>void;const req={id:'r',material_id:'轴承',work_order_id:'w',owner_id:'客户',coverage_issues:[],unit:'件',required:'1',reserved:'0',qualified:'0',shortage:'1',received:'0',rejected:'0',in_transit:'0',need_at:null,need_at_basis:'work_order_planned_start_proxy',receipt_ids:[],handoff_ids:[],expedite_ids:[]};const page={project_id:base.id,project_version:3,read_at:'',coverage_issues:[],source_modes:[],work_orders:[],requirements:[req],expedites:[],receipts:[],handoffs:[],material_task_counts:{},total:1,limit:50,offset:0};
 const v=await workflowView({initial:'制造项目',readProjects:async()=>[oem as any],readProject:async()=>oem as any,readMaterialProject:async()=>page});const original=globalThis.fetch;const commands:any[]=[];vi.stubGlobal('fetch',vi.fn(async(input,init)=>{const url=String(input);if(url.includes('/objects/requirement/'))return new Response(JSON.stringify({value:{kind:'requirement',need_time_events:[]}}));if(url.endsWith('/commands')){commands.push(JSON.parse(String(init?.body)));if(commands.length===1)return new Promise<Response>(r=>{resolve=r});return new Response(JSON.stringify({...result,project_id:base.id,project_version:4,object_type:'requirement'}));}return original(input,init);}));
 try {await v.click('供应与物料');await v.click('轴承');await v.click('调整需要时间');await v.field('调整原因','旧连接');await v.click('保存需要时间');await v.rerender({csrfToken:'new-token'});await act(async()=>resolve(new Response(JSON.stringify({...result,project_id:base.id,project_version:9,object_type:'requirement'}))));await new Promise(r=>setTimeout(r,0));expect(v.host.textContent).not.toContain('项目版本 9');}finally{await v.dispose();}
});
it('does not refresh a different project when an old need-time command completes', async () => {
 const a={...base,mode:'oem' as const,allowed_actions:['material.need_time'] as const};const b={...a,id:'second',name:'第二项目'};let resolve!:(r:Response)=>void;const req={id:'r',material_id:'轴承',work_order_id:'w',owner_id:'客户',coverage_issues:[],unit:'件',required:'1',reserved:'0',qualified:'0',shortage:'1',received:'0',rejected:'0',in_transit:'0',need_at:null,need_at_basis:'work_order_planned_start_proxy',receipt_ids:[],handoff_ids:[],expedite_ids:[]};const page={project_id:base.id,project_version:3,read_at:'',coverage_issues:[],source_modes:[],work_orders:[],requirements:[req],expedites:[],receipts:[],handoffs:[],material_task_counts:{},total:1,limit:50,offset:0};
 const v=await workflowView({initial:'制造项目',readProjects:async()=>[a as any,b as any],readProject:async()=>a as any,readMaterialProject:async(_offset,id)=>({...page,project_id:id})});const original=globalThis.fetch;let secondReads=0;vi.stubGlobal('fetch',vi.fn(async(input,init)=>{const url=String(input);if(url.endsWith('/projects/second'))return new Response(JSON.stringify(b));if(url.includes('/projects/second/material-control?'))secondReads++;if(url.includes('/objects/requirement/'))return new Response(JSON.stringify({value:{kind:'requirement',need_time_events:[]}}));if(url.endsWith('/commands'))return new Promise<Response>(r=>{resolve=r});return original(input,init);}));
 try {await v.click('供应与物料');await v.click('轴承');await v.click('调整需要时间');await v.field('调整原因','旧项目');await v.click('保存需要时间');await v.click('返回项目列表');await v.click('放弃并离开');await v.click('第二项目');await v.click('供应与物料');const before=secondReads;await act(async()=>resolve(new Response(JSON.stringify({...result,project_id:base.id,project_version:9,object_type:'requirement'}))));await new Promise(r=>setTimeout(r,0));expect(secondReads).toBe(before);expect(v.host.textContent).toContain('第二项目');}finally{await v.dispose();}
});
it('applies search and problem filters through the real WorkflowApp material request', async () => {
 const oem={...base,mode:'oem' as const};const page={project_id:base.id,project_version:3,read_at:'',coverage_issues:[],source_modes:[],work_orders:[],requirements:[],expedites:[],receipts:[],handoffs:[],material_task_counts:{},total:0,scope_total:0,problem_counts:{attention:0,urgent:0},limit:50,offset:0};const v=await workflowView({initial:'制造项目',readProjects:async()=>[oem],readProject:async()=>oem,readMaterialProject:async()=>page});try{await v.click('供应与物料');await v.field('全项目搜索','轴承');await v.click('搜索');await v.field('卡点筛选','urgent');const calls=v.requests.filter(x=>x.url.includes('/material-control?'));const query=new URL(calls.at(-1)!.url,'http://localhost').searchParams;expect(query.get('search')).toBe('轴承');expect(query.get('problem')).toBe('urgent');expect(query.get('offset')).toBe('0');}finally{await v.dispose();}
});
