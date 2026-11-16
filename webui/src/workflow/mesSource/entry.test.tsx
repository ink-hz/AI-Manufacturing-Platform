import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { it, expect, vi } from 'vitest';
import { WorkflowApp } from '../WorkflowApp';
import type { MountOptions } from '../../types';
vi.mock('../WorkflowHome', () => ({ WorkflowHome: () => <p>正式工作台</p> }));
vi.mock('../GlobalLedger', () => ({ GlobalLedger: () => <p>正式台账</p> }));
vi.mock('../../HandbookReader', () => ({ HandbookReader: () => null }));
it('admin with zero projects sees source browser at home execution and supply; member does not', async () => {
    const calls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: unknown) => { const url = String(input); calls.push(url); return new Response(JSON.stringify(url.endsWith('/mes-source/status') ? { configured: false, can_refresh: false, source: null } : url.endsWith('/projects') ? { items: [] } : {}), { status: 200, headers: { 'content-type': 'application/json' } }); }));
    const options = { apiBase: '/api/v1/manufacturing', csrfToken: 'x', readOnly: false, bootstrap: { user: { id: 'a', display_name: 'Admin' }, configuration_admin: true, can_edit: true, allowed: true, workflow_access: true, dataset: { mode: 'production', label: '平台' }, release: {} } } as unknown as MountOptions;
    const host = document.createElement('div');
    const root = createRoot(host);
    await act(async () => root.render(<WorkflowApp options={options}/>));
    expect(host.querySelector('[aria-label="MES源工单"]')).not.toBeNull();
    for (const title of ['工单与执行', '计划与物料']) {
        await act(async () => Array.from(host.querySelectorAll('button')).find(b => b.textContent === title)!.click());
        expect(host.querySelector('[aria-label="MES源工单"]')).not.toBeNull();
        expect(host.textContent).toContain('平台正式台账');
    }
    await act(async () => root.render(<WorkflowApp options={{ ...options, bootstrap: { ...options.bootstrap!, configuration_admin: false, user: { ...options.bootstrap!.user, id: 'b' } } }}/>));
    expect(host.querySelector('[aria-label="MES源工单"]')).toBeNull();
    await act(async () => root.unmount());
    vi.unstubAllGlobals();
});
it('retained order from source A cannot query source B until explicitly reselected', async () => {
    let namespace = 'source-a';
    const source = () => ({system:'mes',origin:'native',fact_role:'observation',environment:'production',site_code:namespace,namespace});
    const componentCalls: {namespace:string;method:string}[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input:unknown, init?:RequestInit) => {
        const url = new URL(String(input),'http://localhost');
        let data: unknown = {};
        if(url.pathname.endsWith('/mes-source/status')) data={configured:true,can_refresh:true,source:source()};
        else if(url.pathname.endsWith('/mes-source/orders')) data={snapshot:{id:'1',kind:'orders',scope:{prefix:'',after:''},source:source(),collected_at:'now',data:{items:[{shop_order:'SAME',description:namespace==='source-a'?'OLD-DESCRIPTION':'NEW-DESCRIPTION'}],next_cursor:null}},refresh_error:null};
        else if(url.pathname.endsWith('/mes-source/order-materials')) {
            componentCalls.push({namespace,method:init?.method||'GET'});
            data={snapshot:{id:'2',kind:'order-materials',scope:{shop_order:'SAME'},source:source(),collected_at:'now',data:{total:1,components:[{component_key:'1',material_id:namespace==='source-a'?'MATERIAL-A':'MATERIAL-B'}]}},refresh_error:null};
        } else if(url.pathname.endsWith('/projects')) data={items:[]};
        return new Response(JSON.stringify(data),{status:200,headers:{'content-type':'application/json'}});
    }));
    const options={apiBase:'/api/v1/manufacturing',csrfToken:'x',readOnly:false,bootstrap:{user:{id:'a',display_name:'Admin'},configuration_admin:true,can_edit:true,allowed:true,workflow_access:true,dataset:{mode:'production'},release:{}}} as unknown as MountOptions;
    const host=document.createElement('div'),root=createRoot(host);
    const click=async(text:string)=>act(async()=>Array.from(host.querySelectorAll('button')).find(b=>b.textContent===text)!.click());
    await act(async()=>root.render(<WorkflowApp options={options}/>));await click('SAME');
    expect(host.textContent).toContain('MATERIAL-A');
    await click('制造项目');namespace='source-b';await click('工单与执行');
    expect(host.textContent).not.toContain('OLD-DESCRIPTION');
    expect(host.textContent).not.toContain('MATERIAL-B');
    expect(componentCalls.filter(call=>call.namespace==='source-b')).toEqual([]);
    await click('SAME');expect(host.textContent).toContain('NEW-DESCRIPTION');expect(host.textContent).toContain('MATERIAL-B');
    expect(componentCalls.filter(call=>call.namespace==='source-b')).toHaveLength(1);
    await act(async()=>root.unmount());vi.unstubAllGlobals();
});

it('keeps demo dataset identity on formal ledger without placing it over source browsers',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(input:unknown)=>new Response(JSON.stringify(String(input).endsWith('/mes-source/status')?{configured:true,can_refresh:false,source:{system:'mes',origin:'native',fact_role:'observation',environment:'production',site_code:'SYN-SITE',namespace:'syn'}}:String(input).endsWith('/projects')?{items:[]}:{}),{status:200,headers:{'content-type':'application/json'}})));
 const options={apiBase:'/api/v1/manufacturing',csrfToken:'x',readOnly:false,bootstrap:{user:{id:'a',display_name:'Admin'},configuration_admin:true,can_edit:true,allowed:true,workflow_access:true,dataset:{mode:'demo',label:'全流程模拟环境'},release:{}}} as unknown as MountOptions;
 const host=document.createElement('div'),root=createRoot(host);await act(async()=>root.render(<WorkflowApp options={options}/>));expect(host.textContent).toContain('MES生产环境');expect(host.textContent).not.toContain('隔离演示数据');
 await act(async()=>Array.from(host.querySelectorAll('button')).find(b=>b.textContent==='平台正式台账')!.click());expect(host.textContent).toContain('全流程模拟环境');expect(host.textContent).toContain('隔离演示数据');await act(async()=>root.unmount());vi.unstubAllGlobals();
});
