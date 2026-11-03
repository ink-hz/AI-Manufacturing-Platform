import {useEffect,useRef,useState} from 'react';
import type {OEMWorkspaceProps} from '../OEMWorkspace';
import {readIntentMetadata} from './intentRecovery';
import {ConflictComparison} from '../ConflictComparison';
import {WorkflowError} from '../api';
import type {CommandResult,WorkflowCommand,ObjectKind,ObjectSummary} from '../types';
import type {BusinessStepDefinition,IntentSummary,SourceKey,OperationPayload,SystemDescriptor,IntegrationFact,ObjectRef} from './types';
import {CORE_FIELDS,CoreOperationFields,fieldNeeds,initialValue,record,sourceKey,keyText,fieldLabel,type DraftValue,type DomainChoices} from './CoreOperationFields';
import {ENTERPRISE_FIELDS,EnterpriseOperationFields} from './EnterpriseOperationFields';
import {EVIDENCE_FIELDS,EvidenceOperationFields} from './EvidenceOperationFields';
export const operationSpec=(op:string)=>CORE_FIELDS[op]||ENTERPRISE_FIELDS[op]||EVIDENCE_FIELDS[op];
function cleanDraft(v:DraftValue):unknown {if(Array.isArray(v))return v.map(cleanDraft);if(v&&typeof v==='object')return Object.fromEntries(Object.entries(v).filter(([,x])=>x!==null).map(([k,x])=>[k,cleanDraft(x)]));return v;}
interface Frozen {neverSubmitted?:boolean;command:WorkflowCommand;result?:CommandResult;error?:string}
// Actor/API scoped memory keeps drafts across ordinary workspace unmounts. Durable
// intents are recovered from the authenticated server list after a page reload.
const drafts=new WeakMap<object,Map<string,Frozen>>();
export function SystemOperationForm(p:OEMWorkspaceProps & {step:BusinessStepDefinition;descriptor:SystemDescriptor;selected:ObjectRef|null;pending:IntentSummary[];onReceipt(keys:SourceKey[]):void;onRefresh():void;pull?:SourceKey}){
 const op=p.pull?'bi.refresh':p.step.operationKind!;const id=`system-step:${p.project.id}:${p.step.context}:${p.step.id}`;
 const spec=operationSpec(op);const memory=drafts.get(p.api)||new Map<string,Frozen>();drafts.set(p.api,memory);
 const recovered=p.pending.find(x=>x.operation===(p.pull?'integration.pull':op)&&(!p.pull||!!x.source_key&&keyText(x.source_key)===keyText(p.pull))&&!['applied','rejected'].includes(x.phase));
 const [frozen,setFrozen]=useState<Frozen|undefined>(()=>memory.get(id)||(recovered?{command:{action:'mock_system.query',operation_id:crypto.randomUUID(),expected_version:p.project.version,intent_id:recovered.intent_id}}:undefined));
 const [value,setValue]=useState<DraftValue>(()=>{const v=record(initialValue(spec,p.project,op));if(p.selected){for(const name of ['work_order','revision','unit','shipment','order_line','material_lot','demand','test_run'])if(p.selected.kind===name){const key=name==='test_run'?'run_id':name+'_id';if(key in v)v[key]=p.selected.id;}}return v;});
 const [choices,setChoices]=useState<DomainChoices>({objects:{},facts:[]}),[pages,setPages]=useState<Record<string,number|null>>({}),[error,setError]=useState(''),[busy,setBusy]=useState(false),[loaded,setLoaded]=useState(false),[conflict,setConflict]=useState<WorkflowError|null>(null),[choiceRetry,setChoiceRetry]=useState(0);
 const live=useRef(true), dirty=useRef(false),recovery=useRef<WorkflowCommand|null>(null);
 const needs=fieldNeeds(spec,op);if(['customer.receive_shipment','overseas.receive_shipment','customer.confirm_delivery'].includes(op)){needs.sources.add('customer.delivery_receipt');needs.sources.add('overseas.delivery_receipt');}if(op==='product_test.run'||op==='product_test.calibrate'){needs.sources.clear();needs.sources.add('product_test.artifact');needs.objects.clear();}
 useEffect(()=>{live.current=true;return()=>{live.current=false;p.onDirty(id,false);};},[id]);
 useEffect(()=>{const c=new AbortController();setLoaded(false);setError('');setChoices({objects:{},facts:[]});setPages({});
  Promise.all([...[...needs.objects].map(async kind=>{const page=await p.api.objects(p.project.id,kind,50,0,c.signal);let items=page.items;if(p.selected?.kind===kind&&!items.some(x=>x.id===p.selected!.id)){const exact=await p.api.object(p.project.id,kind,p.selected.id,c.signal);items=[exact.summary,...items];}return {kind,items,total:page.total,offset:page.items.length};}),...[...needs.sources].map(async tag=>{const [system,...rest]=tag.split('.');const page=await p.api.systemFacts(p.project.id,system as SourceKey['system'],{object_type:rest.join('.'),limit:50},c.signal);return {tag,page};})]).then(rows=>{if(c.signal.aborted)return;const objects:DomainChoices['objects']={},facts:IntegrationFact[]=[],next:Record<string,number|null>={};for(const row of rows){if('kind'in row){objects[row.kind]=row.items;next[row.kind]=row.offset<row.total?row.offset:null;}else{facts.push(...row.page.records);next[row.tag]=row.page.continuation;}}setChoices({objects,facts});setPages(next);setLoaded(true);}).catch(e=>{if(!c.signal.aborted)setError(String(e));});return()=>c.abort();
 },[p.api,p.project.id,op,choiceRetry]);
 async function more(key:string){setBusy(true);try{const cursor=pages[key];if(cursor==null)return;if(key.includes('.')){const [system,...rest]=key.split('.');const page=await p.api.systemFacts(p.project.id,system as SourceKey['system'],{object_type:rest.join('.'),cursor,limit:50});if(live.current){setChoices(v=>({...v,facts:[...v.facts,...page.records]}));setPages(v=>({...v,[key]:page.continuation}));}}else{const page=await p.api.objects(p.project.id,key as ObjectKind,50,cursor);if(live.current){setChoices(v=>({...v,objects:{...v.objects,[key]:[...(v.objects[key as ObjectKind]||[]),...page.items]}}));setPages(v=>({...v,[key]:cursor+page.items.length<page.total?cursor+page.items.length:null}));}}}catch(e){if(live.current)setError(String(e));}finally{if(live.current)setBusy(false);}}
 function edit(v:DraftValue){if(frozen)return;setValue(v);dirty.current=true;p.onDirty(id,true);}
 function remember(v:Frozen){memory.set(id,v);if(live.current)setFrozen(v);}
 const intentId=(frozen?.command.action==='mock_system.execute'||frozen?.command.action==='integration.pull')?frozen.command.operation_id:frozen?.command.action==='mock_system.query'||frozen?.command.action==='mock_system.retry'?frozen.command.intent_id:null;
 async function send(action:'execute'|'query'|'retry'){
  if(busy)return;setBusy(true);setError('');let current=frozen;
  try{
   let command:WorkflowCommand;
   if(action==='execute'){
    const known=await readIntentMetadata(p.api,p.project.id);
    if(!live.current)return;
    const unresolved=known.find(x=>x.operation===(p.pull?'integration.pull':op)&&(!p.pull||!!x.source_key&&keyText(x.source_key)===keyText(p.pull))&&!['applied','rejected'].includes(x.phase));
    if(unresolved){remember({command:{action:'mock_system.query',intent_id:unresolved.intent_id,operation_id:crypto.randomUUID(),expected_version:p.project.version}});setError('已有未完成原操作，请查询或继续原操作');return;}

    command=p.pull?{action:'integration.pull',source_key:{system:p.pull.system,object_type:p.pull.object_type,external_id:p.pull.external_id,version:p.pull.version},operation_id:crypto.randomUUID(),expected_version:p.project.version}:{action:'mock_system.execute',system:p.step.responsibleSystem,payload:cleanDraft(value) as OperationPayload,operation_id:crypto.randomUUID(),expected_version:p.project.version};
    current={command};remember(current);p.onDirty(id,true);
   }else{
    if(!intentId)throw Error('缺少持久化原操作，请重新读取恢复列表');
    if(!recovery.current||recovery.current.action!==`mock_system.${action}`){const latest=await p.api.project(p.project.id);recovery.current={action:action==='query'?'mock_system.query':'mock_system.retry',intent_id:intentId,operation_id:crypto.randomUUID(),expected_version:latest.version};}
    command=recovery.current;
   }
   const result=await p.api.command(p.project.id,command);
   if(!result)throw Error('尚未收到结果');
   remember({...current!,result,error:undefined});recovery.current=null;
   if(result.integration?.projection_applied||result.integration?.phase==='rejected'){p.onDirty(id,false);dirty.current=false;}
   if(!live.current)return;p.onChanged(result);p.onRefresh();
   const intents=await readIntentMetadata(p.api,p.project.id);if(!live.current)return;const found=intents.find(x=>x.intent_id===result.integration?.intent_id);if(p.pull)p.onReceipt([p.pull]);if(found?.receipt){p.onReceipt(found.receipt.source_keys);if(found.receipt.error&&live.current)setError(found.receipt.error.message);}
  }catch(e){
   if(action!=='execute'&&e instanceof WorkflowError&&e.code==='NOT_FOUND'&&live.current){
    // Authoritative resolution: the durable intent store has no record, so the original submit was rejected
    // before intent persistence and produced zero source effects. Unfreeze exactly like 核对未提交草稿.
    try{const latest=await p.api.project(p.project.id);if(!live.current)return;p.onChanged({project_id:p.project.id,project_version:latest.version,current_project_version:latest.version,integration:undefined} as CommandResult);memory.delete(id);setFrozen(undefined);setConflict(null);recovery.current=null;setError('已确认服务端未保存原操作，可继续编辑草稿');return;}catch(inner){if(live.current)setError(String(inner));return;}
   }
   if(e instanceof WorkflowError&&e.status===409&&live.current)setConflict(e);const detail=e instanceof WorkflowError?[e.message,...e.reasons].join('；'):String(e);if(current)remember({...current,error:detail,neverSubmitted:e instanceof WorkflowError&&(e.status===422||(e.status===409&&e.code==='VERSION_CONFLICT'))&&!e.fields.intent_id});if(live.current)setError(detail);if(live.current&&e instanceof WorkflowError&&(e.status===403||e.status===401)){p.onReceipt([]);setChoices({objects:{},facts:[]});}}
  finally{if(live.current)setBusy(false);}
 }
 async function verifyUnsubmitted(){
  if(!frozen?.neverSubmitted||frozen.result)return;setBusy(true);try{let offset=0,found=false,total=1;while(offset<total){const page=await p.api.integrationIntents(p.project.id,200,offset);found ||= page.records.some(i=>i.intent_id===intentId);offset+=page.records.length;total=page.total;if(found||!page.records.length)break;}if(found){setError('已找到持久化原操作，请查询原操作结果');return;}const latest=await p.api.project(p.project.id);p.onChanged({project_id:p.project.id,project_version:latest.version,current_project_version:latest.version,integration:undefined} as CommandResult);memory.delete(id);setFrozen(undefined);setConflict(null);setError('已确认服务端未保存原操作，可继续编辑草稿');}catch(e){setError(String(e));}finally{setBusy(false);}
 }
 const terminal=frozen?.result?.integration?.projection_applied||frozen?.result?.integration?.phase==='rejected';
 let scopedChoices=choices;
 if(['customer.receive_shipment','overseas.receive_shipment','customer.confirm_delivery'].includes(op)){
  const shipment=record(value).shipment as SourceKey|undefined;
  const fact=choices.facts.find(f=>f.payload.fact_type==='wms.shipment'&&shipment&&keyText(sourceKey(f))===keyText(shipment));
  const shipped=new Set(fact?.payload.fact_type==='wms.shipment'?fact.payload.units.map(u=>u.unit_id):[]),signed=new Set<string>();
  for(const f of choices.facts){const v=f.payload;if((v.fact_type==='customer.delivery_receipt'||v.fact_type==='overseas.delivery_receipt')&&shipment&&keyText(v.shipment)===keyText(shipment)&&v.decision!=='rejected')for(const id of v.decision==='partial'?v.accepted_unit_ids||[]:v.units.map(u=>u.unit_id))signed.add(id);}
  scopedChoices={...choices,objects:{...choices.objects,unit:(choices.objects.unit||[]).filter(u=>shipped.has(u.id)&&(op==='customer.confirm_delivery'?signed.has(u.id):!signed.has(u.id)))}};
 }
 const Fields=CORE_FIELDS[op]?CoreOperationFields:ENTERPRISE_FIELDS[op]?EnterpriseOperationFields:EvidenceOperationFields;
 return <form aria-label={`办理${p.step.title}`} onSubmit={e=>{e.preventDefault();void send('execute');}}>
  {!frozen&&p.pull&&<p>精确来源版本已绑定：{keyText(p.pull)}；按当前权限准入业务投影。</p>}
  {!frozen&&!p.pull&&<Fields operation={op} value={value} onChange={edit} project={p.project} choices={scopedChoices} disabled={busy||!loaded}/>}
  {Object.entries(pages).filter(([,cursor])=>cursor!==null).map(([key])=><button type="button" disabled={busy} key={key} onClick={()=>void more(key)}>读取更多{fieldLabel(key)}（当前选择范围有界）</button>)}
  {!loaded&&!frozen&&error&&<button type="button" onClick={()=>setChoiceRetry(n=>n+1)}>重新读取业务选项</button>}
  {(error||frozen?.error)&&<p role="alert">{error||frozen?.error}</p>}
  {conflict&&frozen&&<ConflictComparison api={p.api} projectId={p.project.id} version={frozen.command.expected_version} error={conflict} draft={frozen.command}/>}
  {frozen?<><p>原操作资料已固定；查询和继续沿用原来源操作。</p>{frozen.result?.integration&&<p>来源接受 {String(frozen.result.integration.source_committed??'未知')} · 业务投影 {frozen.result.integration.projection_applied?'已完成':'待完成'}</p>}
   {!terminal&&<>{frozen.neverSubmitted&&<button type="button" disabled={busy} onClick={()=>void verifyUnsubmitted()}>核对未提交草稿</button>}<button type="button" disabled={busy} onClick={()=>void send('query')}>查询原操作结果</button><button type="button" disabled={busy} onClick={()=>void send('retry')}>继续原操作</button></>}
   {terminal&&<button type="button" disabled={busy} onClick={()=>void send('retry')}>同步来源消费与投影</button>}
   {terminal&&<button type="button" onClick={()=>p.requestLeave(()=>{memory.delete(id);setFrozen(undefined);setError('');setValue(initialValue(spec,p.project,op));p.onRefresh();})}>办理下一笔</button>}
   <details><summary>固定操作身份与版本</summary><p>原来源操作 {intentId} · 原版本 {frozen.command.expected_version} · 当前项目版本 {p.project.version}</p></details>
  </>:<button disabled={busy||!loaded} type="submit">执行：{p.step.title}</button>}
 </form>;
}
