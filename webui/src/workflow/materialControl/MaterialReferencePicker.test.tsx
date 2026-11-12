// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { MaterialReferencePicker } from "./MaterialReferencePicker";
import { flush } from "../testHelpers";

it("searches and paginates references, and reports a failed page instead of showing stale rows", async () => {
  const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  const api = { materialReferences: vi.fn().mockResolvedValueOnce({items:[{reference:{kind:"receipt",id:"r"},evidence:{title:"第一单",origin:"mock",environment:"mock"},can_open:true}],total:51,project_id:"p",task_kind:"verify",project_version:3}).mockRejectedValueOnce(new Error("断开")) };
  await act(async () => root.render(<MaterialReferencePicker api={api as never} projectId="p" version={3} kind="verify" onSelect={()=>{}} />));
  await flush(); expect(host.textContent).toContain("第一单"); expect(host.textContent).toContain("模拟");
  await act(async () => [...host.querySelectorAll("button")].find(b=>b.textContent==="下一页引用")!.click()); await flush();
  expect(api.materialReferences).toHaveBeenLastCalledWith("p", "verify", "", 50, 50, expect.any(AbortSignal));
  expect(host.textContent).toContain("引用读取失败"); expect(host.textContent).not.toContain("第一单");
  await act(async () => root.unmount()); host.remove();
});
it("passes the applied search and requirement scope to the API", async () => {
  const host=document.createElement("div"); document.body.append(host); const root=createRoot(host);
  const api={materialReferences:vi.fn().mockResolvedValue({items:[],total:0,project_id:"p",task_kind:"verify",project_version:3})};
  await act(async()=>root.render(<MaterialReferencePicker api={api as never} projectId="p" version={3} kind="verify" requirementId="r" onSelect={()=>{}}/>)); await flush();
  const input=host.querySelector('[aria-label="搜索引用"]') as HTMLInputElement;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value")!.set!.call(input,"轴承");input.dispatchEvent(new Event("input",{bubbles:true}));});
  await act(async()=>[...host.querySelectorAll("button")].find(b=>b.textContent==="搜索引用")!.click()); await flush();
  expect(api.materialReferences).toHaveBeenLastCalledWith("p","verify","轴承",50,0,expect.any(AbortSignal),"r");
  await act(async()=>root.unmount()); host.remove();
});
it("reports an unavailable reference API explicitly", async () => {
  const host=document.createElement("div"); document.body.append(host); const root=createRoot(host);
  await act(async()=>root.render(<MaterialReferencePicker api={{} as never} projectId="p" version={3} kind="verify" onSelect={()=>{}}/>));
  expect(host.textContent).toContain("引用读取失败"); expect(host.textContent).toContain("引用查询不可用");
  await act(async()=>root.unmount()); host.remove();
});
it("rejects a reference page returned for a different project",async()=>{
 const host=document.createElement("div");document.body.append(host);const root=createRoot(host);
 const api={materialReferences:vi.fn().mockResolvedValue({project_id:"other",project_version:3,items:[{reference:{kind:"receipt",id:"foreign"},evidence:{title:"外项目记录",origin:"manual",environment:"unknown"},can_open:true}],total:1})};
 await act(async()=>root.render(<MaterialReferencePicker api={api as never} projectId="p" version={3} kind="verify" onSelect={()=>{}}/>));await flush();
 expect(host.textContent).not.toContain("外项目记录");expect(host.textContent).toContain("引用读取失败");
 await act(async()=>root.unmount());host.remove();
});
