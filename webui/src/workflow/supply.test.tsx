import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import { WorkflowApp } from "./WorkflowApp";
import { DetailContent } from "./WorkflowDetail";
import { SupplyForms } from "./forms/SupplyForms";
import type { ProjectDetail, ObjectDetail } from "./types";

const id = "00000000-0000-4000-8000-000000000001";
const project: ProjectDetail = {
  id, version: 7, name: "相机项目", line_id: "一线", product: "D1",
  customer_id: "客户甲", mode: "internal", unit: {code:"件",scale:0}, quantity:"100",
  contract: {customer_approval_required:false,customer_release_required:false,
    acceptance_required:false,customer_revision:"C1",internal_revision:"M1",
    material_ownership_rules:"客户所有"},
  stages: [], summary: {original_order_quantity:"100",current_order_quantity:"100",
    allocated:"0",produced_good:"0",shipped:"0",signed:"0",accepted:"0",
    remaining_to_ship:"100",remaining_to_accept:"100"},
  allowed_actions:["material.define","plan.receive","supply.commit","supply.receive","supply.inspect"],
};
const bootstrap = {
  protocol:1 as const, allowed:true, available:true, workflow_available:true,
  workflow_access:true, can_edit:true, release:"test", legacy_access:false,
  configuration_admin:false, dataset:{id:"test",mode:"test" as const,label:"隔离测试"},
  user:{id,display_name:"李工"},project_ids:[id],
};
let host: HTMLDivElement, root:Root, writes:any[], commandStatus:number;
const response=(x:unknown,status=200)=>new Response(JSON.stringify(x),{status});
async function flush(){await act(async()=>{await new Promise(r=>setTimeout(r,0));});}
async function click(label:string){
  const b=[...host.querySelectorAll("button")].find(x=>x.textContent?.trim()===label && !x.closest("[hidden]"));
  expect(b,label).toBeTruthy();
  await act(async()=>b!.click());await flush();
}
async function field(label:string,value:string){
  const e=host.querySelector(`[aria-label="${label}"]`) as HTMLInputElement;
  expect(e,label).toBeTruthy();
  await act(async()=>{
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value")!.set!.call(e,value);
    e.dispatchEvent(new Event("input",{bubbles:true}));
    e.dispatchEvent(new Event("change",{bubbles:true}));
  });
}
beforeEach(()=>{
  host=document.createElement("div");document.body.append(host);root=createRoot(host);writes=[];commandStatus=200;
  vi.stubGlobal("fetch",vi.fn(async(url:string,init:RequestInit={})=>{
    if(init.method==="POST"){
      const body=JSON.parse(String(init.body));writes.push(body);
      if(commandStatus===409)return response({code:"VERSION_CONFLICT",message:"Project version changed",blocking_reasons:[]},409);
      return response({operation_id:body.operation_id,project_id:id,project_version:8,
        object_type:"material_lot",object_id:"00000000-0000-4000-8000-000000000002",replayed:false});
    }
    if(url.endsWith("/dashboard"))return response({counts:{},cards:[],project_ids:[id],project_count:1});
    if(url.endsWith("/projects"))return response({items:[project]});
    if(url.endsWith("/projects/"+id))return response(project);
    if(url.includes("/objects/"))return response({items:[],total:0,limit:50,offset:0});
    throw Error("Unexpected "+url);
  }));
});
it("material form parses named fields and preserves frozen draft after conflict",async()=>{
  await act(async()=>root.render(<WorkflowApp options={{apiBase:"/api/v1/manufacturing",csrfToken:"csrf",readOnly:false,bootstrap}}/>));
  await flush();await click("制造项目");await click("相机项目");await click("供应与物料");await click("定义物料批次");
  await field("物料业务编号","steel-42");await field("批次业务编号","batch-2");
  await field("批次有效期","2027-12-01");await field("来源业务编号","ERP-LOT-2");await field("来源凭据","签收单");
  commandStatus=409;await click("保存物料批次");
  expect((host.querySelector('[aria-label="物料业务编号"]') as HTMLInputElement).value).toBe("steel-42");
  await click("保存物料批次");
  expect(writes).toHaveLength(2);expect(writes[0]).toEqual(writes[1]);
  expect(writes[0]).toMatchObject({action:"material.define",expected_version:7,
    material_id:"steel-42",lot_id:"batch-2",owner_id:"客户甲",unit:"kg",scale:3,
    expiry:"2027-12-01",source:{object_type:"material_lot",mode:"manual",external_id:"ERP-LOT-2",evidence:"签收单"}});
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
it("opens real supply workspace with named material form",async()=>{
  await act(async()=>root.render(<WorkflowApp options={{apiBase:"/api/v1/manufacturing",csrfToken:"csrf",readOnly:false,bootstrap}}/>));
  await flush();await click("制造项目");await click("相机项目");await click("供应与物料");
  expect(host.textContent).toContain("物料需求");
  expect(host.textContent).toContain("在途");
  expect(host.textContent).toContain("确认预留");
  expect(host.textContent).toContain("缺口");
  await click("定义物料批次");
  expect(host.querySelector('[aria-label="物料业务编号"]')).toBeTruthy();
  expect(host.querySelector('[aria-label="物料计量精度"]')).toBeTruthy();
  expect(host.querySelector('[aria-label="来源业务编号"]')).toBeTruthy();
});
it("plan form can name multiple scoped material requirements",async()=>{
  await act(async()=>root.render(<WorkflowApp options={{apiBase:"/api/v1/manufacturing",csrfToken:"csrf",readOnly:false,bootstrap}}/>));
  await flush();await click("制造项目");await click("相机项目");await click("供应与物料");
  await click("接收供应计划");await click("添加物料需求");
  expect(host.querySelectorAll('[aria-label^="计划物料数量"]')).toHaveLength(2);
});
it("keeps the selected material lot visible while deriving material identity",async()=>{
  const lotId="00000000-0000-4000-8000-000000000020";
  const lot={id:lotId,project_id:id,kind:"material_lot" as const,title:"batch-20",state:"active",
    quantity:null,unit:null,version:1,source:null,blocking_reasons:[],next_actions:[]};
  const api={object:vi.fn(async()=>({value:{kind:"material_lot",material_id:"steel",owner_id:"客户甲",unit:"kg"}}))} as any;
  await act(async()=>root.render(<SupplyForms action="plan.receive" api={api} project={project}
    onChanged={()=>{}} onOpen={()=>{}} onDirty={()=>{}} readOnly={false}
    workOrders={[]} orders={[]} revisions={[]} lots={[lot]} requirements={[]}
    commitments={[]} receipts={[]}/>));
  const select=host.querySelector('[aria-label="计划物料批次 1"]') as HTMLSelectElement;
  await act(async()=>{select.value=lotId;select.dispatchEvent(new Event("change",{bubbles:true}));});
  await flush();
  expect((host.querySelector('[aria-label="计划物料批次 1"]') as HTMLSelectElement).value).toBe(lotId);
  expect(host.textContent).toContain("物料 steel");
});
it("shows typed requirement balance and original/current promise fields",async()=>{
  const detail={
    summary:{id,project_id:id,kind:"requirement",title:"steel",state:"required",quantity:"100",
      unit:"kg",version:1,blocking_reasons:[],next_actions:[]},
    value:{kind:"requirement",plan_id:id,work_order_id:id,execution_scope:"trial",
      material_id:"steel",owner_id:"客户甲",quantity:"100",unit:"kg",
      balance:{required:"100",in_transit:"20",received:"80",qualified:"75",rejected:"5",
        reserved:"0",shortage:"100",unit:"kg",cutoff:"2026-10-28T08:00:00Z",source_version:2},
      unqualified_quantity:"5"},relations:[],evidence:[],history:[],
  } as unknown as ObjectDetail;
  await act(async()=>root.render(<DetailContent data={detail} onOpen={()=>{}}/>));
  expect(host.textContent).toContain("在途");
  expect(host.textContent).toContain("已检合格");
  expect(host.textContent).toContain("确认预留");
  expect(host.textContent).toContain("缺口");
});
it("shows the source plan version used by work order readiness",async()=>{
  const checks=[{kind:"plan",required:true,status:"ready",reason:"current scoped plan and source cutoff",evidence_ids:[]}];
  const readiness={ready:false,checks,input_versions:{project:7,revision:"M1",work_order:1,plan:2,
    plan_id:"plan-2",plan_source:"PLAN-2",plan_cutoff:"2026-10-28T08:00:00+00:00"}};
  const detail={summary:{id,project_id:id,kind:"work_order",title:"WO-1",state:"planned",quantity:"5",unit:"piece",version:1,blocking_reasons:[],next_actions:[]},
    value:{kind:"work_order",order_line_id:id,revision_id:id,quantity:"5",unit:"piece",purpose:"trial",trial_quantity:"1",
      source:{system:"erp",object_type:"work_order",external_id:"WO-1",version:1,mode:"manual",occurred_at:"2026-10-28T08:00:00Z",collected_at:"2026-10-28T08:00:00Z",cutoff:null,evidence:"manual"},
      planned_start:"2026-12-01T00:00:00Z",planned_end:"2026-12-02T00:00:00Z",state:"planned",
      trial_readiness:readiness,bulk_readiness:readiness},relations:[],evidence:[],history:[]} as unknown as ObjectDetail;
  await act(async()=>root.render(<DetailContent data={detail} onOpen={()=>{}}/>));
  expect(host.textContent).toContain("计划来源版本");
  expect(host.textContent).toContain("PLAN-2");
});
