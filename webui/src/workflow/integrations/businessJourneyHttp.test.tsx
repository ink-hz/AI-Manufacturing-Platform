import {act,useState} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {mkdtemp,mkdir,writeFile,realpath} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {startHttpHost,projectInput} from '../httpTestHost';
import {OrdersWorkspace} from '../OrdersWorkspace';
import {SupplyWorkspace} from '../SupplyWorkspace';
import {ExecutionWorkspace} from '../ExecutionWorkspace';
import {LaboratoryWorkspace} from '../LaboratoryWorkspace';
import {QualityWorkspace} from '../QualityWorkspace';
import {DeliveryWorkspace} from '../DeliveryWorkspace';
import {IntroductionWorkspace} from '../IntroductionWorkspace';
import {TraceWorkspace} from '../TraceWorkspace';
import {WorkflowHome} from '../WorkflowHome';
import type {ProjectDetail,CommandResult,CommandFields,MutationAcknowledgement} from '../types';
import type {BusinessContext,OperationPayload,SourceKey,JourneyObservation,FactDetail} from './types';
import {BUSINESS_STEPS} from './businessSteps';
import {fieldLabel,keyText,record,type DraftValue} from './CoreOperationFields';
const amount=(quantity:string)=>({quantity,unit:'piece',scale:0});
const NOW='2026-11-03T00:00:00+00:00';
let host:Awaited<ReturnType<typeof startHttpHost>>,owner:Awaited<ReturnType<Awaited<ReturnType<typeof startHttpHost>>['login']>>,container:HTMLDivElement,root:Root,project:ProjectDetail,last:CommandResult|undefined,output:string;
let observations:JourneyObservation[]=[];let requests:JourneyObservation['requests']=[];let faultNext='';let mountEpoch=0;let inFlight=0;let wireFailures:string[]=[];
async function settle(){let quiet=0;for(let n=0;n<400;n++){await act(async()=>{await new Promise(r=>setTimeout(r,20));});quiet=inFlight?0:quiet+1;if(quiet>=3)return;}throw Error('HTTP/React reads did not settle');}
function capture(session:typeof owner){const realCommand=session.api.command;session.api.command=async(...args)=>{const command=args[1];if(command.action==='mock_system.execute'&&command.payload.operation===faultNext){faultNext='';await session.configureNetworkFault(args[0],command.system,command.operation_id);}const entry={action:command.action,operationId:command.operation_id,intentId:'intent_id'in command?command.intent_id:command.action==='mock_system.execute'||command.action==='integration.pull'?command.operation_id:null,phase:null as JourneyObservation['requests'][number]['phase']};requests.push(entry);const result=await realCommand(...args);entry.phase=result.integration?.phase||null;last=result;return result;};}
beforeEach(async()=>{host=await startHttpHost({businessClock:NOW});owner=await host.login('owner');capture(owner);vi.stubGlobal('fetch',async(input:RequestInfo|URL,init?:RequestInit)=>{inFlight++;try{const r=await owner.transport(input,init);if(!r.ok)wireFailures.push(String(input)+' '+String(init?.body)+' '+await r.clone().text());return r;}finally{inFlight--;}});container=document.createElement('div');document.body.append(container);root=createRoot(container);observations=[];requests=[];wireFailures=[];last=undefined;const base=process.env.WORKFLOW_MOCK_JOURNEY_EVIDENCE_DIR||tmpdir();await mkdir(base,{recursive:true,mode:0o700});output=await realpath(await mkdtemp(join(base,'mock-react-journey-')));await writeFile(join(output,'manifest.json'),JSON.stringify({owner:'manufacturing-mock-react-journey-v1',directory:output,created_at:new Date().toISOString(),business_clock:NOW}),{flag:'wx',mode:0o600});},20000);
afterEach(async(context)=>{const failed=context.task.result?.state==='fail';if(failed)await writeFile(join(output,'failure.json'),JSON.stringify({dom:container.textContent,wireFailures,fixture:host.root}),{flag:'wx',mode:0o600});await act(async()=>root.unmount());container.remove();await writeFile(join(output,'observations.json'),JSON.stringify(observations,null,2),{flag:'wx',mode:0o600});await host.close(failed);vi.unstubAllGlobals();});
async function until(fn:()=>boolean,message='condition'){for(let n=0;n<300;n++){if(fn())return;await act(async()=>{await new Promise(r=>setTimeout(r,10));});}throw Error(message+'\n'+container.textContent);}
async function set(label:string,value:string){await until(()=>!!container.querySelector(`[aria-label="${label}"]`),'missing '+label);const el=container.querySelector(`[aria-label="${label}"]`) as HTMLInputElement|HTMLSelectElement;await act(async()=>{Object.getOwnPropertyDescriptor(el instanceof HTMLSelectElement?HTMLSelectElement.prototype:HTMLInputElement.prototype,'value')!.set!.call(el,value);el.dispatchEvent(new Event(el instanceof HTMLSelectElement?'change':'input',{bubbles:true}));});}
async function click(text:string){await until(()=>[...container.querySelectorAll('button')].some(b=>b.textContent===text&&!b.disabled),'button '+text);await act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent===text)!.click());}
async function fill(value:unknown,path='',name=''){
 if(value===null||value===undefined||name==='target_type')return;
 if(typeof value==='object'&&!Array.isArray(value)){
  const v=value as Record<string,unknown>;
  if('system'in v&&'external_id'in v){if(!container.querySelector(`[aria-label="${path}"]`))await click('补充'+fieldLabel(name));await set(path,keyText(v as unknown as SourceKey));return;}
  if('unit_id'in v&&'sn'in v&&container.querySelector(`[aria-label="${path}"]`)){await set(path,String(v.unit_id));return;}
  for(const [k,x] of Object.entries(v)){if(k==='operation')continue;await fill(x,path?path+' / '+fieldLabel(k):fieldLabel(k),k);}return;
 }
 if(Array.isArray(value)){for(let i=0;i<value.length;i++){
   const rowPath=`${path} ${i+1}`;
   if(![...container.querySelectorAll('[aria-label]')].some(el=>(el.getAttribute('aria-label')||'').startsWith(rowPath))){await click('添加'+fieldLabel(name));}
   await fill(value[i],rowPath,name);
  }return;
 }
 let el=container.querySelector(`[aria-label="${path}"]`) as HTMLInputElement|HTMLSelectElement|null;
 if(!el){const optional=[...container.querySelectorAll('button')].find(b=>b.textContent==='补充'+fieldLabel(name));if(optional){await act(async()=>optional.click());el=container.querySelector(`[aria-label="${path}"]`);} }
 // New source-owned IDs are allocated by the UI; never entered by the user.
 if(!el&&name.endsWith('_id'))return;
 if(!el)throw Error('missing field '+path);
 if(el.type==='checkbox'){if((el as HTMLInputElement).checked!==value)await act(async()=>el!.click());return;}
 if(el instanceof HTMLInputElement&&el.readOnly){expect(el.value).toBe(String(value));return;}
 await set(path,String(value));
}
async function setup(scenario:'empty'|'supply'|'execution'){
 project=await owner.api.createProject({...projectInput('12'),name:'Network Camera',mode:'oem',customer_id:'C',product:'P',contract:{customer_approval_required:true,customer_release_required:false,acceptance_required:true,customer_revision:'A',internal_revision:'A',material_ownership_rules:'customer'}});
 const setup=await owner.setupNetwork(project.id,scenario);project=await owner.api.project(project.id);await writeFile(join(output,'fixture-initialization.json'),JSON.stringify({projectId:project.id,mode:project.mode,contract:project.contract,scenario,businessClock:NOW,countedAsUiCoverage:false}),{flag:'wx',mode:0o600});return setup.refs;
}
async function manual(fields:CommandFields){let result!:CommandResult;await act(async()=>{project=await owner.api.project(project.id);result=await owner.api.command(project.id,{...fields,operation_id:crypto.randomUUID(),expected_version:project.version});});await settle();return result;}
function Workspace({context}:{context:BusinessContext}){const [p,setProject]=useState(project);const props={api:owner.api,project:p,onDirty:()=>{},onOpen:()=>{},readOnly:false,requestLeave:(f:()=>void)=>f(),onChanged:(r:MutationAcknowledgement)=>{if('operation_id'in r)last=r;void owner.api.project(project.id).then(x=>{project=x;setProject(x);});}};
 switch(context){case 'orders':case 'engineering':return <OrdersWorkspace {...props} engineering={context==='engineering'}/>;case 'introduction':return <IntroductionWorkspace {...props}/>;case 'supply':return <SupplyWorkspace {...props} supplyMode="legacy"/>;case 'handoff':return <SupplyWorkspace {...props} supplyMode="handoff" currentUserId={owner.identity.user_id}/>;case 'execution':return <ExecutionWorkspace {...props}/>;case 'laboratory':return <LaboratoryWorkspace {...props}/>;case 'quality':return <QualityWorkspace {...props}/>;case 'delivery':return <DeliveryWorkspace {...props}/>;case 'trace':return <TraceWorkspace {...props}/>;case 'home':return <WorkflowHome api={owner.api} data={null} projects={[p]} projectsReady dashboardError="" projectsError="" refresh={0} active onRefresh={()=>{}} onOpen={()=>{}} onNavigate={()=>{}}/>;}
}
async function mount(context:BusinessContext){project=await owner.api.project(project.id);await act(async()=>root.render(<Workspace key={context+ ++mountEpoch} context={context}/>));if(context==='home')await set('BI 项目',project.id);await until(()=>!!container.querySelector('[aria-label="系统业务步骤"]'),'workspace '+context);await settle();}
function latest():CommandResult{if(!last)throw Error('No acknowledgement');return last;}
async function submit(context:BusinessContext,id:string,payload:OperationPayload,blocked?:string,synchronize=true):Promise<FactDetail[]>{
 const requestStart=requests.length;await set('系统业务步骤',id);await until(()=>!!container.querySelector(`form[aria-label="办理${BUSINESS_STEPS.find(s=>s.id===id)!.title}"] button[type=submit]:not(:disabled)`),'form loaded '+id);
 if(payload.operation==='product_test.run'||payload.operation==='product_test.calibrate')await set('受控原始证据',payload.artifact_checksum);else await fill(payload);last=undefined;await click('执行：'+BUSINESS_STEPS.find(s=>s.id===id)!.title);
 await until(()=>!!last||!!container.querySelector('form [role=alert]'),'source result '+id);
 if(!last)throw Error('source failed '+id+' '+wireFailures.join('\n')+' '+container.textContent);
 await settle();expect(latest().integration?.intent_id).toBeTruthy();
 let result=latest();for(let n=0;!result.integration?.projection_applied&&n<4;n++){await click(n===0?'查询原操作结果':'继续原操作');await until(()=>!!last&&last.operation_id!==result.operation_id);result=latest();}
 expect(result.integration?.projection_applied,id+': '+container.textContent).toBe(true);
 for(let n=0;synchronize&&n<4;n++){const previous=latest().operation_id;await click('同步来源消费与投影');await until(()=>!!last&&last.operation_id!==previous);await settle();result=latest();if(!(result as CommandResult&{network?:{pending:number}}).network?.pending)break;}
 const page=await owner.api.integrationIntents(project.id,200,0),intent=page.records.find(i=>i.intent_id===result.integration!.intent_id)!;expect(intent.receipt?.phase).toBe('accepted');
 const facts=await Promise.all(intent.receipt!.source_keys.map(k=>owner.api.systemFact(project.id,k)));
 const panel=container.querySelector('[data-business-context]') as HTMLElement;const selected=panel.dataset.selectedId?{project_id:project.id,kind:panel.dataset.selectedKind as JourneyObservation['targets'][number]['kind'],id:panel.dataset.selectedId}:null;
 const observation:JourneyObservation={outcome:'applied',requests:requests.slice(requestStart),context,stepId:id,projectId:project.id,selected,inputs:facts.flatMap(d=>d.fact.caused_by||[]),outputs:intent.receipt!.source_keys,targets:facts.flatMap(d=>d.projection?.targets||[]),operationId:result.operation_id,intentId:intent.intent_id,receipts:[intent.receipt!],sourceStates:facts.map(sourceState),blocker:blocked||null,nextAction:BUSINESS_STEPS.find(s=>s.id===id)!.nextStepIds.join(','),observedAt:new Date().toISOString()};observations.push(observation);await writeFile(join(output,`${observations.length.toString().padStart(3,'0')}-${id}.json`),JSON.stringify(observation,null,2),{flag:'wx',mode:0o600});return facts;
}
const sourceState=(d:FactDetail)=>({source:key(d),origin:d.origin||{kind:'untracked' as const},sourceAccepted:d.source_accepted??null,consumerDelivered:d.consumer_delivered??null,workflowProjected:!!d.workflow_projected,sapPosted:d.sap_posted??null,deliveryStates:d.delivery_states||[]});
const key=(d:FactDetail)=>({system:d.fact.source.system,object_type:d.fact.source.object_type,external_id:d.fact.source.external_id,version:d.fact.source.version});
const target=(d:FactDetail,kind:string)=>d.projection!.targets.find(t=>t.kind===kind)!.id;
it('journey A submits CRM, SAP and PDM in orders and engineering, with independent approvals',async()=>{
 await setup('empty');const outsider=await host.login('outsider');const denied=await outsider.transport(`/api/v1/manufacturing/workflow/projects/${project.id}/integration-intents`);expect(denied.status).toBe(404);expect(await denied.text()).not.toContain('intent_id');await mount('orders');
 const [demand]=await submit('orders','orders.crm-demand',{operation:'crm.publish_demand',customer_id:'C',product:'P',demand_kind:'firm',amount:amount('2'),due_date:'2026-11-10'});
 for(const dimension of ['technical','material','capacity','commercial','quality'] as const)await manual({action:'demand.review',demand_id:target(demand,'demand'),dimension,decision:'approved',evidence:'Actual responsible review'});
 await mount('orders');
 const [order]=await submit('orders','orders.sap-order',{operation:'sap.release_order',demand_id:target(demand,'demand'),customer_id:'C',product:'P',amount:amount('2'),due_date:'2026-11-10'});
 await mount('engineering');
 const [revision]=await submit('engineering','engineering.pdm-release',{operation:'pdm.publish_revision',bom_materials:[{material_id:'M',per_unit:amount('1')}],package_id:'PKG-HTTP',revision:'A',customer_revision:'A',internal_revision:'A',firmware_version:'F1',items:[{id:'drawing',kind:'drawing',title:'Drawing',revision:'A',status:'verified',evidence:'Released drawing'}],route_steps:[{station:'assembly',instruction_version:'S1'}],test_spec:{version:'T1',program_version:'P1',measurements:[{name:'voltage',unit:'piece',lower:'4',upper:'6'}]},released_at:NOW});
 const rid=target(revision,'revision');
 await submit('engineering','engineering.customer-approval',{operation:'customer.approve_revision',revision_id:rid,revision:key(revision),customer_id:'C',decision:'approved',external_signer:'Customer design owner',signed_at:NOW,evidence:'Separate customer approval'});
 const npi=await manual({action:'npi.open',revision_id:rid,product_family:'P',scenario:'first_introduction',required_checks:['design'],work_order_ids:[]});
 const approvalTarget={target_type:'engineering' as const,source_key:key(revision),npi_id:npi.object_id,revision_id:rid,checks:[{code:'design',required:true,decision:'pass' as const,evidence:'Design checked',reason:'Verified'}]};
 await mount('engineering');const [request]=await submit('engineering','engineering.oa-request',{operation:'oa.request_approval',target:approvalTarget,requested_by:'Engineering',evidence:'Internal review request'});
 await mount('introduction');await submit('introduction','introduction.oa-review',{operation:'oa.decide_approval',target:approvalTarget,request:key(request),decision:'approved',external_signer:'Engineering authority',signed_at:NOW,evidence:'Internal engineering check'});
 await mount('engineering');const [wo]=await submit('engineering','engineering.sap-work-order',{operation:'sap.release_work_order',order_line_id:target(order,'order_line'),revision_id:rid,released_revision:key(revision),amount:amount('2'),trial_amount:amount('1'),purpose:'production',planned_start:NOW,planned_end:'2026-11-04T00:00:00+00:00'});
 expect(wo.consumer_delivered).not.toBeUndefined();expect(target(wo,'work_order')).toBeTruthy();expect(observations.every(o=>o.receipts[0].phase==='accepted')).toBe(true);
 const other=await owner.api.createProject({...projectInput('1'),mode:'oem',name:'Other authorized project'});await owner.setupNetwork(other.id,'empty');const foreign=await owner.transport(`/api/v1/manufacturing/workflow/projects/${other.id}/systems/pdm/facts/revision/${revision.fact.source.external_id}?version=1`);expect(foreign.status).toBe(404);expect(await foreign.text()).not.toContain('PKG-HTTP');
},60000);

