import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { GlobalLedger } from "./GlobalLedger";
import { ActionForms } from "./ActionForms";
import { SupplyWorkspace } from "./SupplyWorkspace";
import { project, source, workflowView, bootstrap } from "./testHelpers";
import type { ObjectDetail, ObjectSummary, WorkspaceProps } from "./types";
let host: HTMLDivElement, root: Root;
beforeEach(()=>{host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
const summary=(kind:string,id:string,title=id)=>({kind,id,title,project_id:project.id,state:'pending',quantity:'5',unit:'kg',version:1,blocking_reasons:[],next_actions:[]} as ObjectSummary);
const handoff=(actions=['material_handoff.receive'])=>({summary:{...summary('material_handoff','h1','MH-001'),next_actions:actions},value:{kind:'material_handoff',id:'h1',handoff_number:'MH-001',state:'pending',material_lot_id:'lot',work_order_id:null,quantity:'5',unit:'kg',from_location:'仓库 A',to_location:'线边 B',sender_id:'sender',sender_name:'仓管',receiver_id:'receiver',receiver_name:'李工',occurred_at:'2026-11-01T01:00:00Z',recorded_at:'2026-11-01T01:00:00Z',note:null,source,receipt:null,resolution:null,cancellation:null},relations:[],history:[],evidence:[]} as unknown as ObjectDetail);
function client(){return {objects:vi.fn(async(_p:string,k:string)=>({items:k==='material_lot'?[summary(k,'lot','钢材批次')]:k==='material_handoff'?[handoff().summary]:[],total:1})),object:vi.fn(async(..._args:unknown[])=>handoff()),members:vi.fn(async()=>({items:[{user_id:'receiver',display_name:'李工',active:true,roles:['production']},{user_id:'qa',display_name:'质检',active:true,roles:['quality']}],total:2})),assistance:vi.fn(async()=>({items:[],unknowns:[],state:'no_evidence',truncated:false})),command:vi.fn(async(..._args:unknown[])=>({object_type:'material_handoff',object_id:'h1',project_id:project.id,project_version:4}))};}
function props(api:ReturnType<typeof client>,extra:Record<string,unknown>={}){return {api,project:{...project,mode:'oem',allowed_actions:['material_handoff.record','material_handoff.receive','material_handoff.resolve','material_handoff.cancel']},onChanged:vi.fn(),onOpen:vi.fn(),onDirty:vi.fn(),readOnly:false,requestLeave:(f:()=>void)=>f(),...extra} as unknown as Parameters<typeof SupplyWorkspace>[0];}
async function click(text:string){const b=[...host.querySelectorAll('button')].find(x=>x.textContent===text);expect(b,text).toBeTruthy();await act(async()=>b!.click());}
async function field(name:string,value:string){const e=host.querySelector(`[aria-label="${name}"]`) as HTMLInputElement;expect(e,name).toBeTruthy();await act(async()=>{Object.getOwnPropertyDescriptor(e.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype,'value')!.set!.call(e,value);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));});}
async function submit(){await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));}
it('records five core business fields with derived unit and trusted member choices',async()=>{const api=client();await act(async()=>root.render(<SupplyWorkspace {...props(api)}/>));await click('发起物料交接');await field('物料批次','lot');await field('交接数量','2');await field('交出位置','仓库 A');await field('送达位置','线边 B');await field('接收人','receiver');expect(host.querySelectorAll('form > fieldset > label')).toHaveLength(5);expect(host.textContent).toContain('单位：kg');expect(host.querySelector('[aria-label="接收人"]')!.textContent).not.toContain('质检');expect(host.querySelector('[aria-label="来源系统"]')).toBeNull();expect(host.querySelector('form details summary')!.textContent).toBe('补充信息');await submit();expect(api.command.mock.calls[0][1]).toMatchObject({action:'material_handoff.record',material_lot_id:'lot',quantity:'2',unit:'kg',from_location:'仓库 A',to_location:'线边 B',receiver_id:'receiver',occurred_at:null,work_order_id:null});});
it.each([['0','线边 B'],['6','线边 B'],['5','暂存 C']])('defaults receipt and requires an explanation for %s / %s',async(q,loc)=>{const api=client();await act(async()=>root.render(<SupplyWorkspace {...props(api,{initialAction:'material_handoff.receive',initialObject:handoff()})}/>));expect((host.querySelector('[aria-label="实收数量"]') as HTMLInputElement)?.value).toBe('5');expect((host.querySelector('[aria-label="实际接收位置"]') as HTMLInputElement)?.value).toBe('线边 B');expect(host.querySelector('[aria-label="交接记录"]')).toBeNull();await field('实收数量',q);await field('实际接收位置',loc);expect((host.querySelector('button[type="submit"]') as HTMLButtonElement).disabled).toBe(true);await field('差异说明','实物核对差异');await submit();expect(api.command.mock.calls[0][1]).toMatchObject({action:'material_handoff.receive',handoff_id:'h1',received_quantity:q,received_location:loc,note:'实物核对差异',occurred_at:null});});
it('retains edited facts after a rejected command',async()=>{const api=client();api.command.mockRejectedValue(new Error('请重新核对'));await act(async()=>root.render(<SupplyWorkspace {...props(api,{initialAction:'material_handoff.receive',initialObject:handoff()})}/>));await field('实收数量','3');await field('差异说明','少收两件');await submit();expect(host.textContent).toContain('请重新核对');expect((host.querySelector('[aria-label="实收数量"]') as HTMLInputElement).value).toBe('3');});
it('does not expose receipt without an assigned action',async()=>{const api=client();await act(async()=>root.render(<SupplyWorkspace {...props(api,{initialAction:'material_handoff.receive',initialObject:handoff([])})}/>));expect(host.querySelector('form')).toBeNull();});
it('retires late project pages and shows loaded-range coverage',async()=>{const api=client();let resolve!:(p:any)=>void;api.objects.mockImplementation(async(pid:string,k:string)=>pid===project.id&&k==='material_handoff'?new Promise(r=>{resolve=r;}):{items:[],total:0});const base=props(api);await act(async()=>root.render(<SupplyWorkspace {...base}/>));await act(async()=>root.render(<SupplyWorkspace {...base} project={{...base.project,id:'new-project'}}/>));await act(async()=>resolve({items:[summary('material_handoff','old','OLD PRIVATE HANDOFF')],total:99}));expect(host.textContent).not.toContain('OLD PRIVATE HANDOFF');expect(host.textContent).toContain('已读取 0 / 0');expect(host.textContent).toContain('仅筛选已读取记录');});
it('keeps drafts through handbook and guards leaving',async()=>{const p={...project,mode:'oem' as const,allowed_actions:['material_handoff.record'] as WorkspaceProps['project']['allowed_actions']};const v=await workflowView({readProjects:async()=>[p],readProject:async()=>p,options:{bootstrap}});try{await v.click('计划与物料');await v.field('所属项目筛选',p.id);await v.click('进入项目办理');await v.click('发起物料交接');await v.field('交出位置','未保存位置');await v.click('制造手册');await v.click('返回工作区');expect((v.host.querySelector('[aria-label="交出位置"]') as HTMLInputElement).value).toBe('未保存位置');await v.click('供应与到货');expect(v.host.querySelector('[role="dialog"]')).toBeTruthy();}finally{await v.dispose();}});
it('opens global handoff facts and returns to the filtered handoff ledger',async()=>{const p={...project,mode:'oem' as const,allowed_actions:['material_handoff.receive'] as WorkspaceProps['project']['allowed_actions']};const d=handoff();const v=await workflowView({readProjects:async()=>[p],readProject:async()=>p,readLedger:async(kind,_l,offset)=>({items:kind==='material_handoff'?[d.summary]:[],total:kind==='material_handoff'?1:0,offset,limit:50}),readObject:async(_p,kind)=>kind==='material_handoff'?d:{...d,summary:summary('material_lot','lot','钢材批次')},options:{bootstrap}});try{await v.click('计划与物料');await v.click('物料交接');await v.field('所属项目筛选',p.id);await v.click('待接收');expect(v.host.textContent).toContain('仅筛选本页已读取记录');expect(v.host.textContent).toContain('仓管 / 李工');expect(v.host.textContent).toContain('送达位置待接收确认');await v.click('MH-001');await v.click('前往处理：确认接收');expect(v.host.querySelector('form[aria-label="确认接收"]')).toBeTruthy();await v.click('返回台账');expect((v.host.querySelector('[aria-label="所属项目筛选"]') as HTMLSelectElement).value).toBe(p.id);expect(v.host.querySelector('.mf-tabs button[aria-pressed="true"]')?.textContent).toBe('物料交接');expect(v.host.querySelector('[aria-label="本页交接状态筛选"] button[aria-pressed="true"]')?.textContent).toBe('待接收');}finally{await v.dispose();}});
it('keeps the newest selected lot unit when an older detail arrives late',async()=>{const api=client();api.objects.mockImplementation(async(_p:string,k:string)=>({items:k==='material_lot'?['a','b'].map(id=>({...summary(k,id),unit:null})):[],total:k==='material_lot'?2:0}));const pending=new Map<string,(d:ObjectDetail)=>void>();api.object.mockImplementation(async(_p?:unknown,_k?:unknown,id?:unknown)=>new Promise(r=>pending.set(String(id),r)));await act(async()=>root.render(<SupplyWorkspace {...props(api,{initialAction:'material_handoff.record'})}/>));await field('物料批次','a');await field('交接数量','10');await field('交出位置','仓库 A');await field('送达位置','线边 B');await field('接收人','receiver');await field('物料批次','b');await act(async()=>pending.get('b')!({...handoff(),value:{kind:'material_lot',unit:'piece'} as ObjectDetail['value']}));expect(host.textContent).toContain('单位：piece');await act(async()=>pending.get('a')!({...handoff(),value:{kind:'material_lot',unit:'kg'} as ObjectDetail['value']}));expect(host.textContent).not.toContain('单位：kg');await submit();expect(api.command.mock.calls[0][1]).toMatchObject({material_lot_id:'b',unit:'piece',quantity:'10'});});
it('blocks submission after a lot detail failure and retains the business draft',async()=>{const api=client();api.objects.mockImplementation(async(_p:string,k:string)=>({items:k==='material_lot'?[{...summary(k,'lot'),unit:null}]:[],total:k==='material_lot'?1:0}));api.object.mockRejectedValue(new Error('批次读取失败'));await act(async()=>root.render(<SupplyWorkspace {...props(api,{initialAction:'material_handoff.record'})}/>));await field('交接数量','7');await field('交出位置','草稿位置 A');await field('送达位置','草稿位置 B');await field('接收人','receiver');await field('物料批次','lot');expect(host.textContent).toContain('批次读取失败');expect((host.querySelector('button[type="submit"]') as HTMLButtonElement).disabled).toBe(true);await submit();expect(api.command).not.toHaveBeenCalled();expect((host.querySelector('[aria-label="交出位置"]') as HTMLInputElement).value).toBe('草稿位置 A');expect((host.querySelector('[aria-label="交接数量"]') as HTMLInputElement).value).toBe('7');});
it('explicitly pages scoped members before offering a later authorized receiver',async()=>{const api=client();api.members.mockImplementation(async(_p?:unknown,_limit?:unknown,offset?:unknown)=>({items:offset?[{user_id:'receiver',display_name:'李工',active:true,roles:['production']}]:Array.from({length:50},(_,i)=>({user_id:'qa'+i,display_name:'质检'+i,active:true,roles:['quality']})),total:51}));await act(async()=>root.render(<SupplyWorkspace {...props(api,{initialAction:'material_handoff.record'})}/>));expect(host.querySelector('[aria-label="接收人"]')!.textContent).not.toContain('李工');await click('读取更多项目成员（已读取 50）');expect(host.querySelector('[aria-label="接收人"]')!.textContent).toContain('李工');expect(api.members).toHaveBeenLastCalledWith(project.id,50,50);});
it('keeps legacy internal projects accessible without advertising OEM handoff writes',async()=>{const api=client();const base=props(api);await act(async()=>root.render(<SupplyWorkspace {...base} project={{...base.project,mode:'internal'}}/>));expect(host.querySelector('[aria-label="物料交接工作区"]')).toBeNull();expect([...host.querySelectorAll('button')].some(b=>b.textContent==='发起物料交接')).toBe(false);expect(host.textContent).toContain('供应与物料');});

