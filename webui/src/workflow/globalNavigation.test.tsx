import { act } from 'react';
import { expect, it, vi } from 'vitest';
import { workflowView, project, order, bootstrap, flush } from './testHelpers';
import type { ObjectKind, ObjectPage, ObjectDetail } from './types';

const other = {...project, id:'00000000-0000-4000-8000-000000000009', name:'雷达项目', customer_id:'客户乙', product:'雷达'};
const privateProject = {...project, id:'private-project', name:'私有项目'};
const rows = (kind: ObjectKind) => [project, other, privateProject].map((p, i) => ({...order, id:`${kind}-${i}`, project_id:p.id, kind, title:`${kind}-业务-${i}`, source:{...order.source!, external_id:`SOURCE-${i}`}}));
function visiblePage(kind: ObjectKind, limit: number, offset: number, projectId?: string): ObjectPage {
  const visible = rows(kind).filter(r => r.project_id !== privateProject.id && (!projectId || r.project_id === projectId));
  return {items:visible.slice(offset, offset+limit), total:visible.length, limit, offset};
}
const configuration = {readProjects:async()=>[project, other], readLedger:vi.fn(async (kind:ObjectKind, limit:number, offset:number, projectId?:string)=>visiblePage(kind,limit,offset,projectId))};
it.each([
  ['订单与交付','order_line','订单编号'], ['计划与物料','requirement','物料需求编号'],
  ['工单与执行','work_order','工单编号'], ['质量与追溯','test','检验测试编号'], ['系统协同','exchange','交换编号'],
] as const)('fresh %s opens actual cross-project %s records, not a project entrance',async(module,kind,column)=>{
 const v=await workflowView(configuration);
 try {await v.click(module);
  expect(v.host.querySelector('table')?.textContent).toContain(column);
  expect(v.host.textContent).toContain(`${kind}-业务-0`); expect(v.host.textContent).toContain(`${kind}-业务-1`);
  expect(v.host.textContent).toContain('SOURCE-1'); expect(v.host.textContent).toContain('客户乙');
  expect(v.host.textContent).not.toContain(`${kind}-业务-2`); expect(v.host.textContent).not.toContain('私有项目');
  expect(v.host.querySelector('table')?.textContent).not.toContain('项目名称');
  expect(v.requests.some(r=>r.url.includes(`/workflow/objects/${kind}?`))).toBe(true);
  expect(v.requests.some(r=>r.url.includes(`/projects/${project.id}/objects/`))).toBe(false);
  expect([...v.host.querySelectorAll('button')].some(b=>b.textContent==='新建项目')).toBe(false);
 }finally{await v.dispose();}
});
it('shows bounded actor tasks immediately, with responsibility and exact target',async()=>{
 const v=await workflowView({...configuration,readTasks:async(limit,offset)=>({items:[{category:'acceptance',title:'签收问题',target:order,owner_id:'owner',owner_name:'王工'}],total:51,limit,offset,truncated:true})});
 try{await v.click('事项');expect(v.host.textContent).toContain('可用事项 51');expect(v.host.textContent).toContain('每项目');expect(v.host.textContent).toContain('王工');
 await v.click('ORDER-001');expect(v.requests.some(r=>r.url.endsWith(`/projects/${project.id}/objects/order_line/${order.id}`))).toBe(true);
 expect(v.host.querySelector('nav [aria-current="page"]')?.textContent).toBe('事项');await v.click('返回业务列表');expect(v.host.textContent).toContain('签收问题');
 }finally{await v.dispose();}
});
it('retains tab, project filter and page through exact record drilldown and return',async()=>{
 const readLedger=vi.fn(async(kind:ObjectKind,limit:number,offset:number,projectId?:string)=>({items:[{...order,kind,project_id:other.id,title:`PAGE-${offset}`}],total:75,limit,offset}));
 const v=await workflowView({...configuration,readLedger,readObject:async(projectId,kind,id)=>({summary:{...order,project_id:projectId,kind,id,title:'EXACT DEMAND'},value:{kind:'demand',demand_kind:'firm',product:other.product,quantity:'2',unit:'件',due_date:'2026-11-04',source:order.source!,supersedes_demand_id:null,reviews:{}},relations:[],history:[],evidence:[]})});
 const original=fetch;vi.stubGlobal('fetch',vi.fn(async(input,init)=>String(input).endsWith('/projects/'+other.id)?new Response(JSON.stringify(other)):original(input,init)));
 try{await v.click('订单与交付');await v.click('需求');await v.field('所属项目筛选',other.id);await v.click('下一页');await v.click('PAGE-50');
 expect(v.requests.some(r=>r.url.endsWith(`/projects/${other.id}/objects/demand/${order.id}`))).toBe(true);
 expect(v.host.querySelector('nav [aria-current="page"]')?.textContent).toBe('订单与交付');expect(v.host.textContent).toContain('EXACT DEMAND');
 await v.click('返回业务列表');expect(v.host.textContent).toContain('PAGE-50');expect((v.host.querySelector('[aria-label="所属项目筛选"]') as HTMLSelectElement).value).toBe(other.id);
 expect(readLedger).toHaveBeenLastCalledWith('demand',50,50,other.id);expect(v.host.querySelector('button[aria-pressed="true"]')?.textContent).toBe('需求');
 await v.click('制造项目');expect(v.host.querySelector('table')?.textContent).toContain('项目');
 }finally{await v.dispose();}
});
it('ignores an obsolete global response after changing tabs or identity',async()=>{
 let finish!:(p:ObjectPage)=>void; const slow = new Promise<ObjectPage>(r=>finish=r);
 const v=await workflowView({...configuration,readLedger:async(kind,limit,offset)=>kind==='order_line'?slow:visiblePage(kind,limit,offset)});
 try{await v.click('订单与交付');await v.click('需求');expect(v.host.textContent).toContain('demand-业务-0');
 await act(async()=>finish(visiblePage('order_line',50,0)));await flush();expect(v.host.textContent).not.toContain('order_line-业务-0');
 await v.rerender({bootstrap:{...bootstrap,user:{id:'new-user',display_name:'新账号'}}});expect(v.host.textContent).not.toContain('demand-业务-0');
 }finally{await v.dispose();}
});
it('offers trace via explicit project dropdown, and sidebar navigation always returns to global scope',async()=>{
 const v=await workflowView(configuration);try{await v.click('质量与追溯');await v.field('所属项目筛选',project.id);await v.click('追溯查询');expect(v.host.textContent).toContain('追溯');
 await v.click('订单与交付');expect(v.host.textContent).toContain('order_line-业务-1');expect(v.host.querySelector('[aria-label="所属项目筛选"]')).not.toBeNull();
 }finally{await v.dispose();}
});
it('shows an explicit unavailable state without legacy fallback or product switching',async()=>{
 const v=await workflowView({options:{bootstrap:{...bootstrap,workflow_available:false,legacy_access:true}}});
 try{expect(v.host.querySelector('[role="alert"]')?.textContent).toContain('不可用');expect(v.host.textContent).not.toContain('旧项目协同');expect(v.requests).toHaveLength(0);}finally{await v.dispose();}
});
it('clears stale records during loading, retries errors and shows a truthful empty page',async()=>{
 let fail=false,empty=false;
 const v=await workflowView({...configuration,readLedger:async(kind,limit,offset)=>{if(fail)throw Error('unavailable');return empty?{items:[],total:0,limit,offset}:visiblePage(kind,limit,offset);}});
 try{await v.click('订单与交付');expect(v.host.textContent).toContain('订单合计 2 条');fail=true;await v.click('刷新台账');expect(v.host.querySelector('[role="alert"]')).not.toBeNull();expect(v.host.textContent).not.toContain('order_line-业务-0');
 fail=false;empty=true;await v.click('重试读取台账');expect(v.host.textContent).toContain('订单合计 0 条');expect(v.host.textContent).toContain('当前范围暂无订单记录');
 }finally{await v.dispose();}
});
it('global project actions retain dirty drafts through handbook and guard a sidebar change',async()=>{
 const v=await workflowView({...configuration,initial:'订单与交付'});
 try{await v.click('需求');await v.field('所属项目筛选',project.id);await v.click('进入项目办理');await v.click('登记需求');await v.field('产品','global draft');await v.click('制造手册');await v.click('返回工作区');expect((v.host.querySelector('[aria-label="产品"]') as HTMLInputElement).value).toBe('global draft');
 await v.click('计划与物料');expect(v.host.querySelectorAll('[role="dialog"]')).toHaveLength(1);await v.click('继续编辑');expect((v.host.querySelector('[aria-label="产品"]') as HTMLInputElement).value).toBe('global draft');
 await v.click('返回台账');await v.click('放弃并离开');expect(v.host.querySelector('button[aria-pressed="true"]')?.textContent).toBe('需求');expect((v.host.querySelector('[aria-label="所属项目筛选"]') as HTMLSelectElement).value).toBe(project.id);
 }finally{await v.dispose();}
});
it('aborts a pending global read and cannot restore rows after an account change or revocation',async()=>{
 let finish!:(p:ObjectPage)=>void;let signal:AbortSignal|null|undefined;
 const pending=new Promise<ObjectPage>(r=>finish=r);
 const auth=vi.fn(),v=await workflowView({...configuration,readLedger:async()=>pending,options:{onAuthError:auth}});
 const original=fetch;vi.stubGlobal('fetch',vi.fn((input,init)=>{if(String(input).includes('/workflow/objects/'))signal=init?.signal;return original(input,init);}));
 try{await v.click('订单与交付');await v.rerender({bootstrap:{...bootstrap,user:{id:'next-identity',display_name:'第二账号'}}});expect(signal?.aborted).toBe(true);
 await act(async()=>finish(visiblePage('order_line',50,0)));await flush();expect(v.host.textContent).not.toContain('order_line-业务-0');
 vi.stubGlobal('fetch',vi.fn(async(input,init)=>String(input).includes('/workflow/objects/')?new Response('{}',{status:403}):original(input,init)));
 await v.click('订单与交付');expect(auth).toHaveBeenCalledTimes(1);expect(v.host.textContent).toContain('无权访问');expect(v.host.textContent).not.toContain('雷达项目');
 }finally{await v.dispose();}
});
it('read-only global drilldown never exposes a write action',async()=>{
 const v=await workflowView({options:{readOnly:true}});try{await v.click('订单与交付');await v.click('ORDER-001');expect(v.host.textContent).toContain('当前只读');expect([...v.host.querySelectorAll('button')].some(b=>b.textContent?.startsWith('前往处理：'))).toBe(false);expect(v.host.querySelector('form')).toBeNull();}finally{await v.dispose();}
});
it.each(['shipment','release'] as const)('opens the exact %s from the second project and returns to its module tab',async(kind)=>{
 const summary={...order,project_id:other.id,kind,title:kind+'-SECOND-PROJECT'};
 const value: ObjectDetail['value'] = kind==='shipment'?{kind:'shipment',id:summary.id,order_line_id:order.id,unit_ids:['unit'],exchange_id:'exchange',quantity:'1',state:'accepted',shipped:'1',unit:'件',signed:'0',accepted:'0',remaining:{ordered:'2',allocated:'2',qualified:'2',pending_shipment:'0',shipped:'1',signed:'0',accepted:'0',remaining_to_ship:'1',remaining_to_accept:'2',unit:'件'},blocking_reasons:[],boxes:[],facts:[],issues:[]}:{kind:'release',id:summary.id,release_kind:'quality',unit_ids:['unit'],decision:'approved',evidence:'Second project quality evidence',test_ids:[],actor_id:'quality-owner',customer_id:other.customer_id,revision_id:null,customer_revision:null,external_signatory:null,method:null,source:null,recorded_at:'2026-10-29'};
 const readObject=vi.fn(async(projectId:string,requestedKind:ObjectKind,id:string)=>({summary,value,relations:[],history:[],evidence:[]}));
 const v=await workflowView({...configuration,readLedger:async(requested,limit,offset)=>({items:requested===kind?[summary]:[],total:requested===kind?1:0,limit,offset}),readObject});
 const original=fetch;vi.stubGlobal('fetch',vi.fn(async(input,init)=>String(input).endsWith('/projects/'+other.id)?new Response(JSON.stringify(other)):original(input,init)));
 try{await v.click(kind==='shipment'?'订单与交付':'质量与追溯');await v.click(kind==='shipment'?'发货':'放行');await v.click(summary.title);
 expect(readObject).toHaveBeenCalledWith(other.id,kind,summary.id);expect(v.host.textContent).toContain(kind==='shipment'?'实际发出':'Second project quality evidence');
 await v.click('返回业务列表');expect(v.host.querySelector('button[aria-pressed="true"]')?.textContent).toBe(kind==='shipment'?'发货':'放行');expect(v.host.textContent).toContain(summary.title);
 }finally{await v.dispose();}
});
it('refreshes the retained global context and quantities after a project form command',async()=>{
 let saved=false;
 const summary=()=>({...order,kind:'demand' as const,title:'SAVED-DEMAND',quantity:saved?'3':'2'});
 const v=await workflowView({...configuration,readLedger:async(kind,limit,offset)=>({items:kind==='demand'?[summary()]:[],total:kind==='demand'?1:0,limit,offset}),readObject:async()=>({summary:summary(),value:{kind:'demand',demand_kind:'firm',product:project.product,quantity:'3',unit:'件',due_date:'2026-11-04',source:order.source!,supersedes_demand_id:null,reviews:{}},relations:[],history:[],evidence:[]})});
 const original=fetch;vi.stubGlobal('fetch',vi.fn(async(input,init)=>{if(String(input).endsWith('/commands')){saved=true;return new Response(JSON.stringify({project_id:project.id,project_version:4,object_type:'demand',object_id:order.id,operation_id:'saved',status:'accepted'}));}return original(input,init);}));
 try{await v.click('订单与交付');await v.click('需求');await v.field('所属项目筛选',project.id);await v.click('进入项目办理');await v.click('登记需求');await v.field('产品','真实命令草稿');await v.field('需求数量','3');await v.field('需求交期','2026-11-04');await v.field('来源业务编号','SAVED-DEMAND');await v.field('来源凭据','Signed source');await v.click('保存需求');
 expect(saved).toBe(true);await v.click('返回业务列表');expect(v.host.querySelector('button[aria-pressed="true"]')?.textContent).toBe('需求');expect((v.host.querySelector('[aria-label="所属项目筛选"]') as HTMLSelectElement).value).toBe(project.id);expect(v.host.querySelector('tbody tr')?.textContent).toContain('3 件');
 }finally{await v.dispose();}
});
it('does not carry a previous project action target into another project chosen from the ledger',async()=>{
 const v=await workflowView(configuration);const original=fetch;
 vi.stubGlobal('fetch',vi.fn(async(input,init)=>String(input).endsWith('/projects/'+other.id)?new Response(JSON.stringify(other)):original(input,init)));
 try{await v.click('订单与交付');await v.click('order_line-业务-0');await v.click('前往处理：发货申请');expect(v.host.textContent).toContain('当前事项：ORDER-001');
 await v.click('返回台账');await v.field('所属项目筛选',other.id);await v.click('进入项目办理');expect(v.host.textContent).not.toContain('当前事项：ORDER-001');expect(v.host.textContent).toContain(other.name);
 }finally{await v.dispose();}
});
it('distinguishes an empty page after totals shrink from an empty project scope',async()=>{
 const v=await workflowView({...configuration,readLedger:async(kind,limit,offset)=>({items:offset?[]:rows(kind).slice(0,1),total:offset?1:60,limit,offset})});
 try{await v.click('订单与交付');await v.click('下一页');expect(v.host.textContent).toContain('订单合计 1 条');expect(v.host.textContent).toContain('当前页暂无订单记录');expect(v.host.textContent).not.toContain('当前范围暂无订单记录');await v.click('上一页');expect(v.host.textContent).toContain('order_line-业务-0');}finally{await v.dispose();}
});

