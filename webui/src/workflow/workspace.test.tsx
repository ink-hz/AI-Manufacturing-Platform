import { ActionForms } from './ActionForms';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { EngineeringForms } from './forms/EngineeringForms';
import { project, order, bootstrap } from './testHelpers';
import { it, expect, vi } from 'vitest';
import { workflowView, flush } from './testHelpers';
import type { ProjectDetail } from './types';
it('offers eleven ordinary-member workspaces with real project context and one current action', async () => {
    const v = await workflowView();
    try {
        const nav = v.host.querySelector('nav[aria-label="制造工作区"]')!;
        expect([...nav.querySelectorAll('button')].map(b => b.textContent)).toEqual(['工作台', '制造项目', '订单与交付', '工程与资产', '测试与标定', '计划与物料', '工单与执行', '质量与追溯', '事项', '系统协同', '制造手册']);
        await v.click('订单与交付');
        await v.field('所属项目筛选', project.id);
        await v.click('进入项目办理');
        expect(v.host.textContent).toContain('待发 2');
        await v.click('登记需求');
        expect(v.host.querySelectorAll('form')).toHaveLength(1);
        expect(v.host.querySelector('textarea')).toBeNull();
    }
    finally {
        await v.dispose();
    }
});
it('drills a home card into the same owned detail and preserves manual source badge', async () => {
    const v = await workflowView();
    try {
        await v.click('ORDER-001');
        expect(v.requests.some(r => r.url.endsWith('/objects/order_line/00000000-0000-4000-8000-000000000003'))).toBe(true);
        expect(v.host.textContent).toContain('人工登记');
        expect(v.host.textContent).toContain('独立测试');
    }
    finally {
        await v.dispose();
    }
});
it('uses bounded revision family summaries without one detail read per option', async () => {
    const host = document.createElement('div'), root = createRoot(host), lookup = vi.fn(async () => { throw Error('per-option lookup forbidden'); });
    document.body.append(host);
    try {
        await act(async () => root.render(<EngineeringForms project={project} api={{ object: lookup } as any} action="engineering.revision" onOpen={() => { }} onDirty={() => { }} onChanged={() => { }} readOnly={false} orders={[]} workOrders={[]} revisions={Array.from({ length: 50 }, (_, i) => ({ ...order, id: String(i), kind: 'revision', title: 'Package ' + i, revision_family_id: 'family-' + i }))}/>));
        expect(lookup).not.toHaveBeenCalled();
        expect(host.querySelectorAll('[aria-label="资料系列"] option')).toHaveLength(51);
    }
    finally {
        await act(async () => root.unmount());
        host.remove();
    }
});
it('opens an authorized contextual action in its operational workspace', async () => {
    const v = await workflowView();
    try {
        await v.click('ORDER-001');
        await v.click('前往处理：发货申请');
        expect(v.host.textContent).toContain('当前事项：ORDER-001');
        expect(v.host.textContent).toContain('交付、所有权与独立关闭');
        expect(v.host.querySelectorAll('form')).toHaveLength(0);
    }
    finally {
        await v.dispose();
    }
});
it('preserves a stage hint draft when its disclosure is collapsed', async () => {
    const host = document.createElement('div'), root = createRoot(host);
    document.body.append(host);
    try {
        await act(async () => root.render(<ActionForms project={{ ...project, allowed_actions: ['project.stage'] }} api={{} as any} onDirty={() => { }} onChanged={() => { }} onOpen={() => { }} readOnly={false}/>));
        const details = host.querySelector('details')!;
        await act(async () => { details.open = true; details.dispatchEvent(new Event('toggle')); });
        const input = host.querySelector('[aria-label="阶段说明"]') as HTMLInputElement;
        await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'Unfinished collaboration note'); input.dispatchEvent(new Event('input', { bubbles: true })); });
        await act(async () => { details.open = false; details.dispatchEvent(new Event('toggle')); });
        await act(async () => { details.open = true; details.dispatchEvent(new Event('toggle')); });
        expect((host.querySelector('[aria-label="阶段说明"]') as HTMLInputElement).value).toBe('Unfinished collaboration note');
    }
    finally {
        await act(async () => root.unmount());
        host.remove();
    }
});
const selectedProject = (version = 3): ProjectDetail => ({ ...project, version, progress: { stages: [], blocking_objects: [order], blockers_truncated: false, fulfillment: { status: 'blocked', recorded_count: 0, blocking_reasons: [`Current fulfillment ${version}`] }, quality: { status: 'ready', recorded_count: 0, blocking_reasons: [] }, cost: { status: 'ready', recorded_count: 0, blocking_reasons: [] } }, tasks: [{ category: 'acceptance', title: `Owned issue ${version}`, owner_id: 'owner-id', owner_name: 'Responsible engineer', target: order }], tasks_truncated: false });
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(r => resolve = r); return { promise, resolve }; };
it('loads current project progress when opening an owned global task', async () => {
    const readProject = vi.fn(async () => selectedProject());
    const v = await workflowView({ initial: '事项', readProject, readTasks: async(limit,offset)=>({items:selectedProject().tasks!,total:1,limit,offset,truncated:false}) });
    try {
        expect(v.host.textContent).toContain('Owned issue 3');
        await v.click('ORDER-001');
        expect(v.host.querySelector('[aria-label="实际业务进展"]')).not.toBeNull();
        expect(v.host.textContent).toContain('Current fulfillment 3');
        expect(readProject).toHaveBeenCalledTimes(1);
    }
    finally {
        await v.dispose();
    }
});
it('preserves selected progress when an equal-version list finishes after detail', async () => {
    const list = deferred<ProjectDetail[]>();
    let lists = 0;
    const v = await workflowView({ initial: '制造项目', readProjects: async () => ++lists === 1 ? [project] : list.promise, readProject: async () => selectedProject() });
    try {
        await v.click('重新读取项目');
        expect(v.host.textContent).toContain('Current fulfillment 3');
        await act(async () => list.resolve([{ ...project, progress: null, tasks: [] }]));
        await flush();
        expect(v.host.textContent).toContain('Current fulfillment 3');
        await v.click('ORDER-001');
        expect(v.host.textContent).toContain('Current fulfillment 3');
    }
    finally {
        await v.dispose();
    }
});
it('invalidates old progress on a genuinely newer list and fetches its selected detail', async () => {
    const list = deferred<ProjectDetail[]>(), detail = deferred<ProjectDetail>();
    let lists = 0, newer = false;
    const readProject = vi.fn(async () => newer ? detail.promise : selectedProject());
    const v = await workflowView({ initial: '制造项目', readProjects: async () => ++lists === 1 ? [project] : list.promise, readProject });
    try {
        await v.click('重新读取项目');
        expect(v.host.textContent).toContain('Current fulfillment 3');
        newer = true;
        await act(async () => list.resolve([{ ...project, version: 4, progress: null, tasks: [] }]));
        await flush();
        expect(v.host.textContent).not.toContain('Current fulfillment 3');
        expect(v.host.textContent).toContain('正在核验当前项目业务条件');
        await act(async () => detail.resolve(selectedProject(4)));
        await flush();
        expect(v.host.textContent).toContain('Current fulfillment 4');
        await v.click('ORDER-001');
        expect(v.host.textContent).toContain('Current fulfillment 4');
        await v.click('返回业务列表');
        await v.click('登记需求');
        expect(v.host.textContent).toContain('草稿依据：项目版本 4');
    }
    finally {
        await v.dispose();
    }
});
it('uses actual grant response scope as a freshness floor against delayed older project data',async()=>{
 const late=deferred<ProjectDetail>();let changed=false;
 const v=await workflowView({initial:'制造项目',options:{bootstrap:{...bootstrap,configuration_admin:true},findSubjects:async()=>[{id:'target-user',displayName:'Target'}]},readProject:async()=>changed?late.promise:project});
 const prior=fetch;
 vi.stubGlobal('fetch',vi.fn(async(raw:any,init:any)=>{
   if(init?.method==='PUT'){changed=true;return new Response(JSON.stringify({scope:{kind:'project',project_id:project.id},user_id:'target-user',roles:['planner'],qualifications:[],active:true,project_version:9}),{status:200});}
   if(String(raw).includes('/members'))return new Response(JSON.stringify({items:[]}),{status:200});
   return prior(raw,init);
 }));
 try{
   await v.click('成员授权');await v.field('授权成员','target-user');await flush();await v.field('授权凭据','Named authority');
   await act(async()=>v.host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));await flush();
   await act(async()=>late.resolve({...project,version:4}));await flush();
   await v.click('订单与需求');await v.click('登记需求');
   expect(v.host.textContent).toContain('草稿依据：项目版本 9');
 }finally{await v.dispose();}
});
