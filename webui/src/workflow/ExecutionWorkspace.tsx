import { useEffect, useRef, useState } from "react";
import type { DomainValue, ObjectKind, ObjectSummary, Readiness, WorkspaceProps } from "./types";
import { ObjectTable } from "./OrdersWorkspace";
import { ExecutionForms } from "./forms/ExecutionForms";
import { label } from "./labels";

type Props=WorkspaceProps & {requestLeave(action:()=>void):void};
type Action="unit.register"|"production.start"|"production.interrupt"|"production.resume"|"execution.record"|"first_article.record";
const kinds:ObjectKind[]=["work_order","unit","interruption","plan","material_lot","test"];
const actions:{action:Action;title:string;mode?:"trial"|"bulk"}[]=[
  {action:"unit.register",title:"登记序列号"},
  {action:"production.start",title:"首件试做开工",mode:"trial"},
  {action:"production.start",title:"批量执行开工",mode:"bulk"},
  {action:"execution.record",title:"记录工位执行"},
  {action:"production.interrupt",title:"请求生产中断"},
  {action:"production.resume",title:"恢复生产"},
  {action:"first_article.record",title:"记录首件检验"},
];
function ReadinessCard({title,readiness}:{title:string;readiness:Readiness}){
  return <section><h4>{title} · {readiness.ready?"就绪":"阻断"}</h4><ul>{readiness.checks.map(c=><li key={c.kind}>{label(c.kind)} · {label(c.status)} · {label(c.reason)}</li>)}</ul></section>;
}
export function ExecutionWorkspace(p:Props){
  const [items,setItems]=useState<Partial<Record<ObjectKind,ObjectSummary[]>>>({});
  const [totals,setTotals]=useState<Partial<Record<ObjectKind,number>>>({});
  const [loading,setLoading]=useState<Partial<Record<ObjectKind,boolean>>>({});
  const [workOrder,setWorkOrder]=useState<Extract<DomainValue,{kind:"work_order"}>|null>(null);
  const [revision,setRevision]=useState<Extract<DomainValue,{kind:"revision"}>|null>(null);
  const [selected,setSelected]=useState("");
  const [action,setAction]=useState<(typeof actions)[number]|null>(null);
  const [epoch,setEpoch]=useState(0);
  const [error,setError]=useState("");
  const generation=useRef(0);
  useEffect(()=>{const current=++generation.current;setError("");Promise.all(kinds.map(async k=>[k,await p.api.objects(p.project.id,k,50,0)] as const)).then(pages=>{if(current!==generation.current)return;setItems(Object.fromEntries(pages.map(([k,v])=>[k,v.items])));setTotals(Object.fromEntries(pages.map(([k,v])=>[k,v.total])));setSelected(old=>old||pages.find(([k])=>k==="work_order")?.[1].items[0]?.id||"");}).catch(e=>{if(current===generation.current)setError(String(e));});return()=>{generation.current++;};},[p.api,p.project.id,p.project.version]);
  useEffect(()=>{if(!selected){setWorkOrder(null);return;}let active=true;p.api.object(p.project.id,"work_order",selected).then(d=>{if(active&&d.value.kind==="work_order")setWorkOrder(d.value);}).catch(e=>{if(active)setError(String(e));});return()=>{active=false;};},[p.api,p.project.id,selected,p.project.version]);
  useEffect(()=>{if(!workOrder?.revision_id){setRevision(null);return;}let active=true;p.api.object(p.project.id,"revision",workOrder.revision_id).then(d=>{if(active&&d.value.kind==="revision")setRevision(d.value);}).catch(e=>{if(active)setError(String(e));});return()=>{active=false;};},[p.api,p.project.id,workOrder?.revision_id,p.project.version]);
  async function more(kind:ObjectKind){if(loading[kind])return;const current=generation.current;setLoading(x=>({...x,[kind]:true}));try{const page=await p.api.objects(p.project.id,kind,50,(items[kind]||[]).length);if(current===generation.current){setItems(x=>({...x,[kind]:[...(x[kind]||[]),...page.items]}));setTotals(x=>({...x,[kind]:page.total}));}}catch(e){if(current===generation.current)setError(String(e));}finally{if(current===generation.current)setLoading(x=>({...x,[kind]:false}));}}
  const show=(value:(typeof actions)[number]|null)=>p.requestLeave(()=>{setAction(value);setEpoch(x=>x+1);});
  return <section><h3>生产执行与序列号</h3><p>开工分为首件试做与批量执行。待定请求占用序列号预算；MES 接受回执确认运行。所有工位与物料事件追加来源历史。</p>
    {error&&<p role="alert">{error}</p>}
    <label>查看工单<select aria-label="查看工单" value={selected} onChange={e=>{setSelected(e.target.value);setWorkOrder(null);setRevision(null);}}><option value="">请选择</option>{(items.work_order||[]).map(w=><option key={w.id} value={w.id}>{w.title}</option>)}</select></label>
    {workOrder&&<><ReadinessCard title="试产准备" readiness={workOrder.trial_readiness}/><ReadinessCard title="量产准备" readiness={workOrder.bulk_readiness}/></>}
    {revision&&<section><h4>固定工程包 · {revision.package_id} / {revision.revision}</h4><p>测试规范 {revision.test_spec.version} · 程序 {revision.test_spec.program_version} · 固件 {revision.firmware_version}</p><ol>{revision.route_steps.map(s=><li key={s.station}>{s.station} · 作业指导 {s.instruction_version}</li>)}</ol></section>}
    {!p.readOnly&&<div className="mf-actions">{actions.filter(a=>p.project.allowed_actions.includes(a.action)).map(a=><button key={a.title} onClick={()=>show(a)}>{a.title}</button>)}</div>}
    {action&&<><button onClick={()=>show(null)}>放弃草稿并重新读取</button><ExecutionForms key={action.title+epoch} {...p} action={action.action} mode={action.mode} selectedWorkOrderId={selected} revision={revision} rejectedEvents={(workOrder?.execution_events||[]).filter(e=>e.status==="rejected")} workOrders={items.work_order||[]} units={items.unit||[]} interruptions={items.interruption||[]} plans={items.plan||[]} lots={items.material_lot||[]} tests={items.test||[]} onChanged={r=>{setAction(null);p.onChanged(r);}}/></>}
    {(["work_order","unit","interruption"] as ObjectKind[]).map(k=><section key={k}><h4>{label(k)}</h4><ObjectTable items={items[k]||[]} onOpen={p.onOpen}/>{(items[k]||[]).length<(totals[k]||0)&&<button disabled={loading[k]} onClick={()=>void more(k)}>读取更多{label(k)}（已读取 {(items[k]||[]).length} / {totals[k]}）</button>}</section>)}
  </section>;
}