it('preserves one-click explicit modes when a controlled parent clears the selected action', async () => {
  const api = client();
  function Controlled() {
    const [action, setAction] = useState<string | null>(null);
    const base = props(api);
    return <SupplyWorkspace {...base} project={{...base.project, allowed_actions: [...base.project.allowed_actions, 'supply.receive']}} initialAction={action} onSelectAction={setAction}/>;
  }
  await act(async () => root.render(<Controlled/>));
  await click('发起物料交接');
  await click('供应与到货');
  expect(host.querySelector('[aria-label="物料交接工作区"]')).toBeNull();
  await click('登记到货');
  await click('放弃草稿并重新读取');
  expect(host.querySelector('[aria-label="物料交接工作区"]')).toBeNull();
  expect(host.querySelector('form')).toBeNull();
  await click('物料交接');
  await click('发起物料交接');
  expect(host.querySelector('form[aria-label="发起物料交接"]')).toBeTruthy();
});

it('requires accepting the dirty draft guard before either controlled mode transition', async () => {
  const p = {...project, mode: 'oem' as const, allowed_actions: ['material_handoff.record', 'supply.receive'] as WorkspaceProps['project']['allowed_actions']};
  const v = await workflowView({readProjects: async()=>[p], readProject: async()=>p});
  try {
    await v.click('计划与物料'); await v.field('所属项目筛选', p.id); await v.click('进入项目办理');
    await v.click('发起物料交接'); await v.field('交出位置', '保留的草稿位置'); await v.click('供应与到货');
    expect((v.host.querySelector('[aria-label="交出位置"]') as HTMLInputElement).value).toBe('保留的草稿位置');
    await v.click('放弃并离开');
    expect(v.host.querySelector('[aria-label="物料交接工作区"]')).toBeNull();
    await v.click('登记到货'); await v.field('本次到货数量', '3'); await v.click('物料交接');
    expect(v.host.querySelector('[role="dialog"]')).toBeTruthy();
    await v.click('放弃并离开');
    expect(v.host.querySelector('[aria-label="物料交接工作区"]')).toBeTruthy();
  } finally { await v.dispose(); }
});

