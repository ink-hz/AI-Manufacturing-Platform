import type {OEMWorkspaceProps} from '../OEMWorkspace';
import type {MaterialProject,MaterialRequirement} from './types';
export function MaterialFlowPanel({p,page,requirement}:{p:OEMWorkspaceProps;page:MaterialProject;requirement:MaterialRequirement}) {
 const receipts=page.receipts.filter(r=>requirement.receipt_ids.includes(r.id)),handoffs=page.handoffs.filter(h=>requirement.handoff_ids.includes(h.id));
 return <section><h5>到货与交料</h5>{!receipts.length&&!handoffs.length&&<p>暂无关联到货或交料记录。</p>}{receipts.map((r,i)=><p key={r.id}><button className="wf-text-link" onClick={()=>p.requestLeave(()=>p.onOpen({projectId:p.project.id,kind:'receipt',id:r.id}))}>到货 {i+1}</button> · {r.quantity} {r.unit} · 检验合格 {r.qualified} {r.unit} · 拒收 {r.rejected} {r.unit} · 待检 {r.uninspected} {r.unit}</p>)}{handoffs.map(h=><p key={h.id}><button className="wf-text-link" onClick={()=>p.requestLeave(()=>p.onOpen({projectId:p.project.id,kind:'material_handoff',id:h.id}))}>{h.handoff_number}</button> · {h.from_location} → {h.to_location} · 交料 {h.quantity} {h.unit} · {h.receipt?`已签收 ${h.receipt.received_quantity} ${h.unit}，位置 ${h.receipt.received_location}`:'待收料'}</p>)}</section>;
}
