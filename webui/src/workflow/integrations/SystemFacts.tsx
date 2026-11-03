import {SystemOperationForm} from './SystemOperationForm';
import type {OEMWorkspaceProps} from '../OEMWorkspace';
import type {SystemDescriptor,IntentSummary,BusinessContext} from './types';
import {useEffect,useState,useRef} from 'react';
import type {WorkflowApi} from '../api';
import type {WorkflowTarget} from '../types';
import type {FactDetail,SourceKey} from './types';
import {keyText,factTitle} from './CoreOperationFields';
import {SYSTEM_NAMES} from './businessSteps';
const state=(v:boolean|null|undefined)=>v===true?'已确认':v===false?'尚未完成':'尚未确认';
export function SystemFacts({api,projectId,keys,onOpen,refresh=0,reconciliation}:{reconciliation?:{props:OEMWorkspaceProps;descriptors:SystemDescriptor[];intents:IntentSummary[];context:BusinessContext;onRefresh():void};refresh?:number;api:WorkflowApi;projectId:string;keys:SourceKey[];onOpen(target:WorkflowTarget):void}){
 const [details,setDetails]=useState<FactDetail[]>([]),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 const identity=keys.map(keyText).join('|');
 useEffect(()=>{const c=new AbortController();setDetails([]);setError('');Promise.all(keys.map(k=>api.systemFact(projectId,k,c.signal))).then(rows=>{if(!c.signal.aborted)setDetails(rows);}).catch(e=>{if(!c.signal.aborted)setError(String(e));});return()=>c.abort();},[api,projectId,identity,retry,refresh]);
 return <div>{error&&<p role="alert">{error} <button type="button" onClick={()=>setRetry(n=>n+1)}>重新读取来源</button></p>}{details.map(d=><article key={keyText(d.fact.source)}>
  <p>{factTitle(d.fact)}</p><p>来源接受：{state(d.source_accepted)} · 消费送达：{state(d.consumer_delivered)} · 业务投影：{state(d.workflow_projected)} · SAP 过账：{state(d.sap_posted)}</p>
  {!!d.pending_deliveries&&<p>待送达 {d.pending_deliveries}，不能视为全部消费完成</p>}
  {d.fact.payload.fact_type==='bi.snapshot'&&<><p>快照截止 {d.fact.payload.cutoff} · 版本 {d.fact.payload.snapshot_version}</p><table><thead><tr><th>指标</th><th>公式</th><th>分子 / 分母</th></tr></thead><tbody>{d.fact.payload.metrics.map((m,i)=><tr key={i}><td>{m.metric}</td><td>{m.formula_version}</td><td>{m.numerator} / {m.denominator}</td></tr>)}</tbody></table></>}
  {(d.projection?.targets||[]).map(t=><button key={t.kind+t.id} type="button" onClick={()=>{if(t.kind!=='exception')onOpen({projectId:t.project_id,kind:t.kind,id:t.id});}}>查看{t.kind}业务对象</button>)}
  {reconciliation&&!d.workflow_projected&&!reconciliation.props.readOnly&&reconciliation.props.project.allowed_actions.includes('integration.pull')&&reconciliation.descriptors.find(s=>s.system===d.fact.source.system)&&<details><summary>准入此精确来源业务事实</summary><SystemOperationForm {...reconciliation.props} pull={d.fact.source} selected={null} descriptor={reconciliation.descriptors.find(s=>s.system===d.fact.source.system)!} pending={reconciliation.intents} step={{id:'source-admission:'+keyText(d.fact.source),context:reconciliation.context,title:'准入此来源业务事实',responsibleSystem:d.fact.source.system,operationKind:null,inputTypes:[keyText(d.fact.source)],outputTypes:[d.fact.payload.fact_type],receiptType:d.fact.payload.fact_type,blockingDependencies:[],nextStepIds:[]}} onReceipt={()=>{}} onRefresh={()=>{setRetry(n=>n+1);reconciliation.onRefresh();}}/></details>}
  <details><summary>原始来源与消费回执</summary><p>{keyText(d.fact.source)}</p><p>{d.fact.evidence}</p>{d.receipts?.map(r=><p key={r.operation_id}>原操作 {r.operation_id} · {r.phase} · 来源时间 {r.occurred_at} · 收到 {r.received_at} · 过账 {r.posted_at||'未提供'}</p>)}{d.origin?.kind==='operation'&&<p>精确源回执 {d.origin.operation_receipt.operation_id} · {d.origin.operation_receipt.phase}</p>}{d.origin?.kind==='inbox'&&<p>精确消费回执 {d.origin.inbox_receipt.delivery_id} · {d.origin.inbox_receipt.phase}</p>}{d.delivery_states?.map(x=><p key={x.delivery_id}>{SYSTEM_NAMES[x.consumer]} · {x.receipt?.phase||'待送达'}</p>)}<p>前因</p>{d.predecessors?.map(f=><p key={keyText(f.source)}>{keyText(f.source)}</p>)}</details>
 </article>)}</div>;
}


export function ObjectSystemFacts({api,target,onOpen}:{api:WorkflowApi;target:WorkflowTarget;onOpen(target:WorkflowTarget):void}){
 const pagination=useRef<AbortController|null>(null);
 const [keys,setKeys]=useState<SourceKey[]>([]),[cursor,setCursor]=useState<number|null>(null),[error,setError]=useState('');
 useEffect(()=>{if(!api.integrationLinks)return;const c=new AbortController();pagination.current=c;setKeys([]);setCursor(null);setError('');api.integrationLinks(target.projectId,target.kind,target.id,0,c.signal).then(page=>{if(!c.signal.aborted){setKeys((page.records||[]).map(r=>r.source_key));setCursor(page.continuation);}}).catch(e=>{if(!c.signal.aborted)setError(String(e));});return()=>c.abort();},[api,target.projectId,target.kind,target.id]);
 async function more(){const c=pagination.current;if(cursor===null||!c||c.signal.aborted)return;try{const page=await api.integrationLinks(target.projectId,target.kind,target.id,cursor,c.signal);if(c.signal.aborted)return;setKeys(v=>[...v,...page.records.map(r=>r.source_key)]);setCursor(page.continuation);}catch(e){if(!c.signal.aborted)setError(String(e));}}
 if(!keys.length&&!error)return null;
 return <details className="wf-evidence-details"><summary>已登记跨系统原始来源</summary><p>当前对象已读取 {keys.length} 条投影链接；{cursor===null?'登记链接读取完成':'还有链接未读取'}，不代表未登记外部历史。</p>{error&&<p role="alert">{error}</p>}<SystemFacts api={api} projectId={target.projectId} keys={keys} onOpen={onOpen}/>{cursor!==null&&<button onClick={()=>void more()}>读取更多对象来源</button>}</details>;
}
