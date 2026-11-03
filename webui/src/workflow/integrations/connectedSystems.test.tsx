import {act} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {afterEach,describe,it,expect,vi} from 'vitest';
import {WorkflowHome} from '../WorkflowHome';
import {SystemFacts} from './SystemFacts';
import type {FactDetail} from './types';
import {SystemStepPanel} from './SystemStepPanel';
import {BUSINESS_STEPS} from './businessSteps';
import type {OEMWorkspaceProps} from '../OEMWorkspace';
let host:HTMLDivElement,root:Root;
afterEach(async()=>{if(root)await act(async()=>root.unmount());host?.remove();});
async function render(node:React.ReactNode){host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(node));}
async function choose(id:string){await act(async()=>{const el=host.querySelector('[aria-label="系统业务步骤"]') as HTMLSelectElement;el.value=id;el.dispatchEvent(new Event('change',{bubbles:true}));});}
async function click(name:string){const el=[...host.querySelectorAll('button')].find(b=>b.textContent===name);expect(el,name).toBeTruthy();await act(async()=>el!.click());}
const project={id:'project-a',version:1,name:'Camera',customer_id:'C',product:'P',unit:{code:'piece',scale:0},allowed_actions:['mock_system.execute'],release_kinds:['manufacturing','quality']};
function props(){return {project,api:{project:vi.fn(async()=>project),systems:vi.fn(async()=>['sap','pdm','crm','oa','hr_sap','hr_beisen','hr_dingtalk','mes','wms','product_test','plc','bi','customer','overseas','srm'].map(system=>({system,profile:'oem-network-v1',mode:'test',maturity:system==='srm'?'planned':'modeled',status:'unexercised',permitted_operations:BUSINESS_STEPS.filter(s=>s.responsibleSystem===system).map(s=>s.operationKind),capabilities:[],pending_count:0}))),objects:vi.fn(async()=>({items:[],total:0})),systemFacts:vi.fn(async()=>({records:[],continuation:null,source_cutoff:0,projections:[]})),integrationIntents:vi.fn(async()=>({records:[],total:0,limit:50,offset:0})),command:vi.fn()},onChanged:vi.fn(),onOpen:vi.fn(),onDirty:vi.fn(),requestLeave:(f:()=>void)=>f(),readOnly:false} as unknown as OEMWorkspaceProps;}
describe('integrated responsibilities',()=>{
 for(const context of [...new Set(BUSINESS_STEPS.map(s=>s.context))]) it(`shows focused ${context} steps and honest missing evidence`,async()=>{
  await render(<SystemStepPanel {...props()} context={context} selected={null}/>);
  expect(host.textContent).toContain('模拟契约');
  for(const step of BUSINESS_STEPS.filter(s=>s.context===context)){
   await choose(step.id);
   expect(host.querySelector('h4')?.textContent).toBe(step.title);
   expect(host.textContent).toContain('输入');expect(host.textContent).toContain('产出');
   expect(host.textContent).toContain('当前对象尚未读取到此步骤回执');
  }
  expect(host.querySelector('[aria-label=JSON]')).toBeNull();expect(host.querySelector('[aria-label=UUID]')).toBeNull();
 });
 it('does not present a connector last receipt as selected-object evidence',async()=>{
  const p=props();await render(<SystemStepPanel {...p} context="supply" selected={null}/>);
  expect(host.textContent).toContain('模拟契约');
  expect(host.textContent).toContain('当前对象尚未读取到此步骤回执');
 });
 it('retains frozen source intent after an unknown HTTP result and queries original identity',async()=>{
  const p=props();const command=vi.mocked(p.api.command);command.mockRejectedValueOnce(new Error('lost response'));
  await render(<SystemStepPanel {...p} context="home" selected={null}/>);
  await click('执行：刷新 BI 快照');
  expect(host.textContent).toContain('查询原操作结果');
  const original=command.mock.calls[0][1].operation_id;
  await click('查询原操作结果');
  expect(command).toHaveBeenCalledTimes(2);
  expect(command.mock.calls[1][1]).toMatchObject({action:'mock_system.query',intent_id:original});
  expect(command.mock.calls[1][1].operation_id).not.toBe(original);
  expect([...host.querySelectorAll('button')].some(b=>b.textContent==='执行：刷新 BI 快照')).toBe(false);
 });
});

