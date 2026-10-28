import { useRef, useState } from "react";
import type { CommandFields, ObjectSummary, WorkspaceProps } from "../types";
import { Choice, CommandForm, Field, ObjectChoice, SourceFields, source } from "./shared";

type Props=WorkspaceProps & {action:CommandFields["action"];workOrders:ObjectSummary[];orders:ObjectSummary[];
  revisions:ObjectSummary[];lots:ObjectSummary[];requirements:ObjectSummary[];
  commitments:ObjectSummary[];receipts:ObjectSummary[]};
type Define=Extract<CommandFields,{action:"material.define"}>;
type Plan=Extract<CommandFields,{action:"plan.receive"}>;
type Commit=Extract<CommandFields,{action:"supply.commit"}>;
type Receive=Extract<CommandFields,{action:"supply.receive"}>;
type Inspect=Extract<CommandFields,{action:"supply.inspect"}>;

export function SupplyForms(p:Props){
  const [selectedLots,setSelectedLots]=useState<Record<number,string>>({});
  const selectedLotIds=useRef<Record<number,string>>({});
  const fill=<T,>(current:T,atLookup:T,fetched:T)=>current===atLookup?fetched:current;
  switch(p.action){
    case "reservation.request": return <CommandForm<Extract<CommandFields,{action:"reservation.request"}>> {...p}
      title="请求权威库存预留" save="保存预留请求" canSubmit={v=>p.project.allowed_actions.includes("reservation.request")&&!!v.work_order_id && !!v.requirement_id && !!v.lot_id}
      initial={()=>({action:"reservation.request",work_order_id:"",requirement_id:"",lot_id:"",quantity:"",unit:""})}>
      {(v,set)=><>
        <p>库存预留由权威系统原子接受。保存请求后，在同步与回执中发送并查询；待确认请求占用请求额度，不能作为开工依据。</p>
        <ObjectChoice name="预留对应需求" items={p.requirements} value={v.requirement_id} onChange={x=>{
          set(old=>({...old,requirement_id:x,work_order_id:"",unit:""}));
          if(x)void p.api.object(p.project.id,"requirement",x).then(d=>{const detail=d.value;
            if(detail.kind==="requirement")set(old=>old.requirement_id===x?{...old,work_order_id:detail.work_order_id,unit:detail.unit}:old);
          });
        }}/>
        <ObjectChoice name="预留物料批次" items={p.lots} value={v.lot_id} onChange={x=>set({...v,lot_id:x})}/>
        <Field name="请求预留数量" value={v.quantity} onChange={x=>set({...v,quantity:x})}/>
        <p>物料计量单位：{v.unit||"先选择需求"}</p>
      </>}
    </CommandForm>;
    case "material.define": return <CommandForm<Define> {...p} title="定义物料批次" save="保存物料批次"
      initial={()=>({action:"material.define",material_id:"",lot_id:"",owner_id:p.project.customer_id,unit:"kg",scale:3,expiry:"",source:source("material_lot")})}>
      {(v,set)=><>
        <Field name="物料业务编号" value={v.material_id} onChange={x=>set({...v,material_id:x})}/>
        <Field name="批次业务编号" value={v.lot_id} onChange={x=>set({...v,lot_id:x})}/>
        <Field name="物料所有者" value={v.owner_id} onChange={x=>set({...v,owner_id:x})}/>
        <Field name="物料单位" value={v.unit} onChange={x=>set({...v,unit:x})}/>
        <Field name="物料计量精度" type="number" value={String(v.scale)} onChange={x=>set({...v,scale:Number(x)})}/>
        <Field name="批次有效期" type="date" value={v.expiry} onChange={x=>set({...v,expiry:x})}/>
        <SourceFields value={v.source} onChange={x=>set({...v,source:x})}/>
      </>}
    </CommandForm>;
    case "plan.receive": return <CommandForm<Plan> {...p} title="接收供应计划" save="保存计划"
      initial={()=>({action:"plan.receive",source:source("plan"),input_revision_ids:[],input_order_versions:[],
        requirements:[{work_order_id:"",execution_scope:"trial",material_id:"",owner_id:p.project.customer_id,quantity:"",unit:"kg"}]})}
      canSubmit={v=>!!v.source.cutoff && v.input_revision_ids.length>0 && v.input_order_versions.length>0}>
      {(v,set)=><>
        <p>计划逐行指定工单、试做／批量／通用范围和物料数量；使用固定工程版本及当前订单来源版本。</p>
        {v.requirements.map((r,i)=><fieldset key={i}>
          <legend>物料需求 {i+1}</legend>
          <ObjectChoice name={`计划依据工单 ${i+1}`} items={p.workOrders} value={r.work_order_id}
            onChange={x=>{
              set(old=>({...old,requirements:old.requirements.map((e,n)=>n===i?{...e,work_order_id:x}:e)}));
              if(x)void p.api.object(p.project.id,"work_order",x).then(d=>{
                if(d.value.kind!=="work_order")return;
                const wo=d.value;
                const order=p.orders.find(o=>o.id===wo.order_line_id);
                const apply=(version:number)=>set(old=>old.requirements[i]?.work_order_id!==x?old:({
                  ...old,input_revision_ids:[...new Set([...old.input_revision_ids,wo.revision_id])],
                  input_order_versions:[...old.input_order_versions.filter(o=>o.order_line_id!==wo.order_line_id),
                    {order_line_id:wo.order_line_id,version}],
                }));
                if(order)apply(order.version);
                else void p.api.object(p.project.id,"order_line",wo.order_line_id).then(o=>apply(o.summary.version));
              });
            }}/>
          <ObjectChoice name={`计划物料批次 ${i+1}`} items={p.lots}
            value={selectedLots[i]||""}
            onChange={x=>{selectedLotIds.current[i]=x;setSelectedLots(old=>({...old,[i]:x}));if(!x)return;void p.api.object(p.project.id,"material_lot",x).then(d=>{
              const lot=d.value;
              if(lot.kind==="material_lot" && selectedLotIds.current[i]===x)set(old=>({...old,requirements:old.requirements.map((e,n)=>n===i?{
                ...e,material_id:lot.material_id,owner_id:lot.owner_id,unit:lot.unit}:e)}));
            });}}/>
          <Choice name={`执行范围 ${i+1}`} value={r.execution_scope}
            choices={{trial:"首件试做",bulk:"批量执行",common:"试做与批量通用"}}
            onChange={x=>set(old=>({...old,requirements:old.requirements.map((e,n)=>n===i?{
              ...e,execution_scope:x as "trial"|"bulk"|"common"}:e)}))}/>
          <Field name={`计划物料数量 ${i+1}`} value={r.quantity}
            onChange={x=>set(old=>({...old,requirements:old.requirements.map((e,n)=>n===i?{...e,quantity:x}:e)}))}/>
          <p>物料 {r.material_id||"待选"} · 所有者 {r.owner_id} · 单位 {r.unit}</p>
          <button type="button" disabled={v.requirements.length===1} onClick={()=>{
            selectedLotIds.current=Object.fromEntries(Object.entries(selectedLotIds.current).filter(([n])=>Number(n)!==i)
              .map(([n,x])=>[Number(n)>i?Number(n)-1:Number(n),x]));
            setSelectedLots(old=>Object.fromEntries(Object.entries(old).filter(([n])=>Number(n)!==i)
              .map(([n,x])=>[Number(n)>i?Number(n)-1:Number(n),x])));
            set(old=>({...old,requirements:old.requirements.filter((_,n)=>n!==i)}));
          }}>移除物料需求 {i+1}</button>
        </fieldset>)}
        <button type="button" onClick={()=>set(old=>({...old,requirements:[...old.requirements,
          {work_order_id:"",execution_scope:"trial",material_id:"",owner_id:p.project.customer_id,quantity:"",unit:"kg"}]}))}>添加物料需求</button>
        <Field name="计划来源截止时间" type="datetime-local" value={v.source.cutoff||""}
          onChange={x=>set({...v,source:{...v.source,cutoff:x}})}/>
        <SourceFields value={v.source} onChange={x=>set({...v,source:x})}/>
      </>}
    </CommandForm>;
    case "supply.commit": return <CommandForm<Commit> {...p} title="登记供应承诺" save="保存供应承诺"
      initial={()=>({action:"supply.commit",commitment_id:null,requirement_id:"",type:"purchase",owner_id:p.project.customer_id,
        quantity:"",unit:"kg",original_due:"",current_due:"",source:source("commitment")})}>
      {(v,set)=><>
        <ObjectChoice name="承诺对应需求" items={p.requirements} value={v.requirement_id}
          onChange={x=>{set(old=>({...old,requirement_id:x}));if(x)void p.api.object(p.project.id,"requirement",x).then(d=>{
            const detail=d.value;
            if(detail.kind==="requirement")set(old=>old.requirement_id!==x?old:{...old,
              owner_id:fill(old.owner_id,v.owner_id,detail.owner_id),unit:fill(old.unit,v.unit,detail.unit)});
          });}}/>
        <ObjectChoice name="修订既有承诺" items={p.commitments} value={v.commitment_id||""} required={false}
          onChange={x=>{set(old=>({...old,commitment_id:x||null}));if(x)void p.api.object(p.project.id,"commitment",x).then(d=>{
            const detail=d.value;
            if(detail.kind==="commitment")set(old=>old.commitment_id!==x?old:{...old,
              requirement_id:fill(old.requirement_id,v.requirement_id,detail.requirement_id),
              type:fill(old.type,v.type,detail.type),owner_id:fill(old.owner_id,v.owner_id,detail.owner_id),
              quantity:fill(old.quantity,v.quantity,detail.current_quantity),
              unit:fill(old.unit,v.unit,detail.unit),
              original_due:fill(old.original_due,v.original_due,detail.original_due),
              current_due:fill(old.current_due,v.current_due,detail.current_due),
              source:{...old.source,system:fill(old.source.system,v.source.system,detail.source.system),
                external_id:fill(old.source.external_id,v.source.external_id,detail.source.external_id),
                version:fill(old.source.version,v.source.version,detail.source.version+1)}});
          });}}/>
        <Choice name="供应类型" value={v.type} choices={{purchase:"采购",customer:"客户供料"}}
          onChange={x=>set({...v,type:x as "purchase"|"customer"})}/>
        <Field name="供应所有者" value={v.owner_id} onChange={x=>set({...v,owner_id:x})}/>
        <Field name="供应承诺数量" value={v.quantity} onChange={x=>set({...v,quantity:x})}/>
        <Field name="物料单位" value={v.unit} onChange={x=>set({...v,unit:x})}/>
        <Field name="原始承诺交期" type="date" value={v.original_due} onChange={x=>set({...v,original_due:x})}/>
        <Field name="当前承诺交期" type="date" value={v.current_due} onChange={x=>set({...v,current_due:x})}/>
        <SourceFields value={v.source} onChange={x=>set({...v,source:x})}/>
      </>}
    </CommandForm>;
    case "supply.receive": return <CommandForm<Receive> {...p} title="登记到货" save="保存到货证据"
      initial={()=>({action:"supply.receive",commitment_id:"",material_lot_id:"",quantity:"",unit:"kg",source:source("receipt")})}>
      {(v,set)=><>
        <p>人工登记到货不改变权威库存；来料检验另行登记。</p>
        <ObjectChoice name="到货对应承诺" items={p.commitments} value={v.commitment_id} onChange={x=>set({...v,commitment_id:x})}/>
        <ObjectChoice name="到货物料批次" items={p.lots} value={v.material_lot_id}
          onChange={x=>{set(old=>({...old,material_lot_id:x}));if(x)void p.api.object(p.project.id,"material_lot",x).then(d=>{
            const detail=d.value;
            if(detail.kind==="material_lot")set(old=>old.material_lot_id!==x?old:{...old,
              unit:fill(old.unit,v.unit,detail.unit)});
          });}}/>
        <Field name="本次到货数量" value={v.quantity} onChange={x=>set({...v,quantity:x})}/>
        <p>计量单位：{v.unit}</p>
        <SourceFields value={v.source} onChange={x=>set({...v,source:x})}/>
      </>}
    </CommandForm>;
    case "supply.inspect": return <CommandForm<Inspect> {...p} title="登记来料检验" save="保存检验结果"
      initial={()=>({action:"supply.inspect",receipt_id:"",accepted:"",rejected:"",evidence:""})}>
      {(v,set)=><>
        <p>每次检验追加不可变数量事实。已接收、合格和拒收分别计算；检验结果不会确认库存预留。</p>
        <ObjectChoice name="检验到货记录" items={p.receipts} value={v.receipt_id} onChange={x=>set({...v,receipt_id:x})}/>
        <Field name="本次合格数量" value={v.accepted} onChange={x=>set({...v,accepted:x})}/>
        <Field name="本次拒收数量" value={v.rejected} onChange={x=>set({...v,rejected:x})}/>
        <Field name="检验凭据" value={v.evidence} onChange={x=>set({...v,evidence:x})}/>
      </>}
    </CommandForm>;
    default:return null;
  }
}
