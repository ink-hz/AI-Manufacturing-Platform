import { MaterialHandoffWorkspace } from "./MaterialHandoffWorkspace";
import { OEMWorkspace, type OEMWorkspaceProps } from "./OEMWorkspace";
import { AssistancePanel } from "./AssistancePanel";
import { useEffect, useRef, useState } from "react";
import type { WorkspaceProps, ObjectKind, ObjectSummary, CommandFields } from "./types";
import { ObjectTable } from "./OrdersWorkspace";
import { SupplyForms } from "./forms/SupplyForms";
import { label } from "./labels";
import { OperationHelp } from "./OperationHelp";

const kinds: ObjectKind[]=["material_lot","plan","requirement","commitment","receipt","reservation"];
const lookups: ObjectKind[]=["work_order","order_line","revision"];
const actions: Record<string,string>={
  "reservation.request":"请求权威库存预留",
  "material.define":"定义物料批次","plan.receive":"接收供应计划",
  "supply.commit":"登记供应承诺","supply.receive":"登记到货",
  "supply.inspect":"登记来料检验",
};
export function SupplyWorkspace(p:OEMWorkspaceProps & {onReload?():void;currentUserId?:string}){
  const initialMode=()=>p.project.mode==='oem'&&(!p.initialAction||p.initialAction.startsWith('material_handoff.'))?'handoff':'legacy';
  const [mode,setMode]=useState(initialMode);
  useEffect(()=>{setMode(initialMode());},[p.project.id,p.initialAction]);
  return <section>{p.project.mode==='oem'&&<div className="mf-tabs" aria-label="物料办理类型">
    <button aria-pressed={mode==='handoff'} onClick={()=>p.requestLeave(()=>{p.onSelectAction?.(null);setMode('handoff');})}>物料交接</button>
    <button aria-pressed={mode==='legacy'} onClick={()=>p.requestLeave(()=>{p.onSelectAction?.(null);setMode('legacy');})}>供应与到货</button>
  </div>}{mode==='handoff'&&p.project.mode==='oem'?<MaterialHandoffWorkspace key={p.project.id} {...p}/>:<LegacySupplyWorkspace {...p}/>}</section>;
}
function LegacySupplyWorkspace(p:OEMWorkspaceProps & {onReload?():void}){
  const [items,setItems]=useState<Partial<Record<ObjectKind,ObjectSummary[]>>>({});
  const [totals,setTotals]=useState<Partial<Record<ObjectKind,number>>>({});
  const [loading,setLoading]=useState<Partial<Record<ObjectKind,boolean>>>({});
  const [error,setError]=useState("");
  const [action,setAction]=useState<CommandFields["action"]|null>(()=>p.initialAction&&p.initialAction in actions?p.initialAction as CommandFields["action"]:null);
  const [epoch,setEpoch]=useState(0);
  const generation=useRef(0);
  useEffect(()=>{if(p.initialAction?.startsWith("arrival."))setAction(null);},[p.initialAction]);
  useEffect(()=>{
    const current=++generation.current;
    setError(""); setItems({}); setTotals({}); setLoading({});
    Promise.all([...kinds,...lookups].map(async k=>[k,await p.api.objects(p.project.id,k as ObjectKind,50,0)] as const))
      .then(pages=>{if(current===generation.current){
        setItems(Object.fromEntries(pages.map(([k,v])=>[k,v.items])));
        setTotals(Object.fromEntries(pages.map(([k,v])=>[k,v.total])));
      }}).catch(e=>{if(current===generation.current)setError(String(e));});
    return()=>{generation.current++;};
  },[p.api,p.project.id,p.project.version]);
  async function more(kind:ObjectKind){
    if(loading[kind])return;
    const current=generation.current;
    setLoading(x=>({...x,[kind]:true}));
    try{
      const page=await p.api.objects(p.project.id,kind,50,(items[kind]||[]).length);
      if(current===generation.current){
        setItems(x=>({...x,[kind]:[...(x[kind]||[]),...page.items]}));
        setTotals(x=>({...x,[kind]:page.total}));
      }
    }catch(e){if(current===generation.current)setError(String(e));}
    finally{if(current===generation.current)setLoading(x=>({...x,[kind]:false}));}
  }
  const available=Object.keys(actions).filter(a=>p.project.allowed_actions.includes(a as CommandFields["action"]));
  return <section>
    <h3>供应与物料</h3>
    <OperationHelp><p>库存预留由权威系统原子接受。人工到货与检验只登记证据；确认预留以权威接受回执为准。</p></OperationHelp>
    {error&&<p role="alert">{error}</p>}
    <div className="mf-actions">{!p.readOnly&&available.map(a=><button key={a} onClick={()=>p.requestLeave(()=>{p.onSelectAction?.(a);setAction(a as CommandFields["action"]);setEpoch(x=>x+1);})}>{actions[a]}</button>)}</div>
    {action&&<>
      <button onClick={()=>p.requestLeave(()=>{p.onSelectAction?.(null);setAction(null);setEpoch(x=>x+1);p.onReload?.();})}>放弃草稿并重新读取</button>
      <SupplyForms key={p.project.id+action+epoch} {...p} action={action}
        workOrders={items.work_order||[]} orders={items.order_line||[]}
        revisions={items.revision||[]} lots={items.material_lot||[]}
        requirements={items.requirement||[]} commitments={items.commitment||[]}
        receipts={items.receipt||[]}
        onChanged={result=>{setAction(null);p.onChanged(result);}}/>
    </>}
    {lookups.map(k=>(items[k]||[]).length<(totals[k]||0)&&<button key={k} disabled={loading[k]} onClick={()=>void more(k)}>读取更多{label(k)}（已读取 {(items[k]||[]).length} / {totals[k]}）</button>)}
    <OEMWorkspace {...p} domain="arrival"/>
    <AssistancePanel api={p.api} projectId={p.project.id} version={p.project.version} onOpen={p.onOpen} initialKind="materials"/>
    {kinds.map(k=><section key={k}>
      <h4>{label(k)}</h4>
      {k==="requirement"?<table><thead><tr>
        <th>物料需求</th><th>需求</th><th>在途</th><th>已接收</th><th>已检合格</th><th>拒收</th><th>确认预留</th><th>缺口</th><th>单位</th><th>来源截止</th><th>当前物料阻断</th>
      </tr></thead><tbody>{(items.requirement||[]).map(r=>{
        const b=r.material_balance;
        return <tr key={r.id}><td><button onClick={()=>p.onOpen({projectId:r.project_id,kind:r.kind,id:r.id})}>{r.title}</button></td>
          <td>{b?.required||"—"}</td><td>{b?.in_transit||"—"}</td><td>{b?.received||"—"}</td>
          <td>{b?.qualified||"—"}</td><td>{b?.rejected||"—"}</td><td>{b?.reserved||"—"}</td>
          <td>{b?.shortage||"—"}</td><td>{b?.unit||r.unit||"—"}</td><td>{b?.cutoff||"未提供"}</td><td>{b?.blocking_reasons?.join("；")||"—"}</td></tr>;
      })}</tbody></table>:(items[k]||[]).length?<ObjectTable items={items[k]||[]} onOpen={p.onOpen}/>:<p>尚无{label(k)}记录</p>}
      {(items[k]||[]).length<(totals[k]||0)&&<button disabled={loading[k]} onClick={()=>void more(k)}>读取更多{label(k)}（已读取 {(items[k]||[]).length} / {totals[k]}）</button>}
    </section>)}
  </section>;
}