it('hides source writes when read-only and keeps modeled HR evidence separate from application rights',async()=>{
 const p=props();p.readOnly=true;await render(<SystemStepPanel {...p} context="execution" selected={null}/>);
 await choose('execution.hr-qualification');expect(host.textContent).toContain('培训');
 expect(host.querySelector('form')).toBeNull();expect(p.api.command).not.toHaveBeenCalled();
});
it('guards stage navigation while an edited business draft is retained',async()=>{
 const p=props();p.requestLeave=vi.fn();await render(<SystemStepPanel {...p} context="orders" selected={null}/>);
 const input=host.querySelector('[aria-label="数量与单位 / 数量"]') as HTMLInputElement;
 await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'3');input.dispatchEvent(new Event('input',{bubbles:true}));});
 expect(p.onDirty).toHaveBeenCalledWith('system-step:project-a:orders:orders.crm-demand',true);
 await choose('orders.sap-order');expect(p.requestLeave).toHaveBeenCalled();expect(host.querySelector('h4')?.textContent).toBe('CRM 客户需求');expect(input.value).toBe('3');
});
it('recovers a durable original intent with a fresh API after reload and does not offer a replacement execute',async()=>{
 const p=props(),original='00000000-0000-4000-8000-000000000099';
 vi.mocked(p.api.integrationIntents).mockResolvedValue({project_id:p.project.id,records:[{intent_id:original,project_id:p.project.id,system:'bi',operation:'bi.refresh',expected_version:1,phase:'unknown',created_at:'2026-11-03T00:00:00Z',source_committed:null,receipt:null}],total:1,limit:50,offset:0});
 await render(<SystemStepPanel {...p} context="home" selected={null}/>);
 expect(host.querySelector('button[type=submit]')).toBeNull();await click('查询原操作结果');
 expect(p.api.command).toHaveBeenCalledWith('project-a',expect.objectContaining({action:'mock_system.query',intent_id:original}));
 expect(host.textContent).not.toContain('核对未提交草稿');
});
it('does not offer quality-release variants to an actor with only manufacturing release rights',async()=>{
 const p=props();p.project={...p.project,release_kinds:['manufacturing']};await render(<SystemStepPanel {...p} context="quality" selected={null}/>);await choose('quality.mes-release');
 const select=host.querySelector('[aria-label="业务类别"]') as HTMLSelectElement;
 expect([...select.options].map(o=>o.value)).toEqual(['manufacturing']);
});
it('finds only exact causal SAP posting evidence for the selected physical shipment, including unprojected facts',async()=>{
 const p=props();p.readOnly=true;const selected={project_id:'project-a',kind:'shipment' as const,id:'shipment-a'};
 const physical={system:'wms' as const,object_type:'shipment',external_id:'physical-a',version:1};
 const posting={source:{system:'sap',object_type:'shipment_posting',external_id:'posting-a',version:1,occurred_at:'2026-11-03'},project_id:'project-a',payload:{fact_type:'sap.shipment_posting'},evidence:'Actual SAP posting',caused_by:[physical]};
 p.api.integrationLinks=vi.fn(async()=>({target:selected,records:[{source_key:physical,projection:{targets:[],auxiliary:[]}}],continuation:null,complete:true})) as unknown as typeof p.api.integrationLinks;
 p.api.object=vi.fn(async()=>({summary:{blocking_reasons:[]},value:{kind:'shipment'}})) as unknown as typeof p.api.object;
 p.api.systemFacts=vi.fn(async()=>({records:[posting,{...posting,source:{...posting.source,external_id:'unrelated'},caused_by:[{...physical,external_id:'another-shipment'}]}],continuation:null,source_cutoff:2,projections:[]})) as unknown as typeof p.api.systemFacts;
 p.api.systemFact=vi.fn(async()=>({fact:posting,source_accepted:true,workflow_projected:false,sap_posted:true,consumer_delivered:null,receipts:[],delivery_states:[],predecessors:[]})) as unknown as typeof p.api.systemFact;
 await render(<SystemStepPanel {...p} context="delivery" selected={selected}/>);await choose('delivery.sap-posting');
 expect(p.api.systemFact).toHaveBeenCalledWith('project-a',expect.objectContaining({external_id:'posting-a'}),expect.any(AbortSignal));
 expect(vi.mocked(p.api.systemFact).mock.calls.some(c=>c[1].external_id==='unrelated')).toBe(false);
 expect(host.textContent).toContain('SAP 过账：已确认');expect(host.textContent).toContain('业务投影：尚未完成');
});
it('limits OA target forms to currently permitted underlying business actions',async()=>{
 const p=props();p.project={...p.project,allowed_actions:['nonconformance.disposition']};await render(<SystemStepPanel {...p} context="quality" selected={null}/>);await choose('quality.oa-disposition');
 const select=host.querySelector('[aria-label="审批目标 类型"]') as HTMLSelectElement;
 expect([...select.options].map(o=>o.textContent)).toEqual(['quality']);
});