it.each([['tab',401],['filter',403],['module',403],['tasks',401]] as const)('retires a global read on %s change before a late %s can erase current work',async(change,status)=>{
 const auth=vi.fn(),v=await workflowView({...configuration,options:{onAuthError:auth}});
 let finish!:(v:Response)=>void;let signal:AbortSignal|null|undefined;
 const original=fetch;let pending=true;
 vi.stubGlobal('fetch',vi.fn((input,init)=>{if(pending && String(input).includes(change==='tasks'?'/workflow/tasks?':'/workflow/objects/order_line?')){pending=false;signal=init?.signal;return new Promise<Response>(r=>finish=r);}return original(input,init);}));
 try{await v.click(change==='tasks'?'事项':'订单与交付');
 if(change==='tab')await v.click('需求');
 if(change==='filter')await v.field('所属项目筛选',project.id);
 if(change==='module'||change==='tasks'){await v.click('计划与物料');}
 const aborted=signal?.aborted;
 await v.click('订单与交付');await v.field('所属项目筛选',project.id);await v.click('进入项目办理');await v.click('登记需求');await v.field('产品','retained draft');
 await act(async()=>finish(new Response('{}',{status})));await flush();
 expect(auth).not.toHaveBeenCalled();expect(aborted).toBe(true);expect((v.host.querySelector('[aria-label="产品"]') as HTMLInputElement)?.value).toBe('retained draft');
 }finally{await v.dispose();}
});
it.each(['deferred','failed'] as const)('loads metadata and opens real rows while dashboard is %s',async(mode)=>{
 const v=await workflowView({...configuration,readDashboard:()=>mode==='deferred'?new Promise(()=>{}):Promise.reject(Error('dashboard unavailable'))});
 try{await v.click('订单与交付');expect(v.host.textContent).toContain('客户乙');await v.click('order_line-业务-0');expect(v.host.textContent).toContain('原始承诺数量');expect(v.requests.some(r=>r.url.endsWith(`/projects/${project.id}/objects/order_line/order_line-0`))).toBe(true);}finally{await v.dispose();}
});
it.each(['deferred','failed'] as const)('resolves exact row project when project list is %s',async(mode)=>{
 let finish!:(p:typeof project)=>void;const exact=new Promise<typeof project>(r=>finish=r);
 const v=await workflowView({...configuration,readProjects:()=>mode==='deferred'?new Promise(()=>{}):Promise.reject(Error('list unavailable')),readProject:()=>exact});
 try{await v.click('订单与交付');await v.click('order_line-业务-0');expect(v.host.textContent).toContain('正在读取记录所属项目');
 await act(async()=>finish(project));await flush();expect(v.requests.some(r=>r.url.endsWith(`/projects/${project.id}/objects/order_line/order_line-0`))).toBe(true);
 await v.click('返回业务列表');expect(v.host.querySelector('nav [aria-current="page"]')?.textContent).toBe('订单与交付');}finally{await v.dispose();}
});
it('shows exact project read failure and supports retry',async()=>{
 let fail=true;const v=await workflowView({...configuration,readProjects:async()=>[],readProject:async()=>{if(fail)throw Error('exact unavailable');return project;}});
 try{await v.click('订单与交付');await v.click('order_line-业务-0');expect(v.host.querySelector('[role="alert"]')?.textContent).toContain('exact unavailable');fail=false;await v.click('重试打开记录');expect(v.requests.some(r=>r.url.endsWith(`/projects/${project.id}/objects/order_line/order_line-0`))).toBe(true);}finally{await v.dispose();}
});
it.each(['module','identity','row','handbook'] as const)('cancels obsolete exact project resolution on %s change',async(change)=>{
 let finish!:(r:Response)=>void;let signal:AbortSignal|null|undefined;
 const v=await workflowView({...configuration,readProjects:async()=>[]});const original=fetch;
 vi.stubGlobal('fetch',vi.fn((input,init)=>{if(String(input).endsWith('/projects/'+project.id)){signal=init?.signal;return new Promise<Response>(r=>finish=r);}if(String(input).endsWith('/projects/'+other.id))return Promise.resolve(new Response(JSON.stringify(other)));return original(input,init);}));
 try{await v.click('订单与交付');await v.click('order_line-业务-0');expect(v.host.textContent).toContain('正在读取记录所属项目');
 if(change==='module')await v.click('计划与物料');if(change==='identity')await v.rerender({bootstrap:{...bootstrap,user:{id:'new',display_name:'new'}}});if(change==='row')await v.click('order_line-业务-1');if(change==='handbook')await v.click('制造手册');
 expect(signal?.aborted).toBe(true);await act(async()=>finish(new Response(JSON.stringify(project))));await flush();
 expect(v.requests.some(r=>r.url.endsWith(`/projects/${project.id}/objects/order_line/order_line-0`))).toBe(false);
 if(change==='row')expect(v.host.textContent).toContain(other.name);else expect(v.host.textContent).not.toContain('返回业务列表');
 }finally{await v.dispose();}
});
it('aborts a ledger read when its owner changes offset or unmounts',async()=>{
 const {createRoot}=await import('react-dom/client');const {GlobalLedger}=await import('./GlobalLedger');const {createWorkflowApi}=await import('./api');
 const signals:AbortSignal[]=[];const finishes:Array<(r:Response)=>void>=[];const auth=vi.fn();
 vi.stubGlobal('fetch',vi.fn((_input,init)=>{signals.push(init.signal);return new Promise<Response>(r=>finishes.push(r));}));
 const api=createWorkflowApi({apiBase:'/api/v1/manufacturing',csrfToken:'csrf',readOnly:false},auth),host=document.createElement('div'),root=createRoot(host);
 const render=(offset:number)=><GlobalLedger api={api} module="orders" context={{kind:'order_line',projectId:'',offset}} onContext={()=>{}} projects={[]} refresh={0} onRefresh={()=>{}} onOpen={()=>{}} onProject={()=>{}}/>;
 try{await act(async()=>root.render(render(0)));await act(async()=>root.render(render(50)));expect(signals[0].aborted).toBe(true);expect(signals[1].aborted).toBe(false);
 await act(async()=>root.unmount());expect(signals[1].aborted).toBe(true);await act(async()=>finishes.forEach(f=>f(new Response('{}',{status:403}))));expect(auth).not.toHaveBeenCalled();}finally{api.dispose();vi.unstubAllGlobals();}
});
it('aborts superseded root metadata and project reads before late revocation',async()=>{
 const auth=vi.fn(),v=await workflowView({...configuration,options:{onAuthError:auth}}),original=fetch;
 const pending:Array<{signal:AbortSignal,finish:(r:Response)=>void}>=[];let hold=true;
 vi.stubGlobal('fetch',vi.fn((input,init)=>{if(hold&&(/\/(projects|dashboard)$/.test(String(input))||String(input).endsWith('/projects/'+project.id)))return new Promise<Response>(finish=>pending.push({signal:init!.signal as AbortSignal,finish}));return original(input,init);}));
 try{await v.click('订单与交付');await v.click('刷新台账');expect(pending).toHaveLength(2);hold=false;await v.click('刷新台账');expect(pending.every(r=>r.signal.aborted)).toBe(true);
 hold=true;await v.field('所属项目筛选',project.id);await v.click('进入项目办理');expect(pending).toHaveLength(3);hold=false;await v.click('返回台账');expect(pending[2].signal.aborted).toBe(true);
 await act(async()=>pending.forEach(p=>p.finish(new Response('{}',{status:401}))));await flush();expect(auth).not.toHaveBeenCalled();expect(v.host.textContent).toContain('order_line-业务-0');}finally{await v.dispose();}
});
it('refuses an exact project response older than independently arrived metadata',async()=>{
 let list!:(p:typeof project[])=>void,exact!:(p:typeof project)=>void;
 const v=await workflowView({...configuration,readProjects:()=>new Promise(r=>list=r),readProject:()=>new Promise(r=>exact=r)});
 try{await v.click('订单与交付');await v.click('order_line-业务-0');await act(async()=>list([{...project,version:8}]));await flush();await act(async()=>exact(project));await flush();
 expect(v.host.textContent).toContain('项目版本已更新');expect(v.host.textContent).not.toContain('返回业务列表');
 await v.click('重试打开记录');expect(v.requests.some(r=>r.url.endsWith(`/projects/${project.id}/objects/order_line/order_line-0`))).toBe(true);
 }finally{await v.dispose();}
});
