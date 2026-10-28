import { DetailContent } from "./WorkflowDetail";
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { QualityWorkspace } from './QualityWorkspace';
import type { ProjectDetail } from './types';
const id='00000000-0000-4000-8000-000000000001';
const project={id,version:7,customer_id:'Customer 1',contract:{customer_revision:'C1'},allowed_actions:['test.record','nonconformance.open','nonconformance.disposition','rework.complete','release.decide'],release_kinds:['quality'],quality_summary:{first_tested:100,first_passed:96,final_good:99,scrapped:1,open_nonconformances:0}} as ProjectDetail;
const summary=(kind:string)=>({id,project_id:id,kind,title:kind==='unit'?'SN-001':kind+' evidence',state:'open',version:1,blocking_reasons:[],next_actions:[]});
const revision={kind:'revision',id,test_spec:{version:'T1',program_version:'P1',measurements:[{name:'voltage',unit:'V',lower:'4',upper:'6'}]},firmware_version:'F1',route_steps:[]};
const api={objects:vi.fn(async(_p:string,k:string)=>({items:['unit','test','nonconformance','rework'].includes(k)?[summary(k)]:[],total:1,limit:50,offset:0})),object:vi.fn(async(_p:string,k:string)=>({value:k==='unit'?{kind:'unit',id,revision_id:id,tests:[{id,attempt:1,outcome:'fail'}],test_total:1,first_pass:false}:k==='revision'?revision:{kind:k,id,unit_id:id,route_steps:[{station:'repair',instruction_version:'RW1'}],execution_event_ids:[],test_ids:[]}})),command:vi.fn(async(_p:string,c:any)=>({operation_id:c.operation_id,project_id:id,project_version:8,object_type:'test',object_id:id}))} as any;
let host:HTMLDivElement,root:Root;
beforeEach(()=>{host=document.createElement('div');document.body.append(host);root=createRoot(host);api.command.mockClear();});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
async function render(p=project){await act(async()=>root.render(<QualityWorkspace api={api} project={p} onChanged={()=>{}} onOpen={()=>{}} onDirty={()=>{}} readOnly={false} requestLeave={f=>f()}/>));await act(async()=>{await new Promise(r=>setTimeout(r,0));});}
async function click(text:string){const el=[...host.querySelectorAll('button')].find(x=>x.textContent===text);expect(el,text).toBeTruthy();await act(async()=>el!.click());}
async function field(name:string,value:string){const e=host.querySelector(`[aria-label="${name}"]`) as HTMLInputElement;expect(e,name).toBeTruthy();await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(e,value);e.dispatchEvent(new Event('input',{bubbles:true}));});}
it('shows first/final history and only server-permitted release panels',async()=>{await render();expect(host.textContent).toContain('96');expect(host.textContent).toContain('99');expect(host.textContent).toContain('质量放行');expect(host.textContent).not.toContain('制造放行');expect(host.textContent).not.toContain('客户放行');expect(host.textContent).toContain('首次未通过');});
it('submits measured frozen specification without client PASS',async()=>{await render();await click('记录测试');await field('voltage 实测值','5');await field('来源业务编号','TEST-1');await field('来源凭据','manual test');await click('保存测量');const sent=api.command.mock.calls[0]?.[1];expect(sent).toMatchObject({action:'test.record',unit_id:id,attempt:2,program_version:'P1',limit_version:'T1',measurements:[{name:'voltage',unit:'V',lower:'4',upper:'6',value:'5'}]});expect(sent).not.toHaveProperty('outcome');});
it('loads later bounded selector pages explicitly',async()=>{api.objects.mockImplementationOnce(async()=>({items:Array.from({length:50},(_,i)=>({...summary('unit'),id:String(i),title:'SN-'+i})),total:51,limit:50,offset:0}));await render();const more=[...host.querySelectorAll('button')].find(b=>b.textContent?.startsWith('读取更多序列号'));expect(more).toBeTruthy();await act(async()=>more!.click());expect(api.objects).toHaveBeenCalledWith(id,'unit',50,50);});
it('submits a typed independent repair route',async()=>{await render();await click('不合格处置');await field('返工路线编号','RW-1');await field('返工工位 1','repair');await field('返工作业指导 1','RW-S1');await field('处置依据','qualified disposition');await click('保存处置');expect(api.command.mock.calls[0][1]).toMatchObject({action:'nonconformance.disposition',nonconformance_id:id,decision:'rework',route_id:'RW-1',route_steps:[{station:'repair',instruction_version:'RW-S1'}]});});
it('submits only the chosen authorized release kind and explicit serials',async()=>{await render();await click('质量放行');const box=host.querySelector('input[type="checkbox"]') as HTMLInputElement;await act(async()=>box.click());await field('独立签署依据','QA evidence');await click('保存独立放行');expect(api.command.mock.calls[0][1]).toMatchObject({action:'release.decide',kind:'quality',unit_ids:[id],decision:'approved',evidence:'QA evidence'});});
it('completes a 101-step route from named rework evidence beyond the unit history cap',async()=>{
 const candidates=Array.from({length:101},(_,i)=>({id:`repair-event-${i}`,station:`repair-${i}`,route_version:'RW-S1',occurred_at:'2026-10-28T00:00:00Z',result:'pass',rework_order_id:id}));
 api.objects.mockImplementation(async(_p:string,k:string)=>({items:['unit','test','rework'].includes(k)?[{...summary(k),state:k==='test'?'pass':'open'}]:[],total:1,limit:50,offset:0}));
 api.object.mockImplementation(async(_p:string,k:string)=>({value:k==='unit'?{kind:'unit',id,revision_id:id,tests:[],test_total:0,execution_events:[]}:k==='revision'?revision:{kind:'rework',id,unit_id:id,route_id:'RW-101',route_steps:candidates.map(e=>({station:e.station,instruction_version:e.route_version})),execution_event_ids:[],test_ids:[],candidate_execution_events:candidates}}));
 await render();
 const rework=host.querySelector('[aria-label="查看返工单"]') as HTMLSelectElement;
 await act(async()=>{rework.value=id;rework.dispatchEvent(new Event('change',{bubbles:true}));await new Promise(r=>setTimeout(r,0));});
 await click('完成返工');
 const boxes=[...host.querySelectorAll('input[type="checkbox"]')] as HTMLInputElement[];
 expect(boxes).toHaveLength(101);
 await act(async()=>boxes.forEach(box=>box.click()));
 const test=host.querySelector('[aria-label="通过复测"]') as HTMLSelectElement;
 await act(async()=>{test.value=id;test.dispatchEvent(new Event('change',{bubbles:true}));});
 await click('确认返工完成');
 expect(api.command.mock.calls[0][1]).toMatchObject({action:'rework.complete',rework_order_id:id,test_ids:[id]});
 expect(api.command.mock.calls[0][1].execution_event_ids).toHaveLength(101);
});

