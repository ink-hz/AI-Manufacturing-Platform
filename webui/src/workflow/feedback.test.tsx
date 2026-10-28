import {afterEach,expect,it,vi} from 'vitest';
import {createWorkflowApi} from './api';

afterEach(()=>vi.unstubAllGlobals());
it('sends a bounded scoped SN or lot trace search through the common authenticated API',async()=>{
 const fetcher=vi.fn(async(_url:string)=>new Response(JSON.stringify({nodes:[],edges:[],truncated:false}),{status:200}));vi.stubGlobal('fetch',fetcher);
 const api=createWorkflowApi({apiBase:'/api/v1/manufacturing',csrfToken:'csrf',readOnly:false} as any);
 await (api.trace as any)('project',{sn:'SN / 001'},25);
 expect(fetcher.mock.calls[0][0]).toBe('/api/v1/manufacturing/workflow/projects/project/trace?sn=SN+%2F+001&limit=25');
});

import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {FeedbackForms} from './forms/FeedbackForms';
import {TraceWorkspace} from './TraceWorkspace';
import {WorkflowError} from './api';
const id='00000000-0000-4000-8000-000000000001';
const item=(kind:string)=>({id,kind,project_id:id,title:kind==='unit'?'SN-001':'Lot-001',state:'active',quantity:null,unit:null,version:1,blocking_reasons:[],next_actions:[]});
const project={id,version:7,allowed_actions:['freeze.request','capa.update'],unit:{code:'piece',scale:0}} as any;
async function input(host:HTMLElement,name:string,value:string){const e=host.querySelector(`[aria-label="${name}"]`) as HTMLInputElement;expect(e).toBeTruthy();await act(async()=>{Object.getOwnPropertyDescriptor(e.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype,'value')!.set!.call(e,value);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));});}
async function click(host:HTMLElement,text:string){const e=[...host.querySelectorAll('button')].find(b=>b.textContent===text);expect(e,text).toBeTruthy();await act(async()=>e!.click());}
it('keeps a freeze draft and canonical operation after conflict using current project CAS',async()=>{
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host),command=vi.fn().mockRejectedValue(new WorkflowError(409,'VERSION_CONFLICT',['Current 8'])),dirty=vi.fn();
 try{await act(async()=>root.render(<FeedbackForms {...{project,api:{command} as any,onChanged:vi.fn(),onOpen:vi.fn(),onDirty:dirty,readOnly:false,action:'freeze.request',units:[item('unit')] as any,lots:[],shipments:[],ecos:[],rma:null,capa:null,shipment:null,step:'containment',selectedUnits:[id],selectedLots:[]}}/>));await input(host,'冻结或解冻原因','Human containment investigation');await click(host,'提交冻结状态申请');await click(host,'提交冻结状态申请');expect(command.mock.calls[0][1]).toMatchObject({action:'freeze.request',expected_version:7,unit_ids:[id],lot_ids:[],state:'frozen',reason:'Human containment investigation'});expect(command.mock.calls[1][1]).toEqual(command.mock.calls[0][1]);expect((host.querySelector('[aria-label="冻结或解冻原因"]') as HTMLInputElement).value).toBe('Human containment investigation');expect(dirty).toHaveBeenCalledWith('冻结与解冻申请',true);}finally{await act(async()=>root.unmount());host.remove();}
});
it('renders bounded navigable trace and passes affected serials to the freeze form',async()=>{
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host),open=vi.fn(),trace=vi.fn(async()=>({nodes:[{...item('unit'),customer_id:null}],edges:[],truncated:true}));
 const api={trace,objects:vi.fn(async()=>({items:[],total:0,offset:0,limit:50}))} as any;
 try{await act(async()=>root.render(<TraceWorkspace project={project} api={api} onOpen={open} onChanged={vi.fn()} onDirty={vi.fn()} readOnly={false} requestLeave={f=>f()}/>));await input(host,'追溯序列号','SN-001');await click(host,'查询追溯');expect(trace).toHaveBeenCalledWith(id,{sn:'SN-001'},500);expect(host.textContent).toContain('结果已截断');await click(host,'SN-001');expect(open).toHaveBeenCalledWith({projectId:id,kind:'unit',id});await click(host,'冻结或解冻受影响范围');expect((host.querySelector('input[type="checkbox"]') as HTMLInputElement).checked).toBe(true);}finally{await act(async()=>root.unmount());host.remove();}
});
it('records supplier implementation and human evidence without forcing an ECO',async()=>{
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host),command=vi.fn().mockRejectedValue(new WorkflowError(409));
 try{await act(async()=>root.render(<FeedbackForms {...{project,api:{command} as any,onChanged:vi.fn(),onOpen:vi.fn(),onDirty:vi.fn(),readOnly:false,action:'capa.update',units:[],lots:[],shipments:[],ecos:[],rma:{id} as any,capa:{id,rma_id:id} as any,shipment:null,step:'correction',selectedUnits:[],selectedLots:[]}}/>));await input(host,'纠正措施说明','Supplier changed its inspection process');await input(host,'实际证据','Signed investigation');await input(host,'纠正措施类型','supplier');await input(host,'本措施实际实施凭据','Supplier implementation report');await click(host,'保存纠正措施证据');expect(command.mock.calls[0][1]).toMatchObject({action:'capa.update',step:'correction',rma_id:id,capa_id:id,action_kind:'supplier',eco_id:null,implementation_evidence:'Supplier implementation report',evidence:'Signed investigation'});}finally{await act(async()=>root.unmount());host.remove();}
});

