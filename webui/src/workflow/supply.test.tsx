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
async function select(label:string,value:string){
  const e=host.querySelector(`[aria-label="${label}"]`) as HTMLSelectElement;
  expect(e,label).toBeTruthy();
  await act(async()=>{e.value=value;e.dispatchEvent(new Event("change",{bubbles:true}));});
}
const summary=(n:number,kind:"requirement"|"commitment"|"material_lot")=>({
  id:`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`,project_id:id,kind,title:`item-${n}`,
  state:"active",quantity:null,unit:null,version:1,source:null,blocking_reasons:[],next_actions:[],
});
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
it("preserves promise edits when delayed requirement and commitment details return",async()=>{
  const r=summary(31,"requirement"), c=summary(32,"commitment");
  const pending=new Map<string,(x:any)=>void>();
  const api={object:vi.fn((_p:string,_k:string,x:string)=>new Promise(resolve=>pending.set(x,resolve)))} as any;
  await act(async()=>root.render(<SupplyForms action="supply.commit" api={api} project={project}
    onChanged={()=>{}} onOpen={()=>{}} onDirty={()=>{}} readOnly={false}
    workOrders={[]} orders={[]} revisions={[]} lots={[]} requirements={[r]}
    commitments={[c]} receipts={[]}/>));
  await select("承诺对应需求",r.id);await field("供应承诺数量","24");
  await act(async()=>pending.get(r.id)!({value:{kind:"requirement",owner_id:"Owner",unit:"kg"}}));
  expect((host.querySelector('[aria-label="供应承诺数量"]') as HTMLInputElement).value).toBe("24");
  expect((host.querySelector('[aria-label="供应所有者"]') as HTMLInputElement).value).toBe("Owner");
  await select("修订既有承诺",c.id);await field("供应承诺数量","25");
  await field("当前承诺交期","2027-01-01");await field("来源业务编号","edited-ref");
  await act(async()=>pending.get(c.id)!({value:{kind:"commitment",requirement_id:r.id,type:"purchase",
    owner_id:"Owner",current_quantity:"10",unit:"kg",original_due:"2026-12-01",
    current_due:"2026-12-02",source:{system:"ERP",external_id:"old-ref",version:1}}}));
  expect((host.querySelector('[aria-label="供应承诺数量"]') as HTMLInputElement).value).toBe("25");
  expect((host.querySelector('[aria-label="当前承诺交期"]') as HTMLInputElement).value).toBe("2027-01-01");
  expect((host.querySelector('[aria-label="来源业务编号"]') as HTMLInputElement).value).toBe("edited-ref");
});
it("ignores a delayed lot detail after the receipt selection changes",async()=>{
  const a=summary(33,"material_lot"), b=summary(34,"material_lot");
  const pending=new Map<string,(x:any)=>void>();
  const api={object:vi.fn((_p:string,_k:string,x:string)=>new Promise(resolve=>pending.set(x,resolve)))} as any;
  await act(async()=>root.render(<SupplyForms action="supply.receive" api={api} project={project}
    onChanged={()=>{}} onOpen={()=>{}} onDirty={()=>{}} readOnly={false}
    workOrders={[]} orders={[]} revisions={[]} lots={[a,b]} requirements={[]}
    commitments={[]} receipts={[]}/>));
  await select("到货物料批次",a.id);await field("本次到货数量","7");
  await select("到货物料批次",b.id);
  await act(async()=>pending.get(a.id)!({value:{kind:"material_lot",unit:"kg"}}));
  expect((host.querySelector('[aria-label="到货物料批次"]') as HTMLSelectElement).value).toBe(b.id);
  expect((host.querySelector('[aria-label="本次到货数量"]') as HTMLInputElement).value).toBe("7");
  await act(async()=>pending.get(b.id)!({value:{kind:"material_lot",unit:"m"}}));
  expect(host.textContent).toContain("计量单位：m");
});
it("ignores stale plan material lookup after a different lot is selected",async()=>{
  const a=summary(35,"material_lot"), b=summary(36,"material_lot");
  const pending=new Map<string,(x:any)=>void>();
  const api={object:vi.fn((_p:string,_k:string,x:string)=>new Promise(resolve=>pending.set(x,resolve)))} as any;
  await act(async()=>root.render(<SupplyForms action="plan.receive" api={api} project={project}
    onChanged={()=>{}} onOpen={()=>{}} onDirty={()=>{}} readOnly={false}
    workOrders={[]} orders={[]} revisions={[]} lots={[a,b]} requirements={[]}
    commitments={[]} receipts={[]}/>));
  await select("计划物料批次 1",a.id);await select("计划物料批次 1",b.id);
  await act(async()=>pending.get(a.id)!({value:{kind:"material_lot",material_id:"old",owner_id:"A",unit:"kg"}}));
  expect(host.textContent).not.toContain("物料 old");
  await act(async()=>pending.get(b.id)!({value:{kind:"material_lot",material_id:"new",owner_id:"B",unit:"m"}}));
  expect(host.textContent).toContain("物料 new");
});
it("reservation form uses named requirement and lot selectors with exact quantity",async()=>{
  const props:any={api:{object:vi.fn().mockResolvedValue({value:{kind:"requirement",work_order_id:id,unit:"kg"}}),command:vi.fn()},project:{...project,allowed_actions:["reservation.request"]},onChanged:vi.fn(),onOpen:vi.fn(),onDirty:vi.fn(),readOnly:false,
    action:"reservation.request",workOrders:[],orders:[],revisions:[],requirements:[summary(2,"requirement")],lots:[summary(3,"material_lot")],commitments:[],receipts:[]};
  await act(async()=>root.render(<SupplyForms {...props}/>));
  await select("预留对应需求",summary(2,"requirement").id);await flush();
  await select("预留物料批次",summary(3,"material_lot").id);
  await field("请求预留数量","1.250");await click("保存预留请求");
  expect(props.api.command).toHaveBeenCalledWith(id,expect.objectContaining({action:"reservation.request",quantity:"1.250",unit:"kg",work_order_id:id,requirement_id:summary(2,"requirement").id,lot_id:summary(3,"material_lot").id}));
});
it("exchange workspace exposes synchronization and bounded request list",async()=>{
  await act(async()=>root.render(<WorkflowApp options={{apiBase:"/api/v1/manufacturing",csrfToken:"csrf",readOnly:false,bootstrap}}/>));
  await flush();await click("制造项目");await click("相机项目");await click("同步与回执");
  expect(host.textContent).toContain("权威系统");
  expect(host.textContent).toContain("模拟");
});
it("source pull submits named configured identity and preserves the frozen retry",async()=>{
  const {ExchangeWorkspace}=await import("./ExchangeWorkspace");
  const {WorkflowError}=await import("./api");
  const command=vi.fn().mockRejectedValue(new WorkflowError(409,"VERSION_CONFLICT"));
  const props:any={api:{objects:vi.fn().mockResolvedValue({items:[],total:0}),command},project:{...project,allowed_actions:["source.pull","supply.receive"]},onChanged:vi.fn(),onOpen:vi.fn(),onDirty:vi.fn(),readOnly:false,mode:"test",requestLeave:(f:()=>void)=>f()};
  await act(async()=>root.render(<ExchangeWorkspace {...props}/>));await flush();
  await click("获取来源事实");await field("外部业务编号","WMS-DELIVERY-25");await click("读取权威来源");await click("读取权威来源");
  expect(command).toHaveBeenCalledTimes(2);expect(command.mock.calls[0][1]).toEqual(command.mock.calls[1][1]);
  expect(command.mock.calls[0][1]).toMatchObject({action:"source.pull",system:"erp",object_type:"receipt",external_id:"WMS-DELIVERY-25",expected_version:7});
  expect(command.mock.calls[0][1]).not.toHaveProperty("receipt");
});
it("exchange detail distinguishes uncertain simulation from confirmed inventory",async()=>{
  await act(async()=>root.render(<DetailContent data={{summary:{id,project_id:id,kind:"exchange",title:"ERP 库存请求",state:"unknown",quantity:null,unit:null,version:1,blocking_reasons:[],next_actions:[]},value:{kind:"exchange",action:"reservation.request",policy_action:"reservation.request",system:"erp",business_key:id,mode:"mock",phase:"unknown",requested:"80",accepted:"0",rejected:"0",unit:"kg",reason:"Reply lost; query existing business key",events:[{sequence:1,phase:"unknown",reason:"请求已保存"}],receipt:null,reservation_id:id,source:null,source_object_type:null},relations:[],history:[],evidence:[]} as ObjectDetail} onOpen={vi.fn()}/>));
  expect(host.textContent).toContain("模拟权威系统");expect(host.textContent).toContain("已接受");expect(host.textContent).toContain("Reply lost");expect(host.textContent).toContain("请求已保存");
});
it("production exchange workspace is visibly unconnected and read-only disables actions",async()=>{
  const {ExchangeWorkspace}=await import("./ExchangeWorkspace");
  const props:any={api:{objects:vi.fn().mockResolvedValue({items:[],total:0})},project:{...project,allowed_actions:["source.pull","supply.receive","exchange.dispatch"]},onChanged:vi.fn(),onOpen:vi.fn(),onDirty:vi.fn(),readOnly:true,mode:"production",requestLeave:(f:()=>void)=>f()};
  await act(async()=>root.render(<ExchangeWorkspace {...props}/>));await flush();
  expect(host.textContent).toContain("权威系统未接入");expect(host.textContent).not.toContain("模拟权威系统");
  expect([...host.querySelectorAll("button")].some(b=>b.textContent==="发送权威请求")).toBe(false);
});
it("uses completed apply version for the next draft while project refresh remains delayed",async()=>{
  const original=vi.mocked(fetch).getMockImplementation()!;
  const reads:((r:Response)=>void)[]=[];
  const currentProject={...project,allowed_actions:["exchange.dispatch","reservation.request","source.pull","supply.receive"]};
  const exchangeId="00000000-0000-4000-8000-000000000099";
  const item={id:exchangeId,project_id:id,kind:"exchange",title:"ERP 预留请求",state:"unknown",quantity:"80",unit:"kg",version:1,blocking_reasons:[],next_actions:["exchange.query","exchange.dispatch"]};
  vi.mocked(fetch).mockImplementation(async(u,i={})=>{
    const url=String(u);
    if(i.method==="POST"){
      const body=JSON.parse(String(i.body));writes.push(body);
      return response({operation_id:body.operation_id,project_id:id,project_version:6+writes.length*2,
        current_project_version:7+writes.length*2,object_type:"exchange",object_id:exchangeId,exchange_id:exchangeId,replayed:false});
    }
    if(url.endsWith("/projects")||url.endsWith("/projects/"+id)){
      if(writes.length)return new Promise<Response>(r=>reads.push(r));
      return response(url.endsWith("/projects")?{items:[currentProject]}:currentProject);
    }
    if(url.includes("/objects/exchange/"))return response({summary:item,value:{kind:"exchange",action:"reservation.request",policy_action:"reservation.request",system:"erp",business_key:exchangeId,mode:"mock",phase:"unknown",requested:"80",accepted:"0",rejected:"0",unit:"kg",reason:"等待权威确认",events:[],receipt:null,reservation_id:null,source:null,source_object_type:null},relations:[],history:[],evidence:[]});
    if(url.includes("/objects/exchange?"))return response({items:[item],total:1,limit:50,offset:0});
    return original(u,i);
  });
  await act(async()=>root.render(<WorkflowApp options={{apiBase:"/api/v1/manufacturing",csrfToken:"csrf",readOnly:false,bootstrap}}/>));
  await flush();await click("制造项目");await click("相机项目");await click("同步与回执");await click("发送权威请求");
  await select("待处理交换",exchangeId);await flush();await click("查询后发送原请求");
  await click("返回业务列表");await click("获取来源事实");await field("外部业务编号","DELIVERY-1");await click("读取权威来源");
  expect(writes.map(w=>w.expected_version)).toEqual([7,9]);
  await act(async()=>reads.forEach(r=>r(response({items:[currentProject]}))));await flush();
  await click("返回业务列表");await click("获取来源事实");await field("外部业务编号","DELIVERY-2");await click("读取权威来源");
  expect(writes.map(w=>w.expected_version)).toEqual([7,9,11]);
});
it('shows a failed selected-object lookup without treating missing scope as a successful lookup',async()=>{
 const api={object:vi.fn(async()=>{throw Error('Selected requirement unavailable');}),command:vi.fn()} as any;
 await act(async()=>root.render(<SupplyForms api={api} project={{...project,allowed_actions:['reservation.request']}} action="reservation.request" onDirty={()=>{}} onChanged={()=>{}} onOpen={()=>{}} readOnly={false} workOrders={[]} orders={[]} revisions={[]} lots={[]} requirements={[{id,project_id:id,kind:'requirement',title:'Steel requirement',state:'active',version:1,next_actions:[],blocking_reasons:[],quantity:'1',unit:'kg'}]} commitments={[]} receipts={[]}/>));await select('预留对应需求',id);await flush();expect(host.querySelector('[role="alert"]')?.textContent).toContain('Selected requirement unavailable');expect(api.command).not.toHaveBeenCalled();
});
it("selects the 51st work order through bounded lookup paging and preserves draft",async()=>{
  const {SupplyWorkspace}=await import('./SupplyWorkspace');
  const workOrders=Array.from({length:51},(_,n)=>({...summary(n+100,'requirement'),kind:'work_order' as const,title:`WO-${n+1}`}));
  const api={objects:vi.fn(async(_pid:string,kind:string,limit:number,offset:number)=>({items:kind==='work_order'?workOrders.slice(offset,offset+limit):kind==='material_lot'?[summary(999,'material_lot')]:[],total:kind==='work_order'?51:kind==='material_lot'?1:0,limit,offset})),
    object:vi.fn(async(_pid:string,kind:string)=>kind==='work_order'?{value:{kind,revision_id:'revision-51',order_line_id:'order-51'}}:kind==='material_lot'?{value:{kind,material_id:'steel',owner_id:'客户甲',unit:'kg'}}:{summary:{version:2}}),command:vi.fn(async()=>({project_id:id,project_version:8}))} as any;
  await act(async()=>root.render(<SupplyWorkspace api={api} project={project} readOnly={false} onChanged={()=>{}} onOpen={()=>{}} onDirty={()=>{}} requestLeave={f=>f()}/>));await flush();
  await click('接收供应计划');await field('计划物料数量 1','3');
  const more=[...host.querySelectorAll('button')].find(b=>b.textContent?.startsWith('读取更多工单（'));
  expect(more).toBeTruthy();await act(async()=>more!.click());await flush();
  await select('计划依据工单 1',workOrders[50].id);await flush();
  expect((host.querySelector('[aria-label="计划依据工单 1"]') as HTMLSelectElement).value).toBe(workOrders[50].id);
  expect((host.querySelector('[aria-label="计划物料数量 1"]') as HTMLInputElement).value).toBe('3');
  expect(api.objects).toHaveBeenCalledWith(id,'work_order',50,50);
  await select('计划物料批次 1',summary(999,'material_lot').id);await flush();
  await field('计划来源截止时间','2026-10-29T08:00');await field('来源业务编号','PLAN-51');await field('来源凭据','approved');
  await click('保存计划');
  expect(api.command.mock.calls[0][1]).toMatchObject({requirements:[{work_order_id:workOrders[50].id,quantity:'3'}],input_revision_ids:['revision-51'],input_order_versions:[{order_line_id:'order-51',version:2}]});
});
it('discards a late lookup page and old form when the project changes',async()=>{
 const {SupplyWorkspace}=await import('./SupplyWorkspace');let finish!:(x:any)=>void;
 const old={...summary(100,'requirement'),kind:'work_order',title:'OLD-WO'};
 const api={objects:vi.fn(async(pid:string,kind:string,_limit:number,offset:number)=>kind==='work_order'&&offset===50?new Promise(r=>finish=r):({items:pid===id&&kind==='work_order'?Array.from({length:50},(_,i)=>({...old,id:String(i)})):[],total:pid===id&&kind==='work_order'?51:0,limit:50,offset:0}))} as any;
 const props={api,project,readOnly:false,onChanged:()=>{},onOpen:()=>{},onDirty:()=>{},requestLeave:(f:()=>void)=>f()};
 await act(async()=>root.render(<SupplyWorkspace {...props}/>));await flush();await click('接收供应计划');await field('计划物料数量 1','old draft');
 const more=[...host.querySelectorAll('button')].find(b=>b.textContent?.startsWith('读取更多工单（'))!;await act(async()=>more.click());
 await act(async()=>root.render(<SupplyWorkspace {...props} project={{...project,id:'new-project'}}/>));await flush();
 await act(async()=>finish({items:[old],total:51,limit:50,offset:50}));await flush();
 expect(host.textContent).not.toContain('OLD-WO');
 expect((host.querySelector('[aria-label="计划物料数量 1"]') as HTMLInputElement).value).toBe('');
});