function globalProps(api: ReturnType<typeof client>) {
  return {api: api as unknown as WorkspaceProps['api'], module: 'supply' as const,
    context: {kind: 'material_handoff' as const, projectId: project.id, offset: 0},
    onContext: vi.fn(), projects: [project], refresh: 0, onRefresh: vi.fn(), onOpen: vi.fn(), onProject: vi.fn()};
}
const fixtureDetail = (id: string, lot='shared-lot') => {
  const d=handoff();
  if(d.value.kind!=='material_handoff') throw Error('fixture');
  return {...d, summary: {...d.summary, id, title: id}, value: {...d.value, id, handoff_number: id, material_lot_id: lot}};
};

it('deduplicates shared-lot hydration within a global handoff page', async () => {
  const api=Object.assign(client(), {ledger: vi.fn(async()=>({items:['one','two','three'].map(id=>fixtureDetail(id).summary),total:3,limit:50,offset:0}))});
  api.object.mockImplementation(async (_p?:unknown,k?:unknown,id?:unknown)=>k==='material_handoff'?fixtureDetail(String(id)):{...handoff(),summary:summary('material_lot',String(id),'共用钢材批次')});
  await act(async()=>root.render(<GlobalLedger {...globalProps(api)}/>));
  expect(host.textContent).toContain('共用钢材批次');
  expect(api.object.mock.calls.filter(c=>c[1]==='material_lot')).toHaveLength(1);
});

