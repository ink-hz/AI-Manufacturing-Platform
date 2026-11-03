import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { join } from 'node:path';
import { startHttpHost, projectInput } from './httpTestHost';
import { App } from '../App';
import { SupplyWorkspace } from './SupplyWorkspace';
import { DetailContent } from './WorkflowDetail';
import type { CommandFields, CommandResult, ObjectDetail, WorkspaceProps } from './types';
let http:Awaited<ReturnType<typeof startHttpHost>>,host:HTMLDivElement,root:Root;
type Session=Awaited<ReturnType<Awaited<ReturnType<typeof startHttpHost>>['login']>>;
let owner:Session,warehouse:Session,production:Session;
let warnings:string[]=[];
beforeAll(async()=>{http=await startHttpHost();owner=await http.login('owner');warehouse=await http.login('warehouse');production=await http.login('production');host=document.createElement('div');document.body.append(host);root=createRoot(host);},15000);
afterEach(()=>{expect(warnings.filter(v=>v.includes('not wrapped in act'))).toEqual([]);});
afterAll(async()=>{await act(async()=>root?.unmount());host?.remove();vi.unstubAllGlobals();vi.restoreAllMocks();await http?.close();});
const transport=(s:Session)=>vi.stubGlobal('fetch',s.transport);
async function settled(predicate:()=>boolean){const end=Date.now()+4000;while(!predicate()&&Date.now()<end)await act(async()=>{await new Promise(r=>setTimeout(r,15));});expect(predicate(),host.textContent||'').toBe(true);}
async function field(name:string,value:string){const e=host.querySelector(`[aria-label="${name}"]`) as HTMLInputElement;expect(e,name).toBeTruthy();await act(async()=>{Object.getOwnPropertyDescriptor(e.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype,'value')!.set!.call(e,value);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));});}
async function button(text:string){const b=[...host.querySelectorAll('button')].find(b=>b.textContent===text);expect(b,text).toBeTruthy();await act(async()=>b!.click());}
const snapshotScript=`import json,sqlite3,sys
result={}
for path,tables in [(sys.argv[1],['material_lots','supply_receipts','iqc_results','reservations','material_consumption','source_corrections','source_confirmations','handoffs']),(sys.argv[2],None)]:
 c=sqlite3.connect('file:'+path+'?mode=ro',uri=True)
 if tables is None: tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
 result[path]={t:c.execute('SELECT * FROM "'+t+'" ORDER BY rowid').fetchall() for t in tables}
 c.close()
print(json.dumps(result,sort_keys=True))`;
async function stockSnapshot(){const {stdout}=await promisify(execFile)(process.env.WORKFLOW_TEST_PYTHON||'/Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python',['-c',snapshotScript,join(http.root,'workflow.db'),join(http.root,'authority.db')]);return stdout;}
it('persists actual React handoff/receipt/resolution forms with designated real identities and unchanged stock',async()=>{
 warnings=[];const original=console.error;vi.spyOn(console,'error').mockImplementation((...args:unknown[])=>{warnings.push(args.map(String).join(' '));original(...args);});
 transport(owner);const input=projectInput();const p=await owner.api.createProject({...input,mode:'oem'});
 const cmd=async(s:Session,fields:CommandFields)=>{transport(s);return s.api.command(p.id,{...fields,operation_id:crypto.randomUUID(),expected_version:(await s.api.project(p.id)).version});};
 for(const [s,roles] of [[warehouse,['warehouse']],[production,['production']]] as const){transport(owner);await owner.api.grant(p.id,s.identity.user_id,{operation_id:crypto.randomUUID(),expected_version:(await owner.api.project(p.id)).version,scope:{kind:'project',project_id:p.id},roles:[...roles],qualifications:[],active:true,evidence:'Synthetic HTTP role grant'});}
 const now=new Date().toISOString();const lot=await cmd(owner,{action:'material.define',material_id:'steel',lot_id:'LOT-HANDOFF',owner_id:'Customer 1',unit:'kg',scale:3,expiry:'2027-12-01',source:{system:'Isolated manual test',object_type:'material_lot',external_id:'LOT-HANDOFF',version:1,mode:'manual',occurred_at:now,collected_at:now,cutoff:null,evidence:'Synthetic batch definition'}});
 // Existing fixture seeds an unrelated authority inventory row; all authority and local accounting rows are compared.
 const external=await owner.transport('/fixture/authority',{method:'POST',headers:{'content-type':'application/json','x-csrf-token':owner.options.csrfToken},body:JSON.stringify({action:'receive',fields:{project_id:p.id,external_id:'UNRELATED-STOCK',commitment_id:crypto.randomUUID(),lot_id:crypto.randomUUID(),material_id:'other',owner_id:'Customer 1',quantity:'10',unit:'kg',scale:3,expiry:'2027-12-01',external_actor:'Synthetic warehouse',signature:'Synthetic fixture receipt'}})});expect(external.status,await external.text()).toBe(200);
 const before=await stockSnapshot();let result:CommandResult|undefined;let serial=0;
 async function workspace(s:Session,action?:string,detail?:ObjectDetail){transport(s);const props:WorkspaceProps={api:s.api,project:await s.api.project(p.id),onChanged:r=>{if('operation_id'in r)result=r;},onDirty:()=>{},onOpen:()=>{},readOnly:false};result=undefined;await act(async()=>root.render(<SupplyWorkspace key={++serial} {...props} currentUserId={s.identity.user_id} initialAction={action} initialObject={detail} requestLeave={f=>f()}/>));await settled(()=>!host.textContent?.includes('正在读取…'));}
 async function submit(){await settled(()=>!(host.querySelector('button[type="submit"]') as HTMLButtonElement)?.disabled);await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));await settled(()=>!!result||!!host.querySelector('form [role="alert"]'));expect(result,host.textContent||'').toBeDefined();return result!;}
 await workspace(warehouse);await button('发起物料交接');expect(host.querySelector('[aria-label="接收人"]')!.textContent).toContain('production');expect(host.querySelector('[aria-label="接收人"]')!.textContent).not.toContain('warehouse');await field('物料批次',lot.object_id);await field('交接数量','2.5');await field('交出位置','仓库 A');await field('送达位置','线边 B');await field('接收人',production.identity.user_id);const recorded=await submit();
 transport(warehouse);let d=await warehouse.api.object(p.id,'material_handoff',recorded.object_id);expect(d.value).toMatchObject({kind:'material_handoff',state:'pending',receiver_id:production.identity.user_id,receiver_name:'production',quantity:'2.5',unit:'kg',to_location:'线边 B'});expect(await stockSnapshot()).toBe(before);
 // Sender and configuration administrator cannot sign on the receiver's behalf.
 expect(d.summary.next_actions).not.toContain('material_handoff.receive');await workspace(warehouse,'material_handoff.receive',d);expect(host.querySelector('form')).toBeNull();await expect(cmd(warehouse,{action:'material_handoff.receive',handoff_id:recorded.object_id,received_quantity:'2.5',received_location:'线边 B',occurred_at:null,note:null})).rejects.toMatchObject({status:403});await expect(cmd(owner,{action:'material_handoff.receive',handoff_id:recorded.object_id,received_quantity:'2.5',received_location:'线边 B',occurred_at:null,note:null})).rejects.toMatchObject({status:403});
 warehouse=await http.login('warehouse');owner=await http.login('owner');
 transport(production);d=await production.api.object(p.id,'material_handoff',recorded.object_id);expect(d.summary.next_actions).toContain('material_handoff.receive');await workspace(production,'material_handoff.receive',d);expect((host.querySelector('[aria-label="实收数量"]') as HTMLInputElement).value).toBe('2.5');expect((host.querySelector('[aria-label="实际接收位置"]') as HTMLInputElement).value).toBe('线边 B');await field('实收数量','2');await field('实际接收位置','暂存 C');await field('差异说明','实际短收并放入暂存区');await submit();
 transport(production);d=await production.api.object(p.id,'material_handoff',recorded.object_id);expect(d.value).toMatchObject({state:'disputed',quantity:'2.5',to_location:'线边 B',receipt:{received_quantity:'2',received_location:'暂存 C',actor_id:production.identity.user_id,note:'实际短收并放入暂存区'}});expect(await stockSnapshot()).toBe(before);
 transport(warehouse);d=await warehouse.api.object(p.id,'material_handoff',recorded.object_id);await workspace(warehouse,'material_handoff.resolve',d);await field('处理说明','已核对差额，保留原始交接与接收事实');await submit();transport(warehouse);d=await warehouse.api.object(p.id,'material_handoff',recorded.object_id);expect(d.value).toMatchObject({state:'resolved',quantity:'2.5',receipt:{received_quantity:'2',received_location:'暂存 C'},resolution:{resolution:'已核对差额，保留原始交接与接收事实'}});expect(await stockSnapshot()).toBe(before);
 await act(async()=>root.render(<DetailContent data={d} onOpen={()=>{}}/>));expect(host.querySelector('h3')?.textContent).toBe(d.value.kind==='material_handoff'?d.value.handoff_number:'');expect(host.textContent).toContain('差异已处理');expect(host.textContent).toContain('实际接收位置 暂存 C');expect(host.textContent).toContain('人工登记');
 // Reloaded workspace keeps same-batch records separate and permits cancellation only while pending.
 await workspace(warehouse);await button('发起物料交接');await field('物料批次',lot.object_id);await field('交接数量','1');await field('交出位置','仓库 A');await field('送达位置','线边 D');await field('接收人',production.identity.user_id);const split=await submit();transport(warehouse);const splitDetail=await warehouse.api.object(p.id,'material_handoff',split.object_id);await workspace(warehouse,'material_handoff.cancel',splitDetail);await field('取消原因','分笔交接重复登记');await submit();transport(warehouse);expect((await warehouse.api.object(p.id,'material_handoff',split.object_id)).summary.state).toBe('cancelled');expect((await warehouse.api.object(p.id,'material_handoff',recorded.object_id)).summary.state).toBe('resolved');expect(await stockSnapshot()).toBe(before);
 // The application consumes the real acknowledgement, opens the saved detail,
 // then returns to the same global ledger kind and selected project.
 const finalRecord=await cmd(warehouse,{action:'material_handoff.record',material_lot_id:lot.object_id,work_order_id:null,quantity:'1',unit:'kg',from_location:'仓库 A',to_location:'线边 E',receiver_id:production.identity.user_id,occurred_at:null,note:null});
 transport(production);const finalDetail=await production.api.object(p.id,'material_handoff',finalRecord.object_id);
 const access=await production.api.bootstrap();
 await act(async()=>root.render(<App options={{...production.options,bootstrap:access}}/>));
 await settled(()=>!![...host.querySelectorAll('button')].find(b=>b.textContent==='计划与物料'));
 await button('计划与物料');await button('物料交接');await settled(()=>!!host.querySelector(`[aria-label="所属项目筛选"] option[value="${p.id}"]`));await field('所属项目筛选',p.id);await settled(()=>!!host.querySelector('[aria-label="本页交接状态筛选"]'));await button('待接收');expect((host.querySelector('[aria-label="所属项目筛选"]') as HTMLSelectElement).value).toBe(p.id);
 await settled(()=>!![...host.querySelectorAll('button')].find(b=>b.textContent===(finalDetail.value.kind==='material_handoff'?finalDetail.value.handoff_number:'')));
 await button(finalDetail.value.kind==='material_handoff'?finalDetail.value.handoff_number:'');
 await settled(()=>!![...host.querySelectorAll('button')].find(b=>b.textContent==='前往处理：确认接收'));
 await button('查看物料批次');await settled(()=>host.querySelector('.wf-detail h3')?.textContent==='LOT-HANDOFF');
 await button('返回业务列表');await settled(()=>!!host.querySelector('.wf-global-ledger table')&&!host.textContent?.includes('正在读取'));
 expect((host.querySelector('[aria-label="所属项目筛选"]') as HTMLSelectElement).value).toBe(p.id);
 expect(host.querySelector('[aria-label="本页交接状态筛选"] button[aria-pressed="true"]')?.textContent).toBe('待接收');
 await button(finalDetail.value.kind==='material_handoff'?finalDetail.value.handoff_number:'');
 await settled(()=>!![...host.querySelectorAll('button')].find(b=>b.textContent==='前往处理：确认接收'));
 await button('前往处理：确认接收');await settled(()=>!!host.querySelector('form[aria-label="确认接收"]'));
 await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 await settled(()=>!!host.querySelector('[aria-label="物料交接事实"]')&&!!host.querySelector('.wf-status-info'));
 expect(host.textContent).toContain('实收 1 kg');await button('返回台账');
 await settled(()=>!!host.querySelector('.wf-global-ledger table')&&!host.textContent?.includes('正在读取'));
 expect((host.querySelector('[aria-label="所属项目筛选"]') as HTMLSelectElement).value).toBe(p.id);
 expect(host.querySelector('.wf-global-ledger .mf-tabs button[aria-pressed="true"]')?.textContent).toBe('物料交接');
 expect(host.querySelector('[aria-label="本页交接状态筛选"] button[aria-pressed="true"]')?.textContent).toBe('待接收');
 expect(await stockSnapshot()).toBe(before);
 // A newly saved project handoff retains its project workspace across a related-lot detail.
 await button('进入项目办理');await button('发起物料交接');
 await settled(()=>!!host.querySelector(`[aria-label="物料批次"] option[value="${lot.object_id}"]`) && !!host.querySelector(`[aria-label="接收人"] option[value="${warehouse.identity.user_id}"]`));
 await field('物料批次',lot.object_id);await field('交接数量','1');await field('交出位置','仓库 F');await field('送达位置','线边 G');await field('接收人',warehouse.identity.user_id);
 await settled(()=>!(host.querySelector('button[type="submit"]') as HTMLButtonElement)?.disabled);
 await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 await settled(()=>!!host.querySelector('[aria-label="物料交接事实"]'));
 expect(host.textContent).not.toContain('物料批次 · 物料批次');
 await button('查看物料批次');await settled(()=>host.querySelector('.wf-detail h3')?.textContent==='LOT-HANDOFF');
 await button('返回业务列表');await settled(()=>!!host.querySelector('[aria-label="物料交接工作区"]')&&!host.textContent?.includes('正在读取'));
 expect(host.querySelector('[aria-label="物料办理类型"] button[aria-pressed="true"]')?.textContent).toBe('物料交接');
 expect(await stockSnapshot()).toBe(before);
},30000);