import {ExchangeWorkspace} from './ExchangeWorkspace';
it('dispatches a selected freeze exchange through the real common exchange form',async()=>{
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host),command=vi.fn().mockRejectedValue(new WorkflowError(409));
 const api={command,objects:vi.fn(async()=>({items:[item('exchange')],total:1,limit:50,offset:0})),object:vi.fn(async()=>({summary:{...item('exchange'),next_actions:['exchange.dispatch']},value:{kind:'exchange',action:'freeze.request',policy_action:'freeze.request',phase:'requested',requested:'0',accepted:'0',unit:'',reason:''}}))} as any;
 try{await act(async()=>root.render(<ExchangeWorkspace project={{...project,allowed_actions:['exchange.dispatch','freeze.request']}} api={api} onOpen={vi.fn()} onChanged={vi.fn()} onDirty={vi.fn()} readOnly={false} requestLeave={f=>f()} mode="test"/>));await click(host,'发送权威请求');await input(host,'待处理交换',id);await click(host,'查询后发送原请求');expect(command).toHaveBeenCalledWith(id,expect.objectContaining({action:'exchange.dispatch',exchange_id:id,expected_version:7}));}finally{await act(async()=>root.unmount());host.remove();}
});
it('uses selected server exchange capabilities without a frontend underlying-action catalogue',async()=>{
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host),command=vi.fn(async()=>({project_id:id,project_version:8,object_type:'exchange',object_id:id}));
 const api={command,objects:vi.fn(async()=>({items:[item('exchange')],total:1,limit:50,offset:0})),object:vi.fn(async()=>({summary:{...item('exchange'),next_actions:['exchange.dispatch']},value:{kind:'exchange',action:'new.registered.source_action',policy_action:'new.registered.source_action',phase:'requested',requested:'1',accepted:'0',unit:'piece',reason:''}}))} as any;
 try{await act(async()=>root.render(<ExchangeWorkspace project={{...project,allowed_actions:['exchange.dispatch']}} api={api} onOpen={vi.fn()} onChanged={vi.fn()} onDirty={vi.fn()} readOnly={false} requestLeave={f=>f()} mode="test"/>));await click(host,'发送权威请求');await input(host,'待处理交换',id);await click(host,'查询后发送原请求');expect(command).toHaveBeenCalledTimes(1);}finally{await act(async()=>root.unmount());host.remove();}
});
