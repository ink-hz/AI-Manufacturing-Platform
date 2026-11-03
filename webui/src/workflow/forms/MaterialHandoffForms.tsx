import { useEffect, useRef, useState } from 'react';
import type { Grant, MaterialHandoffCommand, MaterialHandoffValue, ObjectSummary, WorkspaceProps } from '../types';
import { Choice, CommandForm, Field, ObjectChoice } from './shared';
import { label } from '../labels';
type Props=WorkspaceProps & {action:MaterialHandoffCommand['action'];lots:ObjectSummary[];workOrders:ObjectSummary[];members:Grant[];selected?:MaterialHandoffValue|null};
const decimal=(v:string)=>v.replace(/^0+(?=\d)/,'').replace(/(\.\d*?)0+$/,'$1').replace(/\.$/,'');
const quantity=(v:string,positive=false)=>/^\d+(\.\d+)?$/.test(v)&&(!positive||/[1-9]/.test(v));
function BusinessTime({value,onChange}:{value:string|null;onChange(v:string|null):void}){
 const [local,setLocal]=useState(value?value.slice(0,16):'');
 return <Field name="发生时间" required={false} type="datetime-local" value={local} onChange={v=>{setLocal(v);onChange(v?new Date(v).toISOString():null);}}/>;
}
export function MaterialHandoffForms(p:Props){
 const selection=useRef(0),[lookupError,setLookupError]=useState('');
 useEffect(()=>()=>{selection.current++;},[p.project.id]);

 if(p.action==='material_handoff.record')return <CommandForm<Extract<MaterialHandoffCommand,{action:'material_handoff.record'}>> {...p} title="发起物料交接" save="保存交接" initial={()=>({action:'material_handoff.record',material_lot_id:'',work_order_id:null,quantity:'',unit:'',from_location:'',to_location:'',receiver_id:'',occurred_at:null,note:null})} canSubmit={v=>!!v.material_lot_id&&!!v.unit&&quantity(v.quantity,true)&&!!v.from_location.trim()&&!!v.to_location.trim()&&v.from_location.trim()!==v.to_location.trim()&&p.members.some(m=>m.user_id===v.receiver_id)}>{(v,set)=><>
  <ObjectChoice name="物料批次" value={v.material_lot_id} items={p.lots} onChange={id=>{
   const request=++selection.current,unit=p.lots.find(l=>l.id===id)?.unit||'';
   setLookupError('');set({...v,material_lot_id:id,unit});
   if(id&&!unit)void p.api.object(p.project.id,'material_lot',id).then(d=>{
    if(request!==selection.current)return;
    if(d.value.kind!=='material_lot')throw Error('批次类型不匹配');
    const unit=d.value.unit;set(old=>old.material_lot_id===id?{...old,unit}:old);
   }).catch(e=>{if(request===selection.current)setLookupError(String(e));});
  }}/>
  {lookupError&&<p role="alert">{lookupError} · 请重新选择物料批次。</p>}
  <Field name="交接数量" value={v.quantity} onChange={quantity=>set({...v,quantity})}/><p>单位：{v.unit||'选择批次后显示'}</p>
  <Field name="交出位置" value={v.from_location} onChange={from_location=>set({...v,from_location})}/>
  <Field name="送达位置" value={v.to_location} onChange={to_location=>set({...v,to_location})}/>
  <Choice name="接收人" value={v.receiver_id} choices={{'':'请选择',...Object.fromEntries(p.members.map(m=>[m.user_id,m.display_name||m.user_id]))}} onChange={receiver_id=>set({...v,receiver_id})}/>
  <details><summary>补充信息</summary><ObjectChoice name="关联工单" required={false} value={v.work_order_id||''} items={p.workOrders} onChange={id=>set({...v,work_order_id:id||null})}/><BusinessTime value={v.occurred_at} onChange={occurred_at=>set({...v,occurred_at})}/><Field name="备注" required={false} value={v.note||''} onChange={note=>set({...v,note:note||null})}/></details>
 </>}</CommandForm>;
 const h=p.selected;if(!h)return <p>请选择有权办理的交接记录。</p>;
 if(p.action==='material_handoff.receive')return <CommandForm<Extract<MaterialHandoffCommand,{action:'material_handoff.receive'}>> {...p} title="确认接收" save="确认接收" initial={()=>({action:'material_handoff.receive',handoff_id:h.id,received_quantity:h.quantity,received_location:h.to_location,occurred_at:null,note:null})} canSubmit={v=>quantity(v.received_quantity)&&!!v.received_location.trim()&&((decimal(v.received_quantity)===decimal(h.quantity)&&v.received_location.trim()===h.to_location)||!!v.note?.trim())}>{(v,set)=>{const differs=decimal(v.received_quantity)!==decimal(h.quantity)||v.received_location.trim()!==h.to_location;return <>
 <p>{h.handoff_number} · 交出 {h.quantity} {h.unit} · {h.from_location} → {h.to_location}（送达位置待接收确认） · 接收人 {h.receiver_name}</p>
 <Field name="实收数量" value={v.received_quantity} onChange={received_quantity=>set({...v,received_quantity})}/><p>单位：{h.unit}</p><Field name="实际接收位置" value={v.received_location} onChange={received_location=>set({...v,received_location})}/>
 {differs&&<Field name="差异说明" value={v.note||''} onChange={note=>set({...v,note:note||null})}/>}
 <details><summary>补充信息</summary><BusinessTime value={v.occurred_at} onChange={occurred_at=>set({...v,occurred_at})}/>{!differs&&<Field name="备注" required={false} value={v.note||''} onChange={note=>set({...v,note:note||null})}/>}</details>
 </>;}}</CommandForm>;
 if(p.action==='material_handoff.resolve')return <CommandForm<Extract<MaterialHandoffCommand,{action:'material_handoff.resolve'}>> {...p} title={label(p.action)} save="保存差异处理" initial={()=>({action:'material_handoff.resolve',handoff_id:h.id,resolution:''})} canSubmit={v=>!!v.resolution.trim()}>{(v,set)=><><p>{h.handoff_number} · 交出 {h.quantity} {h.unit} · 实收 {h.receipt?.received_quantity} {h.unit} · {h.receipt?.received_location} · {h.receipt?.note}</p><Field name="处理说明" value={v.resolution} onChange={resolution=>set({...v,resolution})}/></>}</CommandForm>;
 return <CommandForm<Extract<MaterialHandoffCommand,{action:'material_handoff.cancel'}>> {...p} title="取消交接" save="确认取消交接" initial={()=>({action:'material_handoff.cancel',handoff_id:h.id,reason:''})} canSubmit={v=>!!v.reason.trim()}>{(v,set)=><><p>{h.handoff_number} · {h.quantity} {h.unit} · {h.from_location} → {h.to_location}</p><Field name="取消原因" value={v.reason} onChange={reason=>set({...v,reason})}/></>}</CommandForm>;
}
