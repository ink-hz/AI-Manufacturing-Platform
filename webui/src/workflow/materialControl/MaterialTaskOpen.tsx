import {useMaterialCommand} from './useMaterialCommand';
import {useState} from 'react';
import type {OEMWorkspaceProps} from '../OEMWorkspace';
import type {MaterialProject,MaterialRequirement} from './types';
export function MaterialTaskOpen({p,page,requirement}:{p:OEMWorkspaceProps;page:MaterialProject;requirement:MaterialRequirement}) {
 const command=useMaterialCommand(p.api,p.project.id);const [version,setVersion]=useState(p.project.version);
 const [kind,setKind]=useState<'iqc'|'trace'|null>(null),[members,setMembers]=useState<{id:string;display_name:string}[]>([]),[member,setMember]=useState(''),[reference,setReference]=useState(''),[note,setNote]=useState(''),[error,setError]=useState(''),[saving,setSaving]=useState(false);
 const receipts=page.receipts.filter(r=>requirement.receipt_ids.includes(r.id));const handoffs=page.handoffs.filter(h=>requirement.handoff_ids.includes(h.id));
 function start(k:'iqc'|'trace'){p.requestLeave(()=>{command.clear();setVersion(p.project.version);setKind(k);setMember('');setReference('');setNote('');setError('');p.api.materialAssignees(p.project.id,k).then(v=>setMembers(v.items)).catch(e=>setError(String(e)));});}
 const edit=(f:(v:string)=>void,v:string)=>{f(v);p.onDirty('material-task-open',true);};
 async function submit(){if(p.readOnly||!p.project.allowed_actions.includes('material_task.open')||!kind||!reference||!member||!note.trim()||saving)return;setSaving(true);setError('');try{const result=await command.execute({action:'material_task.open',requirement_id:requirement.id,task_kind:kind,receipt_id:kind==='iqc'?reference:null,handoff_id:kind==='trace'?reference:null,assignee_id:member,note},version);if(!result)return;p.onDirty('material-task-open',false);setKind(null);p.onChanged(result);}catch(e){if(command.isCurrent())setError(String(e));}finally{if(command.isCurrent())setSaving(false);}}
 const allowed=!p.readOnly&&p.project.allowed_actions.includes('material_task.open');
 return <section>{allowed&&<div className="mf-actions"><button onClick={()=>start('iqc')}>安排检验</button><button onClick={()=>start('trace')}>安排查料</button></div>}{kind&&<div>
 <label>{kind==='iqc'?'到货记录':'交料记录'}<select aria-label={kind==='iqc'?'到货记录':'交料记录'} value={reference} onChange={e=>edit(setReference,e.target.value)}><option value="">请选择</option>{kind==='iqc'?receipts.map((r,i)=><option key={r.id} value={r.id}>到货 {i+1} · {r.quantity} {r.unit} · 待检 {r.uninspected} {r.unit}</option>):handoffs.map(h=><option key={h.id} value={h.id}>{h.handoff_number} · {h.quantity} {h.unit} · {h.from_location} → {h.to_location}</option>)}</select></label>
 {!(kind==='iqc'?receipts:handoffs).length&&<p>{kind==='iqc'?'没有关联到货记录，请先登记到货。':'没有关联交料记录，请先登记交料。'}</p>}
 <label>{kind==='iqc'?'检验人':'查料人'}<select aria-label={kind==='iqc'?'检验人':'查料人'} value={member} onChange={e=>edit(setMember,e.target.value)}><option value="">请选择</option>{members.map(m=><option key={m.id} value={m.id}>{m.display_name}</option>)}</select></label><label>任务说明<input aria-label="任务说明" value={note} onChange={e=>edit(setNote,e.target.value)}/></label>{error&&<p role="alert">{error}</p>}<button disabled={saving||!allowed||!reference||!member||!note.trim()} onClick={()=>void submit()}>创建任务</button></div>}</section>;
}