it('limits simultaneous global handoff and lot reads to four', async () => {
  const api=Object.assign(client(), {ledger:vi.fn(async()=>({items:Array.from({length:12},(_,i)=>fixtureDetail('h'+i).summary),total:12,limit:50,offset:0}))});
  let active=0, peak=0;
  const pending: (()=>void)[]=[];
  api.object.mockImplementation(async(_p?:unknown,k?:unknown,id?:unknown)=>{
    active++;peak=Math.max(peak,active);
    await new Promise<void>(r=>pending.push(r));active--;
    return k==='material_handoff'?fixtureDetail(String(id)):{...handoff(),summary:summary('material_lot',String(id),'共用批次')};
  });
  await act(async()=>root.render(<GlobalLedger {...globalProps(api)}/>));
  expect(peak).toBeLessThanOrEqual(4);
  for(let i=0;i<20&&pending.length;i++) await act(async()=>pending.splice(0).forEach(r=>r()));
  expect(host.querySelectorAll('tbody tr')).toHaveLength(12);
  expect(peak).toBeLessThanOrEqual(4);
});

it('keeps valid global rows and offers an honest retry for one failed handoff or lot', async () => {
  const api=Object.assign(client(), {ledger:vi.fn(async()=>({items:['good','missing','lot-failure'].map(id=>fixtureDetail(id,id).summary),total:3,limit:50,offset:0}))});
  let fail=true;
  api.object.mockImplementation(async(_p?:unknown,k?:unknown,id?:unknown)=>{
    if(fail&&((k==='material_handoff'&&id==='missing')||(k==='material_lot'&&id==='lot-failure')))throw Error('普通读取失败');
    return k==='material_handoff'?fixtureDetail(String(id),String(id)):{...handoff(),summary:summary('material_lot',String(id),'已核对批次 '+id)};
  });
  await act(async()=>root.render(<GlobalLedger {...globalProps(api)}/>));
  expect(host.textContent).toContain('已核对批次 good');
  expect(host.querySelectorAll('tbody tr')).toHaveLength(3);
  const missing=[...host.querySelectorAll('tbody tr')].find(r=>r.textContent?.includes('missing'))!;
  expect(missing.textContent).toContain('交接详情未读取');
  expect(missing.textContent).not.toContain('仓管 / 李工');
  expect(host.textContent).toContain('批次信息未读取');
  fail=false;
  await act(async()=>[...missing.querySelectorAll('button')].find(b=>b.textContent==='重试此行')!.click());
  expect(host.textContent).toContain('已核对批次 missing');
  expect(host.textContent).toContain('已核对批次 good');
});

