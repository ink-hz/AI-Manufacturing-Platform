import { useEffect, useRef, useState } from 'react';
import type { DomainValue, ObjectKind, ObjectSummary, ReleaseKind, WorkspaceProps } from './types';
import { QualityForms } from './forms/QualityForms';
import { ObjectTable } from './OrdersWorkspace';
import { label } from './labels';
type Props=WorkspaceProps&{requestLeave(action:()=>void):void};
type Action='test.record'|'nonconformance.open'|'nonconformance.disposition'|'rework.complete'|'release.decide';
const kinds:ObjectKind[]=['unit','test','nonconformance','rework','release'];
const titles:Record<string,string>={unit:'序列号',test:'测试',nonconformance:'不合格',rework:'返工',release:'放行'};
const releaseTitles:Record<ReleaseKind,string>={manufacturing:'制造放行',quality:'质量放行',customer:'客户放行'};
export function QualityWorkspace(p:Props){
 const [items,setItems]=useState<Partial<Record<ObjectKind,ObjectSummary[]>>>({});
 const [totals,setTotals]=useState<Partial<Record<ObjectKind,number>>>({});
 const [loading,setLoading]=useState<Partial<Record<ObjectKind,boolean>>>({});
 const [selected,setSelected]=useState(''),[selectedRework,setSelectedRework]=useState('');
 const [unit,setUnit]=useState<Extract<DomainValue,{kind:'unit'}>|null>(null),[revision,setRevision]=useState<Extract<DomainValue,{kind:'revision'}>|null>(null),[rework,setRework]=useState<Extract<DomainValue,{kind:'rework'}>|null>(null);
 const [action,setAction]=useState<Action|null>(null),[releaseKind,setReleaseKind]=useState<ReleaseKind>('quality'),[epoch,setEpoch]=useState(0),[error,setError]=useState('');
 const generation=useRef(0);
 useEffect(()=>{const current=++generation.current;setError('');Promise.all(kinds.map(async k=>[k,await p.api.objects(p.project.id,k,50,0)] as const)).then(pages=>{if(current!==generation.current)return;setItems(Object.fromEntries(pages.map(([k,v])=>[k,v.items])));setTotals(Object.fromEntries(pages.map(([k,v])=>[k,v.total])));setSelected(old=>old||pages.find(([k])=>k==='unit')?.[1].items[0]?.id||'');}).catch(e=>{if(current===generation.current)setError(String(e));});return()=>{generation.current++;};},[p.api,p.project.id,p.project.version]);
 useEffect(()=>{let active=true;setUnit(null);setRevision(null);if(selected)p.api.object(p.project.id,'unit',selected).then(async d=>{if(!active||d.value.kind!=='unit')return;setUnit(d.value);const r=await p.api.object(p.project.id,'revision',d.value.revision_id);if(active&&r.value.kind==='revision')setRevision(r.value);}).catch(e=>{if(active)setError(String(e));});return()=>{active=false;};},[p.api,p.project.id,p.project.version,selected]);
 useEffect(()=>{let active=true;setRework(null);if(selectedRework)p.api.object(p.project.id,'rework',selectedRework).then(d=>{if(active&&d.value.kind==='rework'){setRework(d.value);setSelected(d.value.unit_id);}}).catch(e=>{if(active)setError(String(e));});return()=>{active=false;};},[p.api,p.project.id,p.project.version,selectedRework]);
 async function more(kind:ObjectKind){if(loading[kind])return;const current=generation.current;setLoading(x=>({...x,[kind]:true}));try{const page=await p.api.objects(p.project.id,kind,50,(items[kind]||[]).length);if(current===generation.current){setItems(x=>({...x,[kind]:[...(x[kind]||[]),...page.items]}));setTotals(x=>({...x,[kind]:page.total}));}}catch(e){if(current===generation.current)setError(String(e));}finally{if(current===generation.current)setLoading(x=>({...x,[kind]:false}));}}
 const show=(value:Action|null,kind?:ReleaseKind)=>p.requestLeave(()=>{setAction(value);if(kind)setReleaseKind(kind);setEpoch(x=>x+1);});
 const summary=p.project.quality_summary;
 return <section><h3>测量、返工与独立放行</h3><p>首次结果与最终合格分开统计，原始失败不可覆盖。</p>{summary&&<p>首次已测 {summary.first_tested} · 首次通过 {summary.first_passed} · 最终合格 {summary.final_good} · 报废 {summary.scrapped} · 未结不合格 {summary.open_nonconformances}</p>}{error&&<p role="alert">{error}</p>}
  <label>查看序列号<select aria-label="查看序列号" value={selected} onChange={e=>{const id=e.target.value;p.requestLeave(()=>{setSelected(id);setAction(null);});}}><option value="">请选择</option>{(items.unit||[]).map(u=><option key={u.id} value={u.id}>{u.title}</option>)}</select></label>
  <label>查看返工单<select aria-label="查看返工单" value={selectedRework} onChange={e=>{const id=e.target.value;p.requestLeave(()=>{setSelectedRework(id);setAction(null);});}}><option value="">请选择</option>{(items.rework||[]).map(u=><option key={u.id} value={u.id}>{u.title}</option>)}</select></label>
  {unit&&<section><h4>测量历史 · {unit.first_pass===false?'首次未通过':unit.first_pass?'首次通过':'尚未测量'}</h4><p>{unit.scrapped?'不可逆报废':unit.final_good?'最终合格':'尚未最终合格'} · 最近 100 条，共 {unit.test_total||0} 次</p><ol>{(unit.tests||[]).map(t=><li key={t.id}><button onClick={()=>p.onOpen({projectId:p.project.id,kind:'test',id:t.id})}>第 {t.attempt} 次 · {label(t.outcome)} · {t.rework_order_id?'返工复测':'初始路线测试'}</button></li>)}</ol></section>}
  {revision&&<p>固定规范 {revision.test_spec.version} · 测试程序 {revision.test_spec.program_version} · 固件 {revision.firmware_version}</p>}
  {rework&&<section><h4>独立返工路线 {rework.route_id}</h4><ol>{rework.route_steps.map(s=><li key={s.station}>{s.station} · {s.instruction_version}</li>)}</ol><p>在生产执行中选择此返工单并追加真实工位来源记录，然后在此记录复测并完成返工。</p></section>}
  {!p.readOnly&&<div className="mf-actions">{([['test.record','记录测试'],['nonconformance.open','登记不合格'],['nonconformance.disposition','不合格处置'],['rework.complete','完成返工']] as const).filter(([a])=>p.project.allowed_actions.includes(a)).map(([a,title])=><button key={a} disabled={(a==='test.record'&&!revision)||(a==='rework.complete'&&!rework)} onClick={()=>show(a)}>{title}</button>)}{(p.project.release_kinds||[]).map(k=><button key={k} onClick={()=>show('release.decide',k)}>{releaseTitles[k]}</button>)}</div>}
  {action&&<><button onClick={()=>show(null)}>放弃草稿并重新读取</button><QualityForms key={action+releaseKind+epoch} {...p} action={action} releaseKind={releaseKind} units={items.unit||[]} tests={items.test||[]} nonconformances={items.nonconformance||[]} reworks={items.rework||[]} unit={unit} revision={revision} rework={rework} onChanged={r=>{setAction(null);p.onChanged(r);}}/></>}
  {kinds.map(k=><section key={k}><h4>{titles[k]}</h4><ObjectTable items={items[k]||[]} onOpen={p.onOpen}/>{(items[k]||[]).length<(totals[k]||0)&&<button disabled={loading[k]} onClick={()=>void more(k)}>读取更多{titles[k]}（已读取 {(items[k]||[]).length} / {totals[k]}）</button>}</section>)}
 </section>;
}
