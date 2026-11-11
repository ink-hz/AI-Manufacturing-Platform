import {useMaterialCommand} from './useMaterialCommand';
import {useState} from 'react';
import type {OEMWorkspaceProps} from '../OEMWorkspace';
import type {MaterialProject,MaterialRequirement} from './types';
import type {CommandFields} from '../types';
export function ExpeditePanel({p,page,requirement}:{p:OEMWorkspaceProps;page:MaterialProject;requirement:MaterialRequirement}) {
 const command=useMaterialCommand(p.api,p.project.id);
 const [version,setVersion]=useState(p.project.version);
 const [action,setAction]=useState<'open'|'progress'|'close'|null>(null),[id,setId]=useState(''),[reason,setReason]=useState(''),[impact,setImpact]=useState(''),[outcome,setOutcome]=useState<'fulfilled'|'false_alarm'|'superseded'>('fulfilled'),[error,setError]=useState(''),[saving,setSaving]=useState(false);
 const available=(a:string)=>!p.readOnly && p.project.allowed_actions.some(x=>x===a);
 const start=(a:'open'|'progress'|'close',i='')=>p.requestLeave(()=>{command.clear();setVersion(p.project.version);setAction(a);setId(i);setReason('');setImpact('');setError('');});
 async function submit() {
  if(!action||!available('expedite.'+action)||!reason.trim()||action==='open'&&!impact.trim()||saving)return;
  const fields:CommandFields=action==='open'?{action:'expedite.open',requirement_id:requirement.id,reason,impact}:action==='progress'?{action:'expedite.progress',expedite_id:id,note:reason}:{action:'expedite.close',expedite_id:id,outcome,reason};
  setSaving(true);setError('');try {const result=await command.execute(fields,version);if(!result)return;p.onDirty('material-expedite',false);setAction(null);p.onChanged(result);}catch(e){if(command.isCurrent())setError(String(e));}finally{if(command.isCurrent())setSaving(false);}
 }
 const edit=(f:(v:string)=>void,v:string)=>{f(v);p.onDirty('material-expedite',true);};
 const entries=page.expedites.filter(x=>x.requirement_id===requirement.id);
 return <section><h5>催料</h5>{!entries.length&&<p>暂无催料记录</p>}{entries.map(x=><div key={x.id}><p>{x.expedite_number}：{x.reason} {x.state==='open'?'处理中':'已结束'}</p>{x.progress?.map((v,i)=><p key={i}>{v.note}</p>)}{x.state==='open'&&<div className="mf-actions">{available('expedite.progress')&&<button onClick={()=>start('progress',x.id)}>更新催料进展</button>}{available('expedite.close')&&<button onClick={()=>start('close',x.id)}>结束催料</button>}</div>}</div>)}
 {available('expedite.open')&&<button onClick={()=>start('open')}>发起催料</button>}
 {action&&<div><label>{action==='progress'?'进展':'催料原因'}<input aria-label={action==='progress'?'进展':'催料原因'} value={reason} onChange={e=>edit(setReason,e.target.value)}/></label>{action==='open'&&<label>影响<input aria-label="影响" value={impact} onChange={e=>edit(setImpact,e.target.value)}/></label>}{action==='close'&&<label>结果<select aria-label="结果" value={outcome} onChange={e=>edit(v=>setOutcome(v as typeof outcome),e.target.value)}><option value="fulfilled">已完成</option><option value="false_alarm">误报</option><option value="superseded">已替代</option></select></label>}{error&&<p role="alert">{error}</p>}<button disabled={saving||!available('expedite.'+action)||!reason.trim()||(action==='open'&&!impact.trim())} onClick={()=>void submit()}>{action==='open'?'提交催料':action==='progress'?'保存进展':'确认结束'}</button></div>}
 </section>;
}