it.each(['receive', 'resolve', 'cancel', 'lot'] as const)(
  'retains the project workspace for an existing row %s transition', async transition => {
    warnings=[];
    await act(async()=>root.render(null));
    transport(owner);
    const p=await owner.api.createProject({...projectInput(),mode:'oem'});
    for(const [session,roles] of [[warehouse,['warehouse']],[production,['production']]] as const) {
      await owner.api.grant(p.id,session.identity.user_id,{
        operation_id:crypto.randomUUID(),expected_version:(await owner.api.project(p.id)).version,
        scope:{kind:'project',project_id:p.id},roles:[...roles],qualifications:[],active:true,evidence:'Synthetic direct-row grant',
      });
    }
    async function command(session:Session,fields:CommandFields) {
      transport(session);
      return session.api.command(p.id,{...fields,operation_id:crypto.randomUUID(),expected_version:(await session.api.project(p.id)).version});
    }
    const now=new Date().toISOString();
    const lot=await command(owner,{
      action:'material.define',material_id:'direct-steel',lot_id:'LOT-DIRECT',owner_id:'Customer 1',unit:'kg',scale:3,expiry:'2027-12-01',
      source:{system:'Isolated direct-row fixture',object_type:'material_lot',external_id:p.id,version:1,mode:'manual',occurred_at:now,collected_at:now,cutoff:null,evidence:'Synthetic lot'},
    });
    const handoff=await command(warehouse,{
      action:'material_handoff.record',material_lot_id:lot.object_id,work_order_id:null,quantity:'1',unit:'kg',
      from_location:'仓库 A',to_location:'线边 B',receiver_id:production.identity.user_id,occurred_at:null,note:null,
    });
    if(transition==='resolve') await command(production,{
      action:'material_handoff.receive',handoff_id:handoff.object_id,received_quantity:'0',received_location:'线边 B',occurred_at:null,note:'实物短收',
    });
    const actor=transition==='receive'?production:warehouse;
    transport(actor);
    const access=await actor.api.bootstrap();
    await act(async()=>root.render(<App key={transition} options={{...actor.options,bootstrap:access}}/>));
    await settled(()=>!![...host.querySelectorAll('button')].find(b=>b.textContent==='计划与物料'));
    await button('计划与物料');
    await settled(()=>!!host.querySelector(`[aria-label="所属项目筛选"] option[value="${p.id}"]`));
    await field('所属项目筛选',p.id);await button('进入项目办理');
    await settled(()=>!!host.querySelector('[aria-label="物料交接工作区"]')&&!host.textContent?.includes('正在读取'));
    if(transition==='lot') {
      await button('LOT-DIRECT');
      await settled(()=>host.querySelector('.wf-detail h3')?.textContent==='LOT-DIRECT');
    } else {
      if(transition==='resolve') await button('待处理差异');
      await button(({receive:'确认接收',resolve:'处理差异',cancel:'取消交接'})[transition]);
      if(transition==='resolve') await field('处理说明','已按原始记录核对差异');
      if(transition==='cancel') await field('取消原因','实物交出前发现重复登记');
      await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
      await settled(()=>!!host.querySelector('[aria-label="物料交接事实"]'));
    }
    await button('返回业务列表');
    await settled(()=>!!host.querySelector('[aria-label="物料交接工作区"]')&&!host.textContent?.includes('正在读取'));
    expect(host.querySelector('.wf-global-ledger')).toBeNull();
    expect(host.querySelector('[aria-label="物料办理类型"] button[aria-pressed="true"]')?.textContent).toBe('物料交接');
  },15000,
);
