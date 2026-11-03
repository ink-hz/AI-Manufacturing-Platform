import { useEffect, useRef, useState } from 'react';
import type { OEMWorkspaceProps } from './OEMWorkspace';
import type { Grant, MaterialHandoffCommand, ObjectDetail, ObjectKind, ObjectSummary } from './types';
import { MaterialHandoffForms } from './forms/MaterialHandoffForms';
import { label, objectTitle } from './labels';
import { StatusBadge } from './StatusBadge';
const kinds:ObjectKind[]=['material_handoff','material_lot','work_order'];
const eligible=(m:Grant)=>m.active&&m.roles.some(r=>['warehouse','supply','production','project_owner'].includes(r));
export function MaterialHandoffWorkspace(p:OEMWorkspaceProps & {currentUserId?:string}){
 const [items,setItems]=useState<Partial<Record<ObjectKind,ObjectSummary[]>>>({}),[totals,setTotals]=useState<Partial<Record<ObjectKind,number>>>({}),[details,setDetails]=useState<ObjectDetail[]>([]),[members,setMembers]=useState<Grant[]>([]),[memberOffset,setMemberOffset]=useState(0),[hasMembers,setHasMembers]=useState(false),[error,setError]=useState(''),[busy,setBusy]=useState(false),[retry,setRetry]=useState(0),[filter,setFilter]=useState('pending'),[action,setAction]=useState<MaterialHandoffCommand['action']|null>(p.initialAction?.startsWith('material_handoff.')?p.initialAction as MaterialHandoffCommand['action']:null),[epoch,setEpoch]=useState(0);
 const generation=useRef(0);
 useEffect(()=>{if(p.onSelectAction)setAction(p.initialAction?.startsWith('material_handoff.')?p.initialAction as MaterialHandoffCommand['action']:null);},[p.initialAction,p.onSelectAction]);
 useEffect(()=>{
  const c=new AbortController(),g=++generation.current;setItems({});setTotals({});setDetails([]);setMembers([]);setMemberOffset(0);setHasMembers(false);setError('');setBusy(true);
  Promise.all([Promise.all(kinds.map(async k=>[k,await p.api.objects(p.project.id,k,50,0,c.signal)] as const)),p.api.members(p.project.id,50,0)]).then(async([pages,ms])=>{
   const hs=pages.find(([k])=>k==='material_handoff')![1];
   const ds=await Promise.all(hs.items.map(h=>p.api.object(p.project.id,'material_handoff',h.id,c.signal)));
   if(c.signal.aborted||g!==generation.current)return;
   setItems(Object.fromEntries(pages.map(([k,v])=>[k,v.items])));setTotals(Object.fromEntries(pages.map(([k,v])=>[k,v.total])));setDetails(ds);setMembers(ms.items);setMemberOffset(ms.items.length);setHasMembers(ms.items.length===50);
  }).catch(e=>{if(!c.signal.aborted&&g===generation.current)setError(String(e));}).finally(()=>{if(!c.signal.aborted&&g===generation.current)setBusy(false);});
  return()=>{generation.current++;c.abort();};
 },[p.api,p.project.id,p.project.version,retry]);
 async function more(kind:ObjectKind|'members'){
  const g=generation.current;setBusy(true);setError('');
  try{if(kind==='members'){const page=await p.api.members(p.project.id,50,memberOffset);if(g!==generation.current)return;setMembers(old=>[...old,...page.items]);setMemberOffset(old=>old+page.items.length);setHasMembers(page.items.length===50);}else{const page=await p.api.objects(p.project.id,kind,50,(items[kind]||[]).length);const ds=kind==='material_handoff'?await Promise.all(page.items.map(h=>p.api.object(p.project.id,kind,h.id))):[];if(g!==generation.current)return;setItems(old=>({...old,[kind]:[...(old[kind]||[]),...page.items]}));setTotals(old=>({...old,[kind]:page.total}));setDetails(old=>[...old,...ds]);}}catch(e){if(g===generation.current)setError(String(e));}finally{if(g===generation.current)setBusy(false);}
 }
 const scoped=p.initialObject?.summary.project_id===p.project.id&&p.initialObject.value.kind==='material_handoff'?p.initialObject:null;
 const [chosen,setChosen]=useState<ObjectDetail|null>(null);
 const selected=chosen?.summary.project_id===p.project.id?chosen:scoped;
 const permitted=!!action&&p.project.allowed_actions.includes(action)&&!p.readOnly&&(action==='material_handoff.record'||!!selected?.summary.next_actions.includes(action));
 function choose(a:MaterialHandoffCommand['action'],d:ObjectDetail|null=null){p.requestLeave(()=>{p.onSelectAction?.(a);setChosen(d);setAction(a);setEpoch(x=>x+1);});}
 const rows=details.filter(d=>filter==='all'||d.summary.state===filter);
 return <section aria-label="物料交接工作区"><h3>物料交接</h3><p>人工登记 · 每笔交接分别确认数量与位置；同批次拆分记录不代表整批物料位置。待接收的送达位置尚未确认。</p>
 {!p.readOnly&&p.project.allowed_actions.includes('material_handoff.record')&&<button onClick={()=>choose('material_handoff.record')}>发起物料交接</button>}
 {permitted&&<><button onClick={()=>p.requestLeave(()=>{setAction(null);setChosen(null);p.onSelectAction?.(null);setRetry(x=>x+1);})}>放弃草稿并重新读取</button><MaterialHandoffForms key={p.project.id+action+selected?.summary.id+epoch} {...p} action={action!} selected={selected?.value.kind==='material_handoff'?selected.value:null} lots={items.material_lot||[]} workOrders={items.work_order||[]} members={members.filter(m=>eligible(m)&&m.user_id!==p.currentUserId)} onChanged={r=>{setAction(null);p.onChanged(r);}}/>
 {(['material_lot','work_order'] as const).map(k=>(items[k]||[]).length<(totals[k]||0)&&<button key={k} disabled={busy} onClick={()=>void more(k)}>读取更多{label(k)}（已读取 {(items[k]||[]).length} / {totals[k]}）</button>)}{action==='material_handoff.record'&&hasMembers&&<button disabled={busy} onClick={()=>void more('members')}>读取更多项目成员（已读取 {memberOffset}）</button>}</>}
 {error&&<p role="alert">{error}<button onClick={()=>setRetry(x=>x+1)}>重试读取交接</button></p>}
 <div className="mf-tabs" aria-label="交接状态筛选">{[['pending','待接收'],['disputed','待处理差异'],['all','全部记录']].map(([v,t])=><button key={v} aria-pressed={filter===v} onClick={()=>setFilter(v)}>{t}</button>)}</div>
 <p role="status">已读取 {(items.material_handoff||[]).length} / {totals.material_handoff||0} · 仅筛选已读取记录 · 当前显示 {rows.length} 条{busy?' · 正在读取…':''}</p>
 <div className="wf-table-scroll"><table><thead><tr><th>交接记录</th><th>物料批次</th><th>交接数量</th><th>位置</th><th>交出人 / 接收人</th><th>状态</th><th>办理</th></tr></thead><tbody>{rows.map(d=>{const h=d.value;if(h.kind!=='material_handoff')return null;return <tr key={h.id}><td><button onClick={()=>p.onOpen({projectId:p.project.id,kind:'material_handoff',id:h.id})}>{h.handoff_number}</button></td><td><button onClick={()=>p.onOpen({projectId:p.project.id,kind:'material_lot',id:h.material_lot_id})}>{objectTitle((items.material_lot||[]).find(l=>l.id===h.material_lot_id)||{...d.summary,title:'查看物料批次'})}</button></td><td>{h.quantity} {h.unit}{h.receipt&&<p>实收 {h.receipt.received_quantity} {h.unit}</p>}</td><td>{h.from_location} → {h.to_location}{h.receipt?<p>实际接收：{h.receipt.received_location}</p>:h.state==='pending'?'（送达位置待接收确认）':'（未确认接收）'}</td><td>{h.sender_name} / {h.receiver_name}</td><td><StatusBadge state={h.state} kind="material_handoff"/></td><td>{!p.readOnly&&d.summary.next_actions.filter(a=>a.startsWith('material_handoff.')&&p.project.allowed_actions.includes(a as MaterialHandoffCommand['action'])).map(a=><button key={a} onClick={()=>choose(a as MaterialHandoffCommand['action'],d)}>{label(a)}</button>)}</td></tr>;})}</tbody></table></div>
 {(items.material_handoff||[]).length<(totals.material_handoff||0)&&<button disabled={busy} onClick={()=>void more('material_handoff')}>读取更多交接记录</button>}
 </section>;
}
