import { useEffect, useRef, useState } from "react";
import type { CommandFields, ExchangeValue, InboundKind, ObjectSummary, WorkspaceProps } from "./types";
import { Choice, CommandForm, Field, ObjectChoice } from "./forms/shared";
import { ObjectTable } from "./OrdersWorkspace";
import { label } from "./labels";

type Props=WorkspaceProps & {requestLeave(action:()=>void):void;mode:"production"|"demo"|"test"};
const policies:Record<InboundKind,CommandFields["action"]>={receipt:"supply.receive",iqc:"supply.inspect",customer_approval:"engineering.customer_approval"};
export function ExchangeWorkspace(p:Props){
  const [items,setItems]=useState<ObjectSummary[]>([]),[total,setTotal]=useState(0),[error,setError]=useState("");
  const [form,setForm]=useState<"pull"|"file"|"dispatch"|"query"|"reconcile"|null>(null),[epoch,setEpoch]=useState(0);
  const activeSelection=useRef("");
  const fileGeneration=useRef(0);
  const alive=useRef(true);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;activeSelection.current="";fileGeneration.current++;};},[]);
  const [selected,setSelected]=useState<ExchangeValue|null>(null);
  const [selectedActions,setSelectedActions]=useState<string[]>([]);
  useEffect(()=>{let active=true;p.api.objects(p.project.id,"exchange",50,0).then(page=>{if(active){setItems(page.items);setTotal(page.total);}}).catch(e=>{if(active)setError(String(e));});return()=>{active=false;};},[p.api,p.project.id,p.project.version]);
  const kinds=(Object.keys(policies) as InboundKind[]).filter(k=>p.project.allowed_actions.includes(policies[k]));
  const edit=!p.readOnly;
  const switchForm=(value:typeof form)=>p.requestLeave(()=>{setForm(value);setSelected(null);setSelectedActions([]);activeSelection.current="";fileGeneration.current++;setEpoch(x=>x+1);});
  const changed:WorkspaceProps["onChanged"]=r=>{setForm(null);setSelected(null);p.onChanged(r);};
  const shared={...p,onChanged:changed};
  const canExchange=selected && selectedActions.includes(form==="dispatch"?"exchange.dispatch":form==="query"?"exchange.query":"exchange.reconcile");
  return <section>
    <h3>同步与回执</h3>
    <p role="status">{p.mode==="production"?"权威系统未接入 · 当前来源不可用":"模拟权威系统 · 独立库存与回执数据库"}</p>
    <p>库存预留由权威系统原子接受。未知结果先查询；重发仍使用原业务键。收到、校验、批准、接受与过账分别记录。</p>
    {error&&<p role="alert">{error}</p>}
    {edit&&<div className="mf-actions">
      {kinds.length>0&&<><button onClick={()=>switchForm("pull")}>获取来源事实</button><button onClick={()=>switchForm("file")}>导入来源文件</button></>}
      {p.project.allowed_actions.includes("exchange.dispatch")&&<button onClick={()=>switchForm("dispatch")}>发送权威请求</button>}
      {p.project.allowed_actions.includes("exchange.query")&&<button onClick={()=>switchForm("query")}>查询已有回执</button>}
      {p.project.allowed_actions.includes("exchange.reconcile")&&<button onClick={()=>switchForm("reconcile")}>对账与纠正</button>}
    </div>}
    {form&&<button onClick={()=>switchForm(null)}>放弃草稿并重新读取</button>}
    {form==="pull"&&<CommandForm<Extract<CommandFields,{action:"source.pull"}>> key={epoch} {...shared} title="获取来源事实" save="读取权威来源"
      initial={()=>({action:"source.pull",system:"erp",object_type:kinds[0],external_id:""})} canSubmit={v=>p.project.allowed_actions.includes(policies[v.object_type])}>
      {(v,set)=><><Choice name="来源事实类型" value={v.object_type} choices={Object.fromEntries(kinds.map(k=>[k,label(k)]))} onChange={x=>set({...v,object_type:x as InboundKind})}/>
        <Field name="来源系统" value={v.system} onChange={x=>set({...v,system:x})}/><Field name="外部业务编号" value={v.external_id} onChange={x=>set({...v,external_id:x})}/>
        <p>只从服务器配置的权威系统获取，不在此录入批准结果。外部签署人与本地记录人分别保留。</p></>}
    </CommandForm>}
    {form==="file"&&<CommandForm<Extract<CommandFields,{action:"source.import_file"}>> key={epoch} {...shared} title="导入来源文件" save="验证并导入文件"
      initial={()=>({action:"source.import_file",object_type:kinds[0],format:"json",content_base64:""})} canSubmit={v=>!!v.content_base64&&p.project.allowed_actions.includes(policies[v.object_type])}>
      {(v,set)=><><Choice name="文件事实类型" value={v.object_type} choices={Object.fromEntries(kinds.map(k=>[k,label(k)]))} onChange={x=>set({...v,object_type:x as InboundKind})}/>
        <Choice name="文件格式" value={v.format} choices={{json:"JSON",csv:"CSV"}} onChange={x=>set({...v,format:x as "json"|"csv"})}/>
        <label>选择来源文件<input aria-label="选择来源文件" type="file" accept=".json,.csv" onChange={e=>{
          const file=e.target.files?.[0];const generation=++fileGeneration.current;set({...v,content_base64:""});
          if(!file)return;if(file.size>1024*1024){setError("文件不得超过 1 MB");return;}
          const reader=new FileReader();reader.onload=()=>{if(!alive.current||generation!==fileGeneration.current)return;setError("");set(old=>({...old,content_base64:String(reader.result).split(",")[1]||""}));};
          reader.onerror=()=>{if(alive.current&&generation===fileGeneration.current)setError("文件读取失败");};reader.readAsDataURL(file);
        }}/></label><p>最多 1 MB、500 行。整批校验后登记，文件来源不能伪装为权威接受。每行必须使用当前项目与已登记业务对象。</p></>}
    </CommandForm>}
    {(form==="dispatch"||form==="query")&&<CommandForm<Extract<CommandFields,{action:"exchange.dispatch"|"exchange.query"}>> key={epoch} {...shared}
      title={form==="dispatch"?"发送权威请求":"查询已有回执"} save={form==="dispatch"?"查询后发送原请求":"查询权威结果"}
      initial={()=>({action:form==="dispatch"?"exchange.dispatch":"exchange.query",exchange_id:""})} canSubmit={v=>!!v.exchange_id && !!canExchange}>
      {(v,set)=><><ObjectChoice name="待处理交换" items={items} value={v.exchange_id} onChange={x=>{
        set({...v,exchange_id:x});setSelected(null);setSelectedActions([]);activeSelection.current=x;if(x)void p.api.object(p.project.id,"exchange",x).then(d=>{if(alive.current&&activeSelection.current===x&&d.value.kind==="exchange"){setSelected(d.value);setSelectedActions(d.summary.next_actions);}}).catch(e=>{if(alive.current&&activeSelection.current===x)setError(String(e));});
      }}/>{selected&&<p>{label(selected.phase)} · 请求 {selected.requested} {selected.unit} · 已接受 {selected.accepted} · {selected.reason}</p>}
      {selected&&!canExchange&&<p role="alert">当前状态或账号不能执行该动作，请查看业务阻断与来源回执。</p>}</>}
    </CommandForm>}
    {form==="reconcile"&&<CommandForm<Extract<CommandFields,{action:"exchange.reconcile"}>> key={epoch} {...shared} title="对账与纠正" save="追加对账事实"
      initial={()=>({action:"exchange.reconcile",exchange_id:"",object_type:"reservation",source_version:1,source:{system:"erp",object_type:"reservation",external_id:"",version:1,mode:"manual",occurred_at:"",collected_at:"",cutoff:null,evidence:"对账"},details:[],resolution:"compare",evidence:""})}
      canSubmit={v=>!!v.exchange_id&&!!canExchange}>
      {(v,set)=><><ObjectChoice name="对账交换记录" items={items} value={v.exchange_id} onChange={x=>{
        set({...v,exchange_id:x});setSelected(null);setSelectedActions([]);activeSelection.current=x;if(x)void p.api.object(p.project.id,"exchange",x).then(d=>{if(!alive.current||activeSelection.current!==x||d.value.kind!=="exchange")return;const value=d.value;setSelected(value);setSelectedActions(d.summary.next_actions);
          set(old=>old.exchange_id!==x?old:{...old,details:(value.receipt?.details||[]).filter((d):d is import("./types").ReceiptDetail=>"lot_id" in d),source_version:value.source?.version||value.receipt?.source_version||1,
            object_type:value.source_object_type||"reservation",resolution:value.source?"accept_authority":"compare",
            source:value.source?{...value.source,mode:"manual"}:{...old.source,external_id:value.business_key}});
        }).catch(e=>{if(alive.current&&activeSelection.current===x)setError(String(e));});
      }}/>{selected?.source&&<p>确认已保留的权威事实，追加数量纠正事件；原人工登记与来源保持可查。</p>}
      {v.details.map((d,i)=><fieldset key={d.key}><legend>权威明细 {i+1} · {d.owner_id}</legend>
        <Field name={`核对数量 ${i+1}`} value={d.quantity} onChange={x=>set({...v,details:v.details.map((item,n)=>n===i?{...item,quantity:x}:item)})}/><p>{d.unit}</p></fieldset>)}
      <Field name="对账凭据" value={v.evidence} onChange={x=>set({...v,evidence:x})}/></>}
    </CommandForm>}
    <ObjectTable items={items} onOpen={p.onOpen}/>
    {items.length<total&&<button onClick={()=>void p.api.objects(p.project.id,"exchange",50,items.length).then(page=>{if(alive.current){setItems(old=>[...old,...page.items]);setTotal(page.total);}}).catch(e=>setError(String(e)))}>读取更多交换（{items.length} / {total}）</button>}
  </section>;
}