it('journey B recovers real shortage through Supply receipts and IQC before default handoff reservation and pick',async()=>{
 const refs=await setup('supply');const receiver=await host.login('production');
 await owner.api.grant(project.id,receiver.identity.user_id,{operation_id:crypto.randomUUID(),expected_version:project.version,scope:{kind:'project',project_id:project.id},roles:['production'],qualifications:[],active:true,evidence:'Explicit test role for the designated manual receiver; no HR grant'});
 await mount('supply');
 const [plan]=await submit('supply','supply.sap-plan',{operation:'sap.publish_plan',input_revision_ids:[refs.revision],input_order_versions:[{order_line_id:refs.order_line,version:1}],requirements:[{requirement_id:crypto.randomUUID(),work_order_id:refs.work_order,execution_scope:'common',material_id:'M',owner_id:'C',amount:amount('12')}],cutoff:NOW});
 if(plan.fact.payload.fact_type!=='sap.plan')throw Error('plan receipt');refs.requirement=plan.fact.payload.requirements[0].requirement_id;

 expect(container.textContent).toContain('WMS 实物收货');expect(container.textContent).toContain('MES 检验回执');
 const requirement=await owner.api.object(project.id,'requirement',refs.requirement);expect(requirement.summary.material_balance?.qualified).toBe('8');
 await set('系统业务步骤','supply.wms-reserve');await until(()=>!!container.querySelector('form button[type=submit]:not(:disabled)'));
 await fill({operation:'wms.reserve',requirement_id:refs.requirement,work_order_id:refs.work_order,allocations:[{material_lot_id:refs.lot,material_id:'M',owner_id:'C',amount:amount('12'),qualification:refs.qualification}]});last=undefined;await click('执行：WMS 合格库存预留');await until(()=>!!container.querySelector('form [role=alert]')||last?.integration?.phase==='rejected');await settle();
 const blockedText=container.querySelector('form [role=alert]')?.textContent||'源拒绝：合格库存不足';expect(blockedText).toMatch(/stock|quantity|qualified|库存|数量|合格/i);
 const blockedRequest=requests.at(-1)!;const intent=(await owner.api.integrationIntents(project.id,200,0)).records.find(i=>i.intent_id===blockedRequest.intentId);const rejected:JourneyObservation={outcome:'blocked',context:'supply',stepId:'supply.wms-reserve',projectId:project.id,selected:null,inputs:[refs.qualification],outputs:[],targets:[],operationId:blockedRequest.operationId,intentId:blockedRequest.intentId!,requests:[blockedRequest],receipts:intent?.receipt?[intent.receipt]:[],sourceStates:[],blocker:blockedText,nextAction:'supply.wms-receipt',observedAt:new Date().toISOString()};observations.push(rejected);await writeFile(join(output,'001-supply.wms-reserve-blocked.json'),JSON.stringify(rejected,null,2),{flag:'wx',mode:0o600});
 const [receipt]=await submit('supply','supply.wms-receipt',{operation:'wms.receive',custodian:'warehouse',commitment_id:refs.commitment,material_lot_id:refs.lot,lot_id:'LOT',material_id:'M',owner_id:'C',amount:amount('4'),location:'receiving',supplier_batch:'B1',expiry:'2026-12-03'},blockedText);
 const [iqc]=await submit('supply','supply.mes-iqc',{operation:'mes.inspect',receipt:key(receipt),accepted:amount('4'),rejected:amount('0'),evidence:'Receipt-specific replenishment IQC'});
 expect(iqc.fact.payload.fact_type).toBe('mes.iqc');
 const qualifications=await owner.api.systemFacts(project.id,'wms',{object_type:'qualification',limit:50});expect(qualifications.records.length).toBe(2);
 const allocations=qualifications.records.map((f,i)=>({material_lot_id:refs.lot,material_id:'M',owner_id:'C',amount:amount(i===0?'8':'4'),qualification:f.source}));
 await set('系统业务步骤','supply.wms-reserve');await click([...container.querySelectorAll('button')].some(b=>b.textContent==='办理下一笔')?'办理下一笔':'核对未提交草稿');await settle();
 const [reservation]=await submit('supply','supply.wms-reserve',{operation:'wms.reserve',requirement_id:refs.requirement,work_order_id:refs.work_order,allocations});
 await mount('handoff');expect(container.textContent).toContain('发起物料交接');expect(container.textContent).toContain('待检物料不可配料');
 const [picked]=await submit('handoff','handoff.wms-pick',{operation:'wms.pick',work_order_id:refs.work_order,allocations:allocations.map(a=>({...a,reservation:key(reservation)})),source_custody:{location:'receiving',custodian:'warehouse'},destination_custody:{location:'line',custodian:'production'},cause:key(reservation),evidence:'Picked qualified replenished material'},undefined,false);
 await submit('handoff','handoff.sap-accounting',{operation:'sap.post_movement',cause:key(picked),account:'raw-custody',allocations:allocations.map(a=>({...a,reservation:key(reservation)})),evidence:'Exact picked physical allocations'});
 const balanceBefore=(await owner.api.object(project.id,'material_lot',refs.lot)).summary.material_balance;
 await set('系统业务步骤','handoff.manual-receipt');await click('发起物料交接');await settle();
 await set('物料批次',refs.lot);await set('交接数量','12');await set('交出位置','Warehouse');await set('送达位置','Assembly');await set('接收人',receiver.identity.user_id);await set('关联工单',refs.work_order);
 const manualStart=requests.length;last=undefined;await click('保存交接');await until(()=>!!last);await settle();const handoffId=latest().object_id;
 await act(async()=>root.render(null));owner=receiver;capture(owner);await mount('handoff');await click('确认接收');await settle();
 last=undefined;await act(async()=>container.querySelector('form[aria-label="确认接收"]')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));await until(()=>!!last);await settle();
 const handoff=await owner.api.object(project.id,'material_handoff',handoffId);expect(handoff.value).toMatchObject({kind:'material_handoff',state:'received',receipt:{received_quantity:'12',received_location:'Assembly',actor_id:receiver.identity.user_id}});
 expect((await owner.api.object(project.id,'material_lot',refs.lot)).summary.material_balance).toEqual(balanceBefore);
 const manualObservation:JourneyObservation={outcome:'applied',context:'handoff',stepId:'handoff.manual-receipt',projectId:project.id,selected:{project_id:project.id,kind:'material_handoff',id:handoffId},inputs:[],outputs:[],targets:[{project_id:project.id,kind:'material_handoff',id:handoffId}],operationId:latest().operation_id,intentId:null,requests:requests.slice(manualStart),receipts:[],sourceStates:[],blocker:null,nextAction:'execution.mes-run',observedAt:new Date().toISOString()};observations.push(manualObservation);await writeFile(join(output,`${observations.length.toString().padStart(3,'0')}-handoff.manual-receipt.json`),JSON.stringify(manualObservation,null,2),{flag:'wx',mode:0o600});


},60000);

