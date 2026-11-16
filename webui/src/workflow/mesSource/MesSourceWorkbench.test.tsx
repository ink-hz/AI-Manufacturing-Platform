import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { it, expect, vi } from 'vitest';
import { MesSourceWorkbench } from './MesSourceWorkbench';
import type { WorkflowApi } from '../api';
const source = { system: 'mes', origin: 'native', fact_role: 'observation', environment: 'production', site_code: 'SITE', namespace: 'n' };
const observation = (data: unknown, scope: Record<string, string | number> = { prefix: '', after: '' }) => ({ snapshot: { id: '1', kind: 'orders', source, scope, collected_at: 'original-time', data }, refresh_error: null });
const empty = { snapshot: null, refresh_error: null };
async function mount(overrides: Record<string, unknown> = {}) {
    const api = { mesSourceStatus: vi.fn(async () => ({ configured: true, can_refresh: true, source })), mesSourceQuery: vi.fn(async (kind: string, scope: Record<string, string | number>, refresh: boolean) => kind === 'orders' ? refresh ? observation({ items: [{ shop_order: 'SO1', description: '真实说明' }], next_cursor: null, total: null, page_size: 5 }) : empty : observation(kind === 'order-materials' ? { total: 1, components: [{ component_key: '1', material_id: 'MAT', unit: 'EA', required_quantity: '123.00001', withdrawn_quantity: null }] } : { rows: [{ MATNR: 'MAT', DFQTY: '2.001', INSP_CODE: 'IQC1' }], total_items: 1 }, scope)), ...overrides } as unknown as WorkflowApi;
    const host = document.createElement('div');
    const root = createRoot(host);
    await act(async () => root.render(<MesSourceWorkbench api={api} readOnly={false} accountId="a"/>));
    await act(async () => { await new Promise(r => setTimeout(r, 0)); });
    return { api, host, root };
}
async function click(host: HTMLElement, label: string) { await act(async () => Array.from(host.querySelectorAll('button')).find(b => b.textContent === label)!.click()); await act(async () => { await new Promise(r => setTimeout(r, 0)); }); }
it('loads real source without projects, then complete components and related material pages', async () => {
    const v = await mount();
    expect(v.host.textContent).toContain('MES生产环境');
    expect(v.host.textContent).toContain('真实说明');
    expect(v.api.mesSourceQuery).toHaveBeenCalledWith('orders', { prefix: '', after: '' }, false, expect.any(AbortSignal));
    await click(v.host, 'SO1');
    expect(v.host.textContent).toContain('123.00001');
    expect(v.host.textContent).toContain('未知');
    await click(v.host, '查看 MAT');
    expect(v.host.textContent).toContain('2.001');
    expect(v.host.textContent).toContain('IQC1');
    expect(v.host.textContent).toContain('不计入本工单合格可用量');
    await act(async () => v.root.unmount());
});
it('cache renders without auto-refresh and offline refresh preserves time', async () => {
    const cached = observation({ items: [], next_cursor: null, total: null, page_size: 5 });
    const query = vi.fn(async (_k: string, _s: unknown, refresh: boolean) => ({ ...cached, refresh_error: refresh ? { code: 'MES_RELAY_UNAVAILABLE', message: 'safe' } : null }));
    const v = await mount({ mesSourceQuery: query });
    expect(query).toHaveBeenCalledTimes(1);
    expect(v.host.textContent).toContain('本页无工单');
    await click(v.host, '刷新工单');
    expect(v.host.textContent).toContain('original-time');
    expect(v.host.textContent).toContain('离线');
    await act(async () => v.root.unmount());
});
it('never commits late component responses after selecting another source order', async () => {
    let resolve!: (v: unknown) => void;
    const query = vi.fn(async (kind: string, scope: Record<string, string | number>) => kind === 'orders' ? observation({ items: [{ shop_order: 'SO1', description: 'one' }, { shop_order: 'SO2', description: 'two' }], next_cursor: null }) : scope.shop_order === 'SO1' ? await new Promise(r => resolve = r) : observation({ total: 0, components: [] }, scope));
    const v = await mount({ mesSourceQuery: query });
    await click(v.host, 'SO1');
    await click(v.host, 'SO2');
    await act(async () => resolve(observation({ total: 1, components: [{ component_key: 'old', material_id: 'STALE' }] }, { shop_order: 'SO1' })));
    expect(v.host.textContent).not.toContain('STALE');
    await act(async () => v.root.unmount());
});
it('rejects source-context mismatch and never retries a failed initial query', async () => {
    const wrong = observation({ items: [{ shop_order: 'WRONG', description: 'wrong' }] });
    wrong.snapshot.source = { ...source, namespace: 'other' };
    const query = vi.fn(async () => wrong);
    const v = await mount({ mesSourceQuery: query });
    expect(v.host.textContent).not.toContain('WRONG');
    expect(v.host.textContent).toContain('读取失败');
    expect(query).toHaveBeenCalledTimes(1);
    await act(async () => v.root.unmount());
});
it('keyset navigation allows a genuine empty next page and returns to prior cursor', async () => {
    const query = vi.fn(async (_k: string, scope: Record<string, string | number>) => observation({ items: scope.after ? [] : [{ shop_order: 'SO1', description: 'one' }], next_cursor: scope.after ? null : 'SO1' }, scope));
    const v = await mount({ mesSourceQuery: query });
    await click(v.host, '下一页工单');
    expect(v.host.textContent).toContain('本页无工单');
    expect(query).toHaveBeenLastCalledWith('orders', { prefix: '', after: 'SO1' }, false, expect.any(AbortSignal));
    await click(v.host, '上一页工单');
    expect(v.host.textContent).toContain('one');
    await act(async () => v.root.unmount());
});
it('read-only identity never starts a source refresh when cache is absent', async () => {
    const query = vi.fn(async () => empty);
    const api = { mesSourceStatus: async () => ({ configured: true, source, can_refresh: true }), mesSourceQuery: query } as unknown as WorkflowApi;
    const host = document.createElement('div'), root = createRoot(host);
    await act(async () => root.render(<MesSourceWorkbench api={api} accountId="reader" readOnly/>));
    expect(query).toHaveBeenCalledTimes(1);
    expect(query).toHaveBeenCalledWith('orders', { prefix: '', after: '' }, false, expect.any(AbortSignal));
    expect(host.textContent).toContain('尚未查询');
    await act(async () => root.unmount());
});
it('account changes isolate pending source results', async () => {
    let finish!: (v: unknown) => void;
    let calls = 0;
    const query = vi.fn(async () => ++calls === 1 ? await new Promise(r => finish = r) : observation({ items: [], next_cursor: null }));
    const api = { mesSourceStatus: async () => ({ configured: true, source, can_refresh: false }), mesSourceQuery: query } as unknown as WorkflowApi;
    const host = document.createElement('div'), root = createRoot(host);
    await act(async () => root.render(<MesSourceWorkbench api={api} accountId="first" readOnly/>));
    await act(async () => root.render(<MesSourceWorkbench api={api} accountId="second" readOnly/>));
    await act(async () => finish(observation({ items: [{ shop_order: 'FIRST-PRIVATE' }], next_cursor: null })));
    expect(host.textContent).not.toContain('FIRST-PRIVATE');
    await act(async () => root.unmount());
});
it('changing component discards late priority and IQC records', async () => {
 let finishPriority!: (value: unknown) => void, finishIqc!: (value: unknown) => void;
 const query = vi.fn(async (kind: string, scope: Record<string,string|number>) => {
  if(kind==='orders') return observation({items:[{shop_order:'SO1',description:'one'}],next_cursor:null},scope);
  if(kind==='order-materials')return observation({total:2,components:[{component_key:'1',material_id:'A'},{component_key:'2',material_id:'B'}]},scope);
  if(scope.material==='A')return await new Promise(resolve=>{if(kind==='priority')finishPriority=resolve;else finishIqc=resolve;});
  return observation({rows:[],total_items:0},scope);
 });
 const v=await mount({mesSourceQuery:query});await click(v.host,'SO1');await click(v.host,'查看 A');await click(v.host,'查看 B');
 await act(async()=>{finishPriority(observation({rows:[{MAKTX:'OLD-PRIORITY'}],total_items:1},{shop_order:'SO1',material:'A',page:1}));finishIqc(observation({rows:[{INSP_CODE:'OLD-IQC'}],total_items:1},{material:'A',page:1}));});
 expect(v.host.textContent).not.toContain('OLD-PRIORITY');expect(v.host.textContent).not.toContain('OLD-IQC');await act(async()=>v.root.unmount());
});
it('synchronously suppresses retained source A selection on source B, including dependent reads', async () => {
 const newSource={...source,namespace:'source-b',site_code:'B'};
 const query=vi.fn(async()=>empty);
 const api={mesSourceStatus:async()=>({configured:true,source:newSource,can_refresh:false}),mesSourceQuery:query} as unknown as WorkflowApi;
 const host=document.createElement('div'),root=createRoot(host);
 const retained={accountId:'same-account',source,order:{shop_order:'SAME',description:'OLD-A'}};
 await act(async()=>root.render(<MesSourceWorkbench api={api} accountId="same-account" readOnly={false} selectedSelection={retained}/>));
 expect(host.textContent).not.toContain('OLD-A');
 expect(query).toHaveBeenCalledTimes(1);
 expect(query).toHaveBeenCalledWith('orders',{prefix:'',after:''},false,expect.any(AbortSignal));
 await act(async()=>root.unmount());
});
it('late source A component results cannot appear after a source B remount', async () => {
 let finish!:(value:unknown)=>void;
 const oldSelection={accountId:'a',source,order:{shop_order:'SAME',description:'OLD-A'}};
 const queryA=vi.fn(async(kind:string)=>kind==='orders'?empty:await new Promise(resolve=>finish=resolve));
 const apiA={mesSourceStatus:async()=>({configured:true,source,can_refresh:false}),mesSourceQuery:queryA} as unknown as WorkflowApi;
 const sourceB={...source,namespace:'source-b'};
 const queryB=vi.fn(async()=>empty);
 const apiB={mesSourceStatus:async()=>({configured:true,source:sourceB,can_refresh:false}),mesSourceQuery:queryB} as unknown as WorkflowApi;
 const host=document.createElement('div'),root=createRoot(host);
 await act(async()=>root.render(<MesSourceWorkbench api={apiA} accountId="a" readOnly selectedSelection={oldSelection}/>));
 await act(async()=>root.render(<MesSourceWorkbench api={apiB} accountId="a" readOnly selectedSelection={oldSelection}/>));
 await act(async()=>finish(observation({total:1,components:[{component_key:'1',material_id:'LATE-A'}]},{shop_order:'SAME'})));
 expect(host.textContent).not.toContain('OLD-A');expect(host.textContent).not.toContain('LATE-A');expect(queryB).toHaveBeenCalledTimes(1);
 await act(async()=>root.unmount());
});

