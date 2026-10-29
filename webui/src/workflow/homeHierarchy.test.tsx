import { act } from 'react';
import { expect, it, vi } from 'vitest';
import { workflowView, project, order, bootstrap, flush } from './testHelpers';
const task={category:'acceptance' as const,title:'验收问题需要处置',target:{...order,title:'TASK-EXACT'},owner_id:'owner',owner_name:'王工'};
it('renders four honest metrics, bounded actual priority items and exact destinations',async()=>{
 const v=await workflowView({readTasks:async(limit,offset)=>({items:[task],total:71,limit,offset,truncated:true}),readProjects:async()=>[{...project,quality_summary:{first_tested:0,first_passed:0,final_good:0,scrapped:0,open_nonconformances:2}}],readDashboard:async()=>({cards:[],counts:{work_order:8,unit:999},project_ids:[project.id],project_count:1})});
 try{
 expect(v.host.querySelectorAll('.wf-home-metric')).toHaveLength(4);
 expect(v.host.textContent).toContain('≥ 71');expect(v.host.textContent).toContain('下界');expect(v.host.textContent).toContain('王工');expect(v.host.textContent).not.toContain('999');
 await v.click('TASK-EXACT');expect(v.requests.some(r=>r.url.endsWith(`/projects/${project.id}/objects/order_line/${order.id}`))).toBe(true);
 await v.click('工作台');await v.click('未闭环不合格');expect(v.host.querySelector('button[aria-pressed="true"]')?.textContent).toBe('NCR');
 await v.click('工作台');await v.click('查看相机项目订单');expect((v.host.querySelector('[aria-label="所属项目筛选"]') as HTMLSelectElement).value).toBe(project.id);
 await v.click('工作台');await v.click('处理待办');expect(v.host.querySelector('nav [aria-current="page"]')?.textContent).toBe('事项');
 }finally{await v.dispose();}
});
it('does not mask missing quality, scope mismatch or in-flight metadata as zero',async()=>{
 const v=await workflowView({readProjects:async()=>[{...project,id:'mismatch'}]});
 try{const metrics=v.host.querySelectorAll('.wf-home-metric');expect(metrics).toHaveLength(4);expect(metrics[0].textContent).toContain('—');expect(metrics[2].textContent).toContain('—');expect(v.host.textContent).toContain('范围不一致');}finally{await v.dispose();}
});
it('keeps home tasks and shortcuts usable when dashboard fails, with explicit retry',async()=>{
 let failed=true;const v=await workflowView({readDashboard:async()=>{if(failed)throw Error('dashboard unavailable');return {cards:[],counts:{work_order:8},project_ids:[project.id],project_count:1};},readTasks:async(limit,offset)=>({items:[task],total:1,limit,offset,truncated:false})});
 try{expect(v.host.textContent).toContain('TASK-EXACT');expect(v.host.textContent).toContain('概览读取失败');failed=false;await v.click('重试读取概览');expect(v.host.querySelectorAll('.wf-home-metric')[3].textContent).toContain('8');await v.click('进入计划与物料');expect(v.host.querySelector('nav [aria-current="page"]')?.textContent).toBe('计划与物料');}finally{await v.dispose();}
});
it('shows task failure and retry independently, including read-only empty scope',async()=>{
 let failed=true;const v=await workflowView({options:{readOnly:true},readTasks:async(limit,offset)=>{if(failed)throw Error('task unavailable');return {items:[],total:0,limit,offset,truncated:false};}});
 try{expect(v.host.textContent).toContain('事项读取失败');failed=false;await v.click('重试读取事项');expect(v.host.textContent).toContain('当前读取范围内没有分配给你的待处理事项');expect(v.host.textContent).toContain('当前只读');}finally{await v.dispose();}
});
it.each(['module','identity','refresh','handbook'] as const)('aborts owned home tasks before a late 401 on %s',async(change)=>{
 const auth=vi.fn();const v=await workflowView({options:{onAuthError:auth}}),original=fetch;
 let finish!:(response:Response)=>void,signal:AbortSignal|undefined;let hold=true;
 await v.click('订单与交付');
 vi.stubGlobal('fetch',vi.fn((input,init)=>{if(hold&&String(input).includes('/workflow/tasks?')){hold=false;signal=init?.signal as AbortSignal;return new Promise<Response>(r=>finish=r);}return original(input,init);}));
 try{await v.click('工作台');expect(signal).toBeDefined();
 if(change==='module')await v.click('计划与物料');
 if(change==='handbook')await v.click('制造手册');
 if(change==='identity')await v.rerender({bootstrap:{...bootstrap,user:{id:'new-user',display_name:'新账号'}}});
 if(change==='refresh')await v.click('刷新工作台');
 expect(signal?.aborted).toBe(true);await act(async()=>finish(new Response('{}',{status:401})));await flush();expect(auth).not.toHaveBeenCalled();expect(v.host.textContent).not.toContain('无权访问');
 }finally{await v.dispose();}
});
it('withholds project metrics when refreshed list summaries predate a known project version',async()=>{
 const v=await workflowView({readProject:async()=>({...project,version:8})});
 try{await v.click('ORDER-001');await v.click('重新读取项目');await v.click('工作台');expect(v.host.textContent).toContain('项目资料版本已更新');expect(v.host.querySelectorAll('.wf-home-metric')[0].textContent).toContain('—');}finally{await v.dispose();}
});
it('clears former metrics while a refresh is pending and distinguishes a verified empty scope',async()=>{
 let pending=false;const v=await workflowView({readProjects:()=>pending?new Promise(()=>{}):Promise.resolve([]),readDashboard:()=>pending?new Promise(()=>{}):Promise.resolve({cards:[],counts:{work_order:0},project_ids:[],project_count:0})});
 try{expect(v.host.querySelectorAll('.wf-home-metric')[0].textContent).toContain('0');expect(v.host.textContent).toContain('当前授权范围暂无项目');pending=true;await v.click('刷新工作台');expect(v.host.querySelectorAll('.wf-home-metric')[0].textContent).toContain('—');expect(v.host.textContent).toContain('正在读取项目资料');}finally{await v.dispose();}
});