it('journey C executes MES and controlled laboratory artifacts from the existing execution/laboratory workspaces',async()=>{
 const refs=await setup('execution');await mount('execution');
 const [employee]=await submit('execution','execution.hr-employee',{operation:'hr_sap.publish_employee',employee_id:'HTTP-E2',display_name:'HTTP operator',organization:'Factory',position:'Assembly',active:true});
 await submit('execution','execution.hr-qualification',{operation:'hr_beisen.publish_qualification',employee:key(employee),qualification:'assembly',training_reference:'HTTP-training',valid_from:'2026-11-02T00:00:00+00:00',valid_until:'2026-11-04T00:00:00+00:00',evidence:'Current independently recorded training'});
 const [shift]=await submit('execution','execution.hr-shift',{operation:'hr_dingtalk.assign_shift',employee:key(employee),work_order_id:refs.work_order,shift_id:'HTTP-SHIFT',starts_at:'2026-11-02T23:00:00+00:00',ends_at:'2026-11-03T08:00:00+00:00',attendance:'present'});
 const processRequests=await owner.api.systemFacts(project.id,'mes',{object_type:'process_request',limit:50});const process=processRequests.records.at(-1)!;
 const [equipment]=await submit('execution','execution.plc-ready',{operation:'plc.set_state',equipment:'EQ1',state:'available',program_version:'P1',process_request:process.source,observed_at:NOW,evidence:'Independent current PLC program acknowledgement'});
 refs.start_payload={...refs.start_payload,operator:key(employee),shift:key(shift),equipment:key(equipment)};
 const beforeApproval=await owner.api.object(project.id,'work_order',refs.work_order);if(beforeApproval.value.kind!=='work_order')throw Error('work order');
 expect(beforeApproval.value.trial_readiness.checks.find(c=>c.kind==='customer')).toMatchObject({required:true,status:'blocked'});
 await set('系统业务步骤','execution.mes-run');await settle();await fill(refs.start_payload);last=undefined;const gateStart=requests.length;await click('执行：MES 开工');await until(()=>!!container.querySelector('form [role=alert]'));await settle();
 const gateError=container.querySelector('form [role=alert]')!.textContent!;expect(gateError).toMatch(/customer|readiness|客户|准备/i);
 const gateRequest=requests.at(-1)!;const gateIntent=(await owner.api.integrationIntents(project.id,200,0)).records.find(i=>i.intent_id===gateRequest.intentId);
 const gateObservation:JourneyObservation={outcome:'blocked',context:'execution',stepId:'execution.mes-run',projectId:project.id,selected:{project_id:project.id,kind:'work_order',id:refs.work_order},inputs:[],outputs:[],targets:[],operationId:gateRequest.operationId,intentId:gateIntent?.intent_id||null,requests:requests.slice(gateStart),receipts:gateIntent?.receipt?[gateIntent.receipt]:[],sourceStates:[],blocker:gateError,nextAction:'engineering.customer-approval',observedAt:new Date().toISOString()};observations.push(gateObservation);await writeFile(join(output,`${observations.length.toString().padStart(3,'0')}-execution.mes-run-blocked.json`),JSON.stringify(gateObservation,null,2),{flag:'wx',mode:0o600});
 const revisionLink=(await owner.api.integrationLinks(project.id,'revision',refs.revision)).records.find(r=>r.source_key.system==='pdm'&&r.source_key.object_type==='revision')!;
 await mount('engineering');await submit('engineering','engineering.customer-approval',{operation:'customer.approve_revision',revision_id:refs.revision,revision:revisionLink.source_key,customer_id:'C',decision:'approved',external_signer:'Required customer design authority',signed_at:NOW,evidence:'Required matching contractual revision approval'});
 const afterApproval=await owner.api.object(project.id,'work_order',refs.work_order);if(afterApproval.value.kind!=='work_order')throw Error('work order');expect(afterApproval.value.trial_readiness.checks.find(c=>c.kind==='customer')).toMatchObject({required:true,status:'ready'});
 await mount('execution');await set('系统业务步骤','execution.mes-run');await settle();
 // The gate rejection has two legitimate durable outcomes: a persisted rejected intent (terminal, 办理下一笔)
 // or a pre-persistence workflow rejection with zero source effects. Resolve through the authoritative query:
 // NOT_FOUND must unfreeze the retained draft (已确认服务端未保存原操作) instead of dead-ending the form.
 if(![...container.querySelectorAll('button')].some(b=>b.textContent==='办理下一笔'&&!b.disabled)){
  await click('查询原操作结果');await settle();
  await until(()=>container.textContent!.includes('已确认服务端未保存原操作')||[...container.querySelectorAll('button')].some(b=>b.textContent==='办理下一笔'),'post-gate recovery resolution');
 }
 const gateFinal=(await owner.api.integrationIntents(project.id,200,0)).records.find(i=>i.intent_id===gateRequest.intentId);
 if(gateFinal)expect(gateFinal.phase).toBe('rejected');
 if([...container.querySelectorAll('button')].some(b=>b.textContent==='办理下一笔'&&!b.disabled)){await click('办理下一笔');await settle();}
 const [start]=await submit('execution','execution.mes-run',refs.start_payload);
 const reservations=await owner.api.systemFacts(project.id,'wms',{object_type:'reservation',limit:50});const reservation=reservations.records[0];if(reservation.payload.fact_type!=='wms.reservation')throw Error('reservation');
 const allocation={...reservation.payload.allocations[0],amount:amount('1'),reservation:reservation.source};
 const [execution]=await submit('execution','execution.mes-pass',{operation:'mes.pass',work_order_id:refs.work_order,unit:refs.units[0],revision_id:refs.revision,operator:refs.start_payload.operator,shift:refs.start_payload.shift,equipment:refs.start_payload.equipment,station:'assembly',route_version:'S1',program_version:'P1',firmware_version:'F1',occurred_at:NOW,material_uses:[allocation],result:'pass'});
 const run=await manual({action:'test_run.start',plan_id:refs.test_plan,unit_id:refs.units[0].unit_id,rework_order_id:null});
 await mount('laboratory');const [prepared]=await submit('laboratory','laboratory.prepare-artifact',{operation:'product_test.prepare_artifact',run_id:run.object_id,template:'pass-v1'});
 await set('系统业务步骤','laboratory.product-test');await until(()=>!!container.querySelector('[aria-label="受控原始证据"] option[value]:not([value=""])'));
 if(prepared.fact.payload.fact_type!=='product_test.artifact'||prepared.fact.payload.prepared.kind!=='test')throw Error('prepared artifact');
 const {kind:_,...data}=prepared.fact.payload.prepared;
 const forged=await owner.transport(`/api/v1/manufacturing/workflow/projects/${project.id}/commands`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':owner.options.csrfToken},body:JSON.stringify({action:'test_run.finish',operation_id:crypto.randomUUID(),expected_version:(await owner.api.project(project.id)).version,run_id:run.object_id,state:'completed',source:{system:'product_test',object_type:'test',external_id:'forged',version:1,mode:'mock',occurred_at:NOW,collected_at:NOW,evidence:'forged mock provenance'},measurements:data.measurements,raw:data.raw,reason:null})});expect(forged.status).toBe(422);
 // The actual controlled selector binds the entire original payload, not editable UUID/hash fields.
 await set('受控原始证据',data.artifact_checksum);
 const [test]=await submit('laboratory','laboratory.product-test',{operation:'product_test.run',...data});
 expect(test.fact.payload.fact_type).toBe('product_test.test');expect(execution.workflow_projected).toBe(true);expect(start.source_accepted).toBe(true);
 await set('系统业务步骤','laboratory.prepare-artifact');await click('办理下一笔');
 const [preparedCalibration]=await submit('laboratory','laboratory.prepare-artifact',{operation:'product_test.prepare_artifact',run_id:run.object_id,template:'calibration-v1'});
 if(preparedCalibration.fact.payload.fact_type!=='product_test.artifact'||preparedCalibration.fact.payload.prepared.kind!=='calibration')throw Error('calibration artifact');
 const {kind:calibrationKind,...calibrationData}=preparedCalibration.fact.payload.prepared;
 const [calibration]=await submit('laboratory','laboratory.calibration',{operation:'product_test.calibrate',...calibrationData});
 await submit('laboratory','laboratory.plc-readback',{operation:'plc.readback',calibration:key(calibration),run_id:run.object_id,unit_id:refs.units[0].unit_id,equipment:'EQ1',source_identity:'Independent-HTTP-readback',source_version:'1',parameters:calibrationData.parameters,observed_at:NOW,evidence:'Independent physical parameter observation'});
 await mount('quality');
 const [manufacturingRelease]=await submit('quality','quality.mes-release',{operation:'mes.release',work_order_id:refs.work_order,units:refs.units,kind:'manufacturing',decision:'approved',test_sources:[key(test)],evidence:'Manufacturing release'});
 await click('办理下一笔');
 const [qualityRelease]=await submit('quality','quality.mes-release',{operation:'mes.release',work_order_id:refs.work_order,units:refs.units,kind:'quality',decision:'approved',test_sources:[key(test)],evidence:'Qualified quality release'});
 await mount('delivery');expect(container.textContent).toContain('SAP 过账回执');
 faultNext='wms.ship';
 const [shipment]=await submit('delivery','delivery.wms-shipment',{operation:'wms.ship',order_line_id:refs.order_line,shipment_id:crypto.randomUUID(),units:refs.units,releases:[key(manufacturingRelease),key(qualityRelease)],amount:amount('1'),destination:'Customer C',evidence:'Actual packed and handed-over units'});
 expect((await owner.api.integrationIntents(project.id,200,0)).records.filter(i=>i.operation==='wms.ship')).toHaveLength(1);
 await set('系统业务步骤','delivery.sap-posting');await until(()=>container.textContent!.includes('SAP 过账：已确认'));await settle();
 const admissionStart=requests.length;last=undefined;await click('执行：准入此来源业务事实');await until(()=>!!last);await settle();expect(latest().integration?.projection_applied).toBe(true);
 const admitted=(await owner.api.integrationIntents(project.id,200,0)).records.find(i=>i.intent_id===latest().integration!.intent_id)!;expect(admitted.operation).toBe('integration.pull');expect(admitted.source_key?.object_type).toBe('shipment_posting');const posting=await owner.api.systemFact(project.id,admitted.source_key!);expect(posting.sap_posted).toBe(true);expect(posting.workflow_projected).toBe(true);
 const postingObservation:JourneyObservation={outcome:'applied',context:'delivery',stepId:'delivery.sap-posting',projectId:project.id,selected:{project_id:project.id,kind:'shipment',id:target(shipment,'shipment')},inputs:posting.fact.caused_by||[],outputs:[admitted.source_key!],targets:posting.projection?.targets||[],operationId:latest().operation_id,intentId:admitted.intent_id,requests:requests.slice(admissionStart),receipts:posting.receipts||[],sourceStates:[sourceState(posting)],blocker:null,nextAction:'delivery.customer-receipt',observedAt:new Date().toISOString()};observations.push(postingObservation);await writeFile(join(output,`${observations.length.toString().padStart(3,'0')}-delivery.sap-posting.json`),JSON.stringify(postingObservation,null,2),{flag:'wx',mode:0o600});
 const claim={units:refs.units,shipment_id:target(shipment,'shipment'),shipment:key(shipment),amount:amount('1'),customer_id:'C',external_signer:'Customer receiving authority',reason:'Physical receipt',signed_evidence:'Signed exact SN list',occurred_at:NOW,decision:'accepted' as const};
 // Select shipment before unit membership, as a business user does.
 await set('系统业务步骤','delivery.customer-receipt');await until(()=>!!container.querySelector('[aria-label="WMS 发货凭据"]'));await settle();await set('WMS 发货凭据',keyText(key(shipment)));
 await submit('delivery','delivery.customer-receipt',{operation:'customer.receive_shipment',...claim});
 await set('系统业务步骤','delivery.customer-acceptance');await until(()=>!!container.querySelector('[aria-label="WMS 发货凭据"]'));await settle();await set('WMS 发货凭据',keyText(key(shipment)));
 await submit('delivery','delivery.customer-acceptance',{operation:'customer.confirm_delivery',...claim});
 const delivered=await owner.api.object(project.id,'shipment',target(shipment,'shipment'));expect(delivered.value.kind).toBe('shipment');if(delivered.value.kind==='shipment'){expect(delivered.value.shipped).toBe('1');expect(delivered.value.signed).toBe('1');expect(delivered.value.accepted).toBe('1');}
 await mount('home');const [snapshot]=await submit('home','home.bi-snapshot',{operation:'bi.refresh'});expect(snapshot.fact.payload.fact_type).toBe('bi.snapshot');await until(()=>container.textContent!.includes('快照截止'));
 await mount('trace');await set('当前业务对象',refs.units[0].unit_id);await until(()=>container.textContent!.includes('当前对象回执与来源'));expect(container.textContent).toContain('当前已读取来源');

},60000);