const superseded = { code: 'MES_REFRESH_SUPERSEDED', message: 'PRIVATE-ERROR' };
it('recovers superseded response with exactly one cache GET and persisted success', async () => {
 const query=vi.fn().mockResolvedValueOnce(empty).mockResolvedValueOnce({...observation({items:[{shop_order:'SYN-OLD',description:'older'}]}),refresh_error:superseded}).mockResolvedValueOnce(observation({items:[{shop_order:'SYN-NEW',description:'newer'}]}));
 const v=await mount({mesSourceQuery:query});expect(v.host.textContent).toContain('newer');expect(v.host.querySelector('[role="alert"]')).toBeNull();expect(query.mock.calls.map(c=>c[2])).toEqual([false,true,false]);expect(query.mock.calls.every(c=>JSON.stringify(c[1])===JSON.stringify({prefix:'',after:''}))).toBe(true);await act(async()=>v.root.unmount());
});
it('shows update in progress when superseded cache remains empty without fake empty or retry',async()=>{
 const query=vi.fn().mockResolvedValueOnce(empty).mockResolvedValueOnce({snapshot:null,refresh_error:superseded}).mockResolvedValueOnce(empty);
 const v=await mount({mesSourceQuery:query});expect(v.host.textContent).toContain('其他查询正在更新');expect(v.host.textContent).not.toContain('本页无工单');expect(v.host.querySelector('[role="alert"]')).toBeNull();expect(query).toHaveBeenCalledTimes(3);await act(async()=>v.root.unmount());
});
it('renders persisted safe error after superseded without leaking arbitrary messages',async()=>{
 const query=vi.fn().mockResolvedValueOnce(empty).mockResolvedValueOnce({...observation({items:[]}),refresh_error:superseded}).mockResolvedValueOnce({...observation({items:[]}),refresh_error:{code:'MES_TIMEOUT',message:'PRIVATE-ERROR'}});
 const v=await mount({mesSourceQuery:query});expect(v.host.textContent).toContain('读取超时');expect(v.host.textContent).not.toContain('PRIVATE-ERROR');expect(v.host.textContent).not.toContain('组件超过');expect(query).toHaveBeenCalledTimes(3);await act(async()=>v.root.unmount());
});
it('keeps successful data and time when superseded cache GET fails',async()=>{
 const query=vi.fn().mockResolvedValueOnce(observation({items:[{shop_order:'SYN-SAVED',description:'saved'}]})).mockResolvedValueOnce({snapshot:null,refresh_error:superseded}).mockRejectedValueOnce(Error('PRIVATE-ERROR'));
 const v=await mount({mesSourceQuery:query});await click(v.host,'刷新工单');expect(v.host.textContent).toContain('saved');expect(v.host.textContent).toContain('original-time');expect(v.host.textContent).toContain('读取失败');expect(v.host.textContent).not.toContain('PRIVATE-ERROR');expect(query.mock.calls.map(c=>c[2])).toEqual([false,true,false]);await act(async()=>v.root.unmount());
});

