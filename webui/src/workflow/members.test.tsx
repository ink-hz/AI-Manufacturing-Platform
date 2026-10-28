import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Members } from "./WorkflowProjects";
import { ConflictComparison } from "./ConflictComparison";
import { createWorkflowApi, WorkflowError } from "./api";
import type { ProjectDetail } from "./types";

const pid = "00000000-0000-4000-8000-000000000001";
const grants = Array.from({length:51}, (_,n)=>({user_id:`10000000-0000-4000-8000-${String(n).padStart(12,"0")}`,scope:{kind:"project",project_id:pid},roles:n===50?["quality"]:[],qualifications:n===50?["inspection"]:[],active:n!==50}));
const target = grants[50];
const project = {id:pid,version:3,unit:{code:"件",scale:0},summary:{current_order_quantity:"1",allocated:"1"}} as ProjectDetail;
let host:HTMLDivElement, root:Root, requests:string[], failLookup:boolean, submitted:any;
const response=(body:unknown,status=200)=>new Response(JSON.stringify(body),{status});
async function flush(){await act(async()=>{await new Promise(r=>setTimeout(r,0));});}
async function click(text:string){const b=[...host.querySelectorAll("button")].find(b=>b.textContent===text)!;expect(b).toBeTruthy();await act(async()=>b.click());await flush();}
beforeEach(()=>{
 host=document.createElement("div");document.body.append(host);root=createRoot(host);requests=[];failLookup=false;submitted=null;
 vi.stubGlobal("fetch",vi.fn(async(raw:string,init:RequestInit)=>{
  const url=new URL(String(raw),location.origin);requests.push(url.pathname+url.search);
  if(init?.method==="PUT"){submitted=JSON.parse(String(init.body));return response({code:"VERSION_CONFLICT",message:"changed",fields:{current_version:4}},409);}
  if(url.pathname.endsWith("/members")){
   if(failLookup)return response({code:"UNAVAILABLE",message:"unavailable"},503);
   const id=url.searchParams.get("user_id");return response({items:id?grants.filter(g=>g.user_id===id):grants.slice(0,50)});
  }
  return response({...project,version:4});
 }));
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
function api(){return createWorkflowApi({apiBase:"/api/v1/manufacturing",csrfToken:"csrf",readOnly:false});}
async function mountMembers(){await act(async()=>root.render(<Members api={api()} project={project} readOnly={false} onDirty={()=>{}} onChanged={()=>{}} onOpen={()=>{}} findSubjects={async()=>[{id:target.user_id,displayName:"Quality 51"}]}/>));await flush();}
async function selectTarget(){const select=host.querySelector('[aria-label="授权成员"]') as HTMLSelectElement;await act(async()=>{select.value=target.user_id;select.dispatchEvent(new Event("change",{bubbles:true}));});await flush();}
it("loads the selected 51st grant and compares its current conflict without truncation",async()=>{
 await mountMembers();await selectTarget();
 expect((host.querySelector('[aria-label="质量"]') as HTMLInputElement).checked).toBe(true);
 expect((host.querySelector('[aria-label="检验资格"]') as HTMLInputElement).checked).toBe(true);
 expect((host.querySelector('[aria-label="授权状态"]') as HTMLSelectElement).value).toBe("false");
 const evidence=host.querySelector('[aria-label="授权凭据"]') as HTMLInputElement;
 await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value")!.set!.call(evidence,"review");evidence.dispatchEvent(new Event("input",{bubbles:true}));});
 await act(async()=>host.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})));await flush();
 expect(submitted.roles).toEqual(["quality"]);expect(submitted.qualifications).toEqual(["inspection"]);expect(submitted.active).toBe(false);
 await click("保留草稿并对照当前资料");expect(host.textContent).toContain("资格：检验资格");
 expect(requests.filter(x=>x.includes("/members?")).every(x=>x.includes(`user_id=${target.user_id}`))).toBe(true);
});
it("current grant comparison finds the 51st grant",async()=>{
 await act(async()=>root.render(<ConflictComparison api={api()} projectId={pid} memberId={target.user_id} version={3} error={new WorkflowError(409,"VERSION_CONFLICT",[],{current_version:4})}/>));
 await click("保留草稿并对照当前资料");expect(host.textContent).toContain("资格：检验资格");
});
it("failed selected-grant loading cannot submit an invented empty grant",async()=>{
 failLookup=true;await mountMembers();await selectTarget();
 const button=[...host.querySelectorAll("button")].find(b=>b.textContent==="保存成员授权")!;
 expect(button.disabled).toBe(true);
 await act(async()=>host.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})));await flush();expect(submitted).toBeNull();
});
it("normalizes the real grant wire response into project freshness metadata",async()=>{
 const changed=vi.fn();const real=api();
 const fetchBefore=fetch;
 vi.stubGlobal('fetch',vi.fn(async(raw:any,init:any)=>init?.method==='PUT'?response({...target,roles:['quality'],active:false,project_version:9}):fetchBefore(raw,init)));
 await act(async()=>root.render(<Members api={real} project={project} readOnly={false} onDirty={()=>{}} onChanged={changed} onOpen={()=>{}} findSubjects={async()=>[{id:target.user_id,displayName:'Quality 51'}]}/>));await flush();await selectTarget();
 const e=host.querySelector('[aria-label="授权凭据"]') as HTMLInputElement;
 await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(e,'signed');e.dispatchEvent(new Event('input',{bubbles:true}));});
 await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));await flush();
 expect(changed).toHaveBeenCalledWith(expect.objectContaining({project_id:pid,project_version:9}));
});
