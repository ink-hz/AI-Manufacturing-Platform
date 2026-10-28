import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ExecutionWorkspace } from "./ExecutionWorkspace";
import { WorkflowError } from "./api";
import type { ProjectDetail, ObjectSummary } from "./types";

const id="00000000-0000-4000-8000-000000000001";
const workOrder: ObjectSummary={id,project_id:id,kind:"work_order",title:"WO-5",state:"planned",quantity:"5",unit:"piece",version:1,blocking_reasons:[],next_actions:[]};
const project:ProjectDetail={id,version:7,name:"相机",line_id:"一线",product:"相机",customer_id:"客户",mode:"internal",unit:{code:"piece",scale:0},quantity:"5",contract:{customer_approval_required:true,customer_release_required:"unknown",acceptance_required:"unknown",customer_revision:"C1",internal_revision:"M1",material_ownership_rules:"客户物料"},stages:[],summary:{original_order_quantity:"5",current_order_quantity:"5",allocated:"5",produced_good:"0",shipped:"0",signed:"0",accepted:"0",remaining_to_ship:"5",remaining_to_accept:"5"},allowed_actions:["unit.register","production.start","production.interrupt","production.resume","execution.record","first_article.record"]};
let host:HTMLDivElement,root:Root,writes:any[];
const api={objects:vi.fn(async(_p:string,k:string)=>({items:k==="work_order"?[workOrder]:[],total:k==="work_order"?1:0,limit:50,offset:0})),object:vi.fn(async()=>({value:{kind:"work_order",revision_id:id,trial_readiness:{ready:true,checks:[],input_versions:{}},bulk_readiness:{ready:false,checks:[{kind:"first_article",status:"blocked",reason:"matching tested first article absent"}],input_versions:{}}}})),command:vi.fn(async(_p:string,c:any)=>{writes.push(c);return {operation_id:c.operation_id,project_id:id,project_version:8,object_type:"unit",object_id:id,replayed:false};})} as any;
beforeEach(()=>{host=document.createElement("div");document.body.append(host);root=createRoot(host);writes=[];api.objects.mockReset().mockImplementation(async(_p:string,k:string)=>({items:k==="work_order"?[workOrder]:[],total:k==="work_order"?1:0,limit:50,offset:0}));api.object.mockReset().mockImplementation(async()=>({value:{kind:"work_order",revision_id:id,trial_readiness:{ready:true,checks:[],input_versions:{}},bulk_readiness:{ready:false,checks:[{kind:"first_article",status:"blocked",reason:"matching tested first article absent"}],input_versions:{}}}}));api.command.mockReset().mockImplementation(async(_p:string,c:any)=>{writes.push(c);return {operation_id:c.operation_id,project_id:id,project_version:8,object_type:"unit",object_id:id,replayed:false};});});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
async function flush(){await act(async()=>{await new Promise(r=>setTimeout(r,0));});}
async function click(name:string){const b=[...host.querySelectorAll("button")].find(x=>x.textContent?.trim()===name);expect(b,name).toBeTruthy();await act(async()=>b!.click());await flush();}
async function field(name:string,value:string){const e=host.querySelector(`[aria-label="${name}"]`) as HTMLInputElement;expect(e,name).toBeTruthy();await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value")!.set!.call(e,value);e.dispatchEvent(new Event("input",{bubbles:true}));e.dispatchEvent(new Event("change",{bubbles:true}));});}
it("shows trial and bulk readiness and registers named SNs",async()=>{
  await act(async()=>root.render(<ExecutionWorkspace api={api} project={project} onChanged={()=>{}} onOpen={()=>{}} onDirty={()=>{}} readOnly={false} requestLeave={f=>f()}/>));await flush();
  expect(host.textContent).toContain("试产准备");expect(host.textContent).toContain("首件");
  await click("登记序列号");await field("序列号 1","SN-001");await click("保存序列号");
  expect(writes[0]).toMatchObject({action:"unit.register",work_order_id:id,sns:["SN-001"]});
});
it("keeps trial and bulk as distinct start modes",async()=>{
  await act(async()=>root.render(<ExecutionWorkspace api={api} project={project} onChanged={()=>{}} onOpen={()=>{}} onDirty={()=>{}} readOnly={false} requestLeave={f=>f()}/>));await flush();
  await click("首件试做开工");expect(host.textContent).toContain("试产范围");
  await click("放弃草稿并重新读取");await click("批量执行开工");expect(host.textContent).toContain("首件");
});
it("submits selected trial SN count and freezes conflict retry",async()=>{
  const unit={...workOrder,id:"00000000-0000-4000-8000-000000000002",kind:"unit" as const,title:"SN-002",state:"registered"};
  api.objects.mockImplementation(async(_p:string,k:string)=>({items:k==="work_order"?[workOrder]:k==="unit"?[unit]:[],total:k==="work_order"||k==="unit"?1:0,limit:50,offset:0}));
  api.command.mockImplementationOnce(async(_p:string,c:any)=>{writes.push(c);throw new WorkflowError(409,"VERSION_CONFLICT",[],{current_version:8});}).mockImplementationOnce(async(_p:string,c:any)=>{writes.push(c);return {operation_id:c.operation_id,project_id:id,project_version:9,object_type:"work_order",object_id:id,replayed:false};});
  await act(async()=>root.render(<ExecutionWorkspace api={api} project={project} onChanged={()=>{}} onOpen={()=>{}} onDirty={()=>{}} readOnly={false} requestLeave={f=>f()}/>));await flush();
  await click("首件试做开工");
  const checkbox=host.querySelector('input[type="checkbox"]') as HTMLInputElement;
  await act(async()=>checkbox.click());
  await click("提交开工请求");
  expect(host.textContent).toContain("草稿已保留");
  await click("提交开工请求");
  expect(writes).toHaveLength(2);expect(writes[0]).toEqual(writes[1]);
  expect(writes[0]).toMatchObject({action:"production.start",mode:"trial",unit_ids:[unit.id],quantity:"1",expected_version:7});
});
it("shows the fixed package basis beside execution actions",async()=>{
  api.object.mockImplementation(async(_p:string,k:string)=>k==="revision"?{value:{kind:"revision",package_id:"camera-pkg",revision:"M1",route_steps:[{station:"assembly",instruction_version:"S1"}],test_spec:{version:"T1",program_version:"P1",measurements:[]},firmware_version:"F1"}}:{value:{kind:"work_order",revision_id:id,trial_readiness:{ready:true,checks:[],input_versions:{}},bulk_readiness:{ready:false,checks:[],input_versions:{}}}});
  await act(async()=>root.render(<ExecutionWorkspace api={api} project={project} onChanged={()=>{}} onOpen={()=>{}} onDirty={()=>{}} readOnly={false} requestLeave={f=>f()}/>));await flush();
  expect(host.textContent).toContain("camera-pkg");expect(host.textContent).toContain("S1");expect(host.textContent).toContain("P1");expect(host.textContent).toContain("F1");
});
it("offers a scoped MES safety stop for an accepted start held locally",async()=>{
  const held="00000000-0000-4000-8000-000000000003";
  api.object.mockImplementation(async()=>({value:{kind:"work_order",revision_id:id,held_start_scopes:[{id:held,mode:"trial",sns:["SN-003"],exchange_id:id,receipt_id:id}],trial_readiness:{ready:false,checks:[],input_versions:{}},bulk_readiness:{ready:false,checks:[],input_versions:{}}}}));
  await act(async()=>root.render(<ExecutionWorkspace api={api} project={project} onChanged={()=>{}} onOpen={()=>{}} onDirty={()=>{}} readOnly={false} requestLeave={f=>f()}/>));await flush();
  expect(host.textContent).toContain("MES 已接受");expect(host.textContent).toContain("SN-003");
  await click("请求生产中断");await field("中断原因与异常","calibration changed");await click("请求 MES 停机");
  expect(writes[0]).toMatchObject({action:"production.interrupt",work_order_id:id,start_id:held,reason:"calibration changed"});
});

it("loads a second bounded page for plans, material lots and test selectors",async()=>{
  const titles:Record<string,string>={plan:"MRP-current-51",material_lot:"Steel-required-51",test:"Fresh-calibration-test-51"};
  api.objects.mockImplementation(async(_p:string,k:string,limit:number,offset:number)=>{
    const title=titles[k];
    const items=title?(offset===0?Array.from({length:50},(_,i)=>({...workOrder,id:`${k}-${i}`,kind:k,title:`${k}-${i}`,state:"confirmed"})):[{...workOrder,id:`${k}-51`,kind:k,title,state:"confirmed"}]):k==="work_order"?[workOrder]:[];
    return {items,total:title?51:items.length,limit,offset};
  });
  await act(async()=>root.render(<ExecutionWorkspace api={api} project={project} onChanged={()=>{}} onOpen={()=>{}} onDirty={()=>{}} readOnly={false} requestLeave={f=>f()}/>));await flush();
  expect(api.objects).toHaveBeenCalledTimes(7);
  for(const kind of Object.keys(titles)){
    const button=[...host.querySelectorAll("button")].find(b=>b.textContent?.startsWith("读取更多")&&b.textContent.includes(kind==="plan"?"计划":kind==="material_lot"?"物料":"测试"));
    expect(button,kind).toBeTruthy();
    await act(async()=>button!.click());await flush();
    expect(api.objects).toHaveBeenCalledWith(id,kind,50,50);
  }
  await click("恢复生产");
  expect(host.querySelector('[aria-label="新确认计划"]')?.textContent).toContain(titles.plan);
  await click("放弃草稿并重新读取");await click("记录工位执行");
  expect(host.querySelector('[aria-label="实际物料批次 1"]')?.textContent).toContain(titles.material_lot);
  await click("放弃草稿并重新读取");await click("记录首件检验");
  expect(host.querySelector('[aria-label="完整通过的测试 1"]')?.textContent).toContain(titles.test);
  expect(api.objects).toHaveBeenCalledTimes(10);
});

it("offers explicit trial requalification while bulk stays stopped",async()=>{
  api.objects.mockImplementation(async(_p:string,k:string)=>({items:k==="work_order"?[workOrder]:k==="interruption"?[{...workOrder,kind:k,title:"Calibration stop",state:"stopped"}]:k==="plan"?[{...workOrder,kind:k,title:"Replan",state:"confirmed"}]:[],total:1,limit:50,offset:0}));
  await act(async()=>root.render(<ExecutionWorkspace api={api} project={project} onChanged={()=>{}} onOpen={()=>{}} onDirty={()=>{}} readOnly={false} requestLeave={f=>f()}/>));await flush();
  await click("恢复生产");
  const scope=host.querySelector('[aria-label="恢复范围"]') as HTMLSelectElement;
  expect(scope).toBeTruthy();
  await act(async()=>{scope.value="trial";scope.dispatchEvent(new Event("change",{bubbles:true}));});
  await field("复工核验凭据","renewed calibration");await click("请求 MES 恢复");
  expect(writes[0]).toMatchObject({action:"production.resume",scope:"trial"});
});
it('records explicit no-consumption only where the fixed initial route permits it',async()=>{
 const {ExecutionForms}=await import('./forms/ExecutionForms');
 const revision={kind:'revision',route_steps:[{station:'calibration',instruction_version:'S2',material_consumption:'none'}],test_spec:{program_version:'P1'},firmware_version:'F1'} as any;
 await act(async()=>root.render(<ExecutionForms api={api} project={project} onChanged={()=>{}} onOpen={()=>{}} onDirty={()=>{}} readOnly={false} action="execution.record" workOrders={[workOrder]} units={[{...workOrder,kind:'unit',title:'SN-1'}]} interruptions={[]} plans={[]} lots={[]} tests={[]} revision={revision}/>));
 await click('移除此物料');await act(async()=>{const select=host.querySelector('[aria-label="序列号"]') as HTMLSelectElement;select.value='SN-1';select.dispatchEvent(new Event('change',{bubbles:true}));});await field('来源业务编号','CAL-1');await field('来源凭据','Actual calibration');
 await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 expect(writes[0]).toMatchObject({station:'calibration',route_version:'S2',material_uses:[]});
 await field('工位','assembly');await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 expect(writes).toHaveLength(1);
});
it('loads the qualified rework route before permitting zero-use adjustment',async()=>{
 const {ExecutionForms}=await import('./forms/ExecutionForms');let complete!:(d:any)=>void;
 api.object.mockImplementation(()=>new Promise(r=>complete=r));
 const revision={kind:'revision',route_steps:[{station:'adjust',instruction_version:'RW1'}],test_spec:{program_version:'P1'},firmware_version:'F1'} as any;
 await act(async()=>root.render(<ExecutionForms api={api} project={project} onChanged={()=>{}} onOpen={()=>{}} onDirty={()=>{}} readOnly={false} action="execution.record" workOrders={[workOrder]} units={[{...workOrder,kind:'unit',title:'SN-1'}]} interruptions={[]} plans={[]} lots={[]} tests={[]} revision={revision} reworks={[{...workOrder,kind:'rework',title:'Qualified adjustment'}]}/>));
 const select=host.querySelector('[aria-label="独立返工单"]') as HTMLSelectElement;await act(async()=>{select.value=id;select.dispatchEvent(new Event('change',{bubbles:true}));});
 expect([...host.querySelectorAll('button')].some(b=>b.textContent==='移除此物料')).toBe(false);
 await act(async()=>complete({value:{kind:'rework',id,route_steps:[{station:'adjust',instruction_version:'RW1',material_consumption:'none'}]}}));await flush();
 await click('移除此物料');expect(host.querySelector('[aria-label="实际物料用量 1"]')).toBeNull();
});