it.each(['source','scope'])('rejects %s mismatch in superseded cache followup',async(mismatch)=>{
 const bad=observation({items:[{shop_order:'SYN-WRONG',description:'wrong-followup'}]});
 if(mismatch==='source')bad.snapshot.source={...source,namespace:'different'};else bad.snapshot.scope={prefix:'different',after:''};
 const query=vi.fn().mockResolvedValueOnce(empty).mockResolvedValueOnce({snapshot:null,refresh_error:superseded}).mockResolvedValueOnce(bad);
 const v=await mount({mesSourceQuery:query});expect(v.host.textContent).not.toContain('wrong-followup');expect(v.host.textContent).toContain('读取失败');expect(query).toHaveBeenCalledTimes(3);await act(async()=>v.root.unmount());
});
it.each(['account','api','unmount'])('discards late superseded cache followup after %s changes',async(change)=>{
 let finish!:(value:unknown)=>void;
 const query=vi.fn().mockResolvedValueOnce(empty).mockResolvedValueOnce({snapshot:null,refresh_error:superseded}).mockImplementationOnce(()=>new Promise(resolve=>finish=resolve)).mockResolvedValue(empty);
 const v=await mount({mesSourceQuery:query});expect(query).toHaveBeenCalledTimes(3);
 if(change==='unmount')await act(async()=>v.root.unmount());
 else await act(async()=>v.root.render(<MesSourceWorkbench api={change==='api'?{...v.api,mesSourceStatus:async()=>({configured:true,can_refresh:false,source:{...source,namespace:'new-source'}}),mesSourceQuery:vi.fn(async()=>empty)}:v.api} accountId={change==='account'?'b':'a'} readOnly/>));
 await act(async()=>finish(observation({items:[{shop_order:'SYN-LATE',description:'late-followup'}]})));
 expect(v.host.textContent).not.toContain('late-followup');if(change!=='unmount')await act(async()=>v.root.unmount());
});
it('does not follow a superseded response after unmount before it arrives',async()=>{
 let finish!:(value:unknown)=>void;const query=vi.fn().mockResolvedValueOnce(empty).mockImplementationOnce(()=>new Promise(resolve=>finish=resolve));const v=await mount({mesSourceQuery:query});await act(async()=>v.root.unmount());await act(async()=>finish({snapshot:null,refresh_error:superseded}));expect(query).toHaveBeenCalledTimes(2);
});