it('retains measurements while suppressing an unbound historical source',async()=>{
 const detail:any={summary:{...summary('test'),state:'pass'},value:{kind:'test',id,unit_id:id,revision_id:id,attempt:1,scope:{test_version:'T1',program_version:'P1',firmware_version:'F1',equipment_check_id:id},measurements:[{name:'voltage',unit:'V',lower:'4',upper:'6',value:'5'}],outcome:'pass',source:null,occurred_at:'2026-10-28T00:00:00Z'},relations:[],history:[],evidence:[]};
 await act(async()=>root.render(<DetailContent data={detail} onOpen={()=>{}}/>));
 expect(host.textContent).toContain('来源未通过准入');
 expect(host.textContent).toContain('voltage');
 expect(host.textContent).not.toContain('来源系统');
});
it('shows historical PASS separately from current evidence qualification and audit source badges',async()=>{
 const src={system:'Signed manual lab',object_type:'test',external_id:'TEST-HISTORY',version:1,mode:'manual',occurred_at:'2026-10-28T00:00:00Z',collected_at:'2026-10-28T00:00:00Z',cutoff:null,evidence:'Signed measurement'};
 const detail:any={summary:{...summary('test'),state:'pass'},value:{kind:'test',id,unit_id:id,revision_id:id,attempt:1,scope:{test_version:'T1',program_version:'P1',firmware_version:'F1',equipment_check_id:id},measurements:[{name:'voltage',unit:'V',lower:'4',upper:'6',value:'5'}],outcome:'pass',current_qualified:false,current_blocking_reasons:['Original execution evidence is no longer valid'],source:null,occurred_at:'2026-10-28T00:00:00Z'},relations:[],history:[{event_id:1,action:'test.record',occurred_at:src.occurred_at,recorded_at:src.collected_at,evidence:[{reference:'Historical lab record',source:src}]}],evidence:[]};
 await act(async()=>root.render(<DetailContent data={detail} onOpen={()=>{}}/>));expect(host.textContent).toContain('当前资格：不满足');expect(host.textContent).toContain('Original execution evidence is no longer valid');expect(host.textContent).toContain('Signed manual lab');expect(host.textContent).toContain('人工登记');
});