it('does not hide project handoffs when one row or a separate choice lookup fails', async () => {
  const api=client();
  api.objects.mockImplementation(async(_p:string,k:string)=>{
    if(k==='work_order')throw Error('工单选项读取失败');
    return {items:k==='material_handoff'?['good','missing'].map(id=>fixtureDetail(id).summary):[],total:k==='material_handoff'?2:0};
  });
  api.object.mockImplementation(async(_p?:unknown,k?:unknown,id?:unknown)=>{
    if(id==='missing')throw Error('单行读取失败');
    return k==='material_handoff'?fixtureDetail(String(id)):{...handoff(),summary:summary('material_lot',String(id),'钢材批次')};
  });
  await act(async()=>root.render(<SupplyWorkspace {...props(api)}/>));
  expect(host.textContent).toContain('仓管 / 李工');
  expect(host.textContent).toContain('交接详情未读取');
  expect(host.querySelectorAll('tbody tr')).toHaveLength(2);
});

it('translates handoff action blockers without changing existing object wording', async()=>{
  const api=client(), d=handoff();
  d.summary.blocking_reasons=['Awaiting designated receiver'];
  await act(async()=>root.render(<ActionForms {...props(api)} detail={d}/>));
  expect(host.textContent).toContain('等待指定接收人确认');
});

it('follows incoming non-null actions and initializes the mode when the project changes', async () => {
  const api=client(), base=props(api);
  const p={...base.project, allowed_actions:[...base.project.allowed_actions, 'supply.receive' as const]};
  await act(async()=>root.render(<SupplyWorkspace {...base} project={p} initialAction="supply.receive"/>));
  expect(host.querySelector('form[aria-label="登记到货"]')).toBeTruthy();
  await act(async()=>root.render(<SupplyWorkspace {...base} project={p} initialAction="material_handoff.record"/>));
  expect(host.querySelector('form[aria-label="发起物料交接"]')).toBeTruthy();
  await click('供应与到货');
  expect(host.querySelector('[aria-label="物料交接工作区"]')).toBeNull();
  await act(async()=>root.render(<SupplyWorkspace {...base} project={{...p,id:'another-project'}} initialAction={null}/>));
  expect(host.querySelector('[aria-label="物料交接工作区"]')).toBeTruthy();
});