it('discards pending superseded component cache after another order is selected',async()=>{
 let finish!:(value:unknown)=>void;
 const query=vi.fn(async(kind:string,scope:Record<string,string|number>,refresh:boolean)=>{
  if(kind==='orders')return observation({items:[{shop_order:'SYN-A',description:'a'},{shop_order:'SYN-B',description:'b'}]});
  if(scope.shop_order==='SYN-A')return refresh?{snapshot:null,refresh_error:superseded}:await new Promise(resolve=>finish=resolve);
  return observation({total:0,components:[]},scope);
 });
 // Initial component GET carries superseded, followup cache GET remains pending.
 let first=true;const wrapped=vi.fn(async(kind:string,scope:Record<string,string|number>,refresh:boolean)=>{if(kind==='order-materials'&&scope.shop_order==='SYN-A'&&first){first=false;return {snapshot:null,refresh_error:superseded};}return query(kind,scope,refresh);});
 const v=await mount({mesSourceQuery:wrapped});await click(v.host,'SYN-A');await click(v.host,'SYN-B');await act(async()=>finish(observation({total:1,components:[{component_key:'syn',material_id:'LATE-COMPONENT'}]},{shop_order:'SYN-A'})));expect(v.host.textContent).not.toContain('LATE-COMPONENT');expect(wrapped.mock.calls.filter(c=>c[1].shop_order==='SYN-A').map(c=>c[2])).toEqual([false,false]);await act(async()=>v.root.unmount());
});
it('keeps valid snapshot supplied with superseded initial refresh when cache GET fails',async()=>{
 const query=vi.fn().mockResolvedValueOnce(empty).mockResolvedValueOnce({...observation({items:[{shop_order:'SYN-CACHED',description:'cached-response'}]}),refresh_error:superseded}).mockRejectedValueOnce(Error('PRIVATE'));
 const v=await mount({mesSourceQuery:query});expect(v.host.textContent).toContain('cached-response');expect(v.host.textContent).toContain('original-time');expect(v.host.textContent).toContain('读取失败');await act(async()=>v.root.unmount());
});