it('ignores a superseded exact fact response after changing project scope',async()=>{
 const p=props();let release!:(d:FactDetail)=>void;
 const source={system:'crm' as const,object_type:'demand',external_id:'old-project-demand',version:1};
 const old=new Promise<FactDetail>(resolve=>{release=resolve;});p.api.systemFact=vi.fn(()=>old);
 await render(<SystemFacts api={p.api} projectId="project-a" keys={[source]} onOpen={()=>{}}/>);
 await act(async()=>root.render(<SystemFacts api={p.api} projectId="project-b" keys={[]} onOpen={()=>{}}/>));
 await act(async()=>release({fact:{source,payload:{fact_type:'crm.demand'},evidence:'Old project evidence'},source_accepted:true} as FactDetail));
 expect(host.textContent).not.toContain('Old project evidence');expect(host.textContent).not.toContain('old-project-demand');
});
it('discovers unresolved original intent beyond the first metadata page before offering a new execute',async()=>{
 const p=props(),original='00000000-0000-4000-8000-000000000199';
 const entry={intent_id:original,project_id:p.project.id,system:'bi' as const,operation:'bi.refresh' as const,expected_version:1,phase:'unknown' as const,created_at:'2026-11-03T00:00:00Z',source_committed:null,receipt:null};
 vi.mocked(p.api.integrationIntents).mockImplementation(async(_id,limit=50,offset=0)=>({project_id:p.project.id,records:offset===0?Array.from({length:50},(_,i)=>({...entry,intent_id:String(i),phase:'applied' as const})):[entry],total:51,limit,offset}));
 await render(<SystemStepPanel {...p} context="home" selected={null}/>);
 expect(host.querySelector('button[type=submit]')).toBeNull();await click('查询原操作结果');
 expect(p.api.command).toHaveBeenCalledWith(p.project.id,expect.objectContaining({action:'mock_system.query',intent_id:original}));
});
it('binds the modeled physical accounting operation to its permitted account',async()=>{
 const p=props();await render(<SystemStepPanel {...p} context="handoff" selected={null}/>);await choose('handoff.sap-accounting');
 const input=host.querySelector('[aria-label="会计科目"]') as HTMLInputElement;
 expect(input?.value).toBe('raw-custody');expect(input.readOnly).toBe(true);
});

it('preserves the application read-only boundary on the home BI form',async()=>{
 const p=props();
 await render(<WorkflowHome api={p.api} data={null} projects={[p.project]} projectsReady dashboardError="" projectsError="" refresh={0} active={false} onRefresh={()=>{}} onOpen={()=>{}} onNavigate={()=>{}} readOnly/>);
 await act(async()=>{const select=host.querySelector('[aria-label="BI 项目"]') as HTMLSelectElement;select.value=p.project.id;select.dispatchEvent(new Event('change',{bubbles:true}));});
 expect(host.textContent).toContain('当前账号无此来源操作权限');expect(host.querySelector('form')).toBeNull();
});
