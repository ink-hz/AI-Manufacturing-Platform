import { useEffect, useState } from "react";
import type { WorkflowApi } from "./api";
import type {
  ObjectDetail,
  WorkflowTarget,
  Readiness,
  SourceRef,
} from "./types";
import { label, objectTitle } from "./forms/shared";
function Facts({ items }: { items: [string, string | number][] }) {
  return (
    <dl className="wf-facts">
      {items.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}
export function Source({ value: v }: { value: SourceRef }) {
  return (
    <section>
      <h4>来源依据</h4>
      <Facts
        items={[
          ["来源系统", v.system],
          ["业务编号", v.external_id],
          ["来源版本", v.version],
          [
            "登记方式",
            {
              manual: "人工登记",
              file: "文件导入",
              mock: "模拟系统",
              api: "接口采集",
            }[v.mode],
          ],
          ["发生时间", v.occurred_at],
          ["采集时间", v.collected_at],
          ["来源截止", v.cutoff || "未提供"],
          ["凭据", v.evidence],
        ]}
      />
    </section>
  );
}
function ReadinessView({ title, value }: { title: string; value: Readiness }) {
  return (
    <section>
      <h4>
        {title} · {value.ready ? "就绪" : "阻断"}
      </h4>
      <table>
        <thead>
          <tr>
            <th>检查项</th>
            <th>状态</th>
            <th>依据与阻断原因</th>
          </tr>
        </thead>
        <tbody>
          {value.checks.map((c) => (
            <tr key={c.kind}>
              <td>{label(c.kind)}</td>
              <td>{label(c.status)}</td>
              <td>{label(c.reason)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Facts items={Object.entries(value.input_versions).filter(([key])=>key!=="plan_id").map(([key,version])=>[
        ({project:"项目版本",revision:"固定修订",work_order:"工单来源版本",plan:"计划来源版本",
          plan_source:"计划业务编号",plan_cutoff:"计划来源截止"} as Record<string,string>)[key]||key,
        version || "未提供",
      ])}/>
      <p>
        库存预留由权威系统原子接受。开工分为首件试做与批量执行；量产首件需实际检验。
      </p>
    </section>
  );
}
export function DetailContent({
  data,
  onOpen,
}: {
  data: ObjectDetail;
  onOpen(t: WorkflowTarget): void;
}) {
  const v = data.value;
  return (
    <article className="wf-detail">
      <h3>{objectTitle(data.summary)}</h3>
      <p>
        状态：{label(data.summary.state)} · 记录版本 {data.summary.version}
      </p>
      {(v.kind === "unit" || v.kind === "material_lot") && <Facts items={[["申请冻结状态",v.freeze_requested||"无申请"],["权威确认状态",v.freeze_confirmed||"尚未确认"],["回执状态",v.freeze_pending?"等待权威确认":"无待确认申请"]]}/>}
      {v.kind === "rma" && <><Facts items={[["原始客户",v.customer_id],["客户问题事实",v.reason],["状态",v.state]]}/>{v.source&&<Source value={v.source}/>}<p>原始检验记录{v.tests_truncated?"（已截断）":""}</p>{v.test_ids.map((id,i)=><button key={id} onClick={()=>onOpen({projectId:data.summary.project_id,kind:"test",id})}>查看原始检验 {i+1}</button>)}<p>RMA 登记不代表实物已经退回。</p></>}
      {v.kind === "capa" && <><p>人工调查与实施证据 · {v.state}</p>{v.steps_truncated&&<p>仅显示最近 100 条证据。</p>}{v.steps.map(s=><section key={s.sequence}><h4>{({containment:"遏制",root_cause:"根因分析",correction:"纠正措施",verification:"有效性验证"})[s.step]}</h4><p>{s.description}</p><p>{s.evidence}</p>{s.implementation_evidence&&<p>实际实施：{s.implementation_evidence}</p>}{s.effective!==null&&<p>{s.effective?"验证通过":"验证失败，保持开放"}</p>}{s.eco_id&&<button onClick={()=>onOpen({projectId:data.summary.project_id,kind:"eco",id:s.eco_id!})}>查看实际工程实施</button>}</section>)}{v.blocking_reasons.map(r=><p key={r}>{r}</p>)}</>}
      {v.kind === "eco" && <>
        <Facts items={[["旧固定版本",v.old_revision],["新固定版本",v.new_revision||"仅取消剩余范围"],["变更原因",v.reason]]}/>
        {!!v.unresolved_stock_basis_ids?.length&&<p role="alert">库存来源覆盖尚未核清，关闭受阻。工程负责人需在交付工作区请求原始权威来源证明；缺少历史证明时保持阻断。</p>}
        <p>实施结果：{({pending:"尚未实施",retained:"保留旧版，未执行工程切换",cancelled:"实际取消剩余范围",switched:"已执行新版切换",mixed:"多种边界结果"} as Record<string,string>)[v.implementation_outcome||"pending"]}</p>
        {(v.retentions||[]).map(r=><p key={r.work_order_id}>保留旧版 {r.quantity} · 已接受序列号 {r.unit_ids.length} · {r.evidence}</p>)}
        <h4>旧版本受影响记录与处置</h4><table><thead><tr><th>类别 / 对象</th><th>所有者</th><th>数量</th><th>已处置</th><th>凭据</th></tr></thead><tbody>{v.impacts.map(i=><tr key={i.id}><td>{label(i.type)} · {i.title} · {label(i.state)}</td><td>{i.owner_id}</td><td>{i.quantity} {i.unit}</td><td>{i.resolved_quantity}</td><td>{i.dispositions.map(d=>`${label(d.decision)} ${d.quantity} · ${d.evidence}`).join("；")||"待处置"}</td></tr>)}</tbody></table>
        <h4>取消与创建边界</h4>{v.switches.map(s=><section key={s.id}><p>{s.boundary==="split_remaining"?"拆分新版工单":"仅取消剩余"} · 保留旧范围 {s.retained_quantity} · 未执行范围 {s.quantity} · {s.phase==="accepted"?"权威已接受":"等待权威接受"}（{label(s.phase)}）</p><button onClick={()=>onOpen({projectId:data.summary.project_id,kind:"exchange",id:s.exchange_id})}>查看取消与创建回执</button>{s.phase==="accepted"&&s.new_work_order_id&&<button onClick={()=>onOpen({projectId:data.summary.project_id,kind:"work_order",id:s.new_work_order_id!})}>核验新版工单准备</button>}</section>)}
      </>}
      {v.kind === "demand" && (
        <>
          <Facts
            items={[
              ["需求类别", label(v.demand_kind)],
              ["产品", v.product],
              ["数量", v.quantity + " " + v.unit],
              ["交期", v.due_date],
            ]}
          />
          <h4>五项评审</h4>
          <Facts
            items={[
              "technical",
              "material",
              "capacity",
              "commercial",
              "quality",
            ].map((k) => [label(k), label(v.reviews[k] || "unknown")])}
          />
        </>
      )}
      {v.kind === "order_line" && (
        <Facts
          items={[
            ["原始承诺数量", v.original_quantity + " " + v.unit],
            ["当前承诺数量", v.current_quantity + " " + v.unit],
            ["原始交期", v.original_due],
            ["当前交期", v.current_due],
            ["已分配", v.allocated],
            ["已产良品", v.produced_good],
            ["已发运", v.shipped],
            ["已签收", v.signed],
            ["已验收", v.accepted],
            ["待发运", v.remaining_to_ship],
            ["待验收", v.remaining_to_accept],
          ]}
        />
      )}
      {v.kind === "commitment_change" && (
        <>
          <Facts
            items={[
              ["原承诺数量", v.old_quantity + " " + v.unit],
              ["新承诺数量", v.new_quantity + " " + v.unit],
              ["原交期", v.old_due],
              ["新交期", v.new_due],
              ["原因", v.reason],
            ]}
          />
          <h4>影响清单</h4>
          <table>
            <thead>
              <tr>
                <th>对象</th>
                <th>数量</th>
                <th>处置</th>
                <th>凭据</th>
              </tr>
            </thead>
            <tbody>
              {v.impacts.map((i, n) => (
                <tr key={i.object_id}>
                  <td>
                    {label(i.object_type)} {n + 1}
                  </td>
                  <td>
                    {i.quantity} {i.unit}
                  </td>
                  <td>{label(i.decision || "pending")}</td>
                  <td>{i.evidence || "待提供"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {v.kind === "revision" && (
        <>
          <Facts
            items={[
              ["固定修订", v.revision],
              ["客户版本", v.customer_revision],
              ["内部版本", v.internal_revision],
              ["固件版本", v.firmware_version],
              ["测试规范", v.test_spec.version],
              ["测试程序", v.test_spec.program_version],
            ]}
          />
          <h4>固定资料</h4>
          <table>
            <thead>
              <tr>
                <th>名称</th>
                <th>版本</th>
                <th>来源</th>
                <th>核对</th>
                <th>凭据</th>
              </tr>
            </thead>
            <tbody>
              {v.items.map((i) => (
                <tr key={i.id}>
                  <td>{i.title}</td>
                  <td>{i.revision}</td>
                  <td>
                    {i.source_name} · {i.source_ref}
                  </td>
                  <td>{label(i.status)}</td>
                  <td>
                    {i.evidence} {i.reason}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <h4>工艺路线</h4>
          <ol>
            {v.route_steps.map((s) => (
              <li key={s.station}>
                {s.station} · 作业指导 {s.instruction_version}
              </li>
            ))}
          </ol>
          <h4>测量范围</h4>
          <ul>
            {v.test_spec.measurements.map((m) => (
              <li key={m.name}>
                {m.name}：{m.lower} — {m.upper} {m.unit}
              </li>
            ))}
          </ul>
          <h4>交接结果</h4>
          {v.handoffs.length ? (
            v.handoffs.map((h) => (
              <p key={h.id}>
                {h.to_system} · 收到 {h.received_revision} ·{" "}
                <strong>{label(h.status)}</strong> · {h.evidence}
              </p>
            ))
          ) : (
            <p>尚无版本接收记录</p>
          )}
          <h4>客户批准与来源</h4>
          {v.customer_approvals.map((a) => (
            <p key={a.id}>
              {label(a.method)} · {a.customer_id} · {a.external_signatory} · {label(a.decision)} ·{" "}
              {a.evidence}{a.source&&<> · 权威确认：{label(a.source.mode)} · {a.source.external_id} · 版本 {a.source.version}</>}
            </p>
          ))}
        </>
      )}
      {v.kind === "work_order" && (
        <>
          <Facts
            items={[
              ["原始登记数量", v.quantity + " " + v.unit],
              ["当前剩余义务", (v.remaining_obligation ?? v.quantity) + " " + v.unit],
              ["用途", label(v.purpose)],
              ["试产数量", v.trial_quantity + " " + v.unit],
              ["计划开始", v.planned_start],
              ["计划结束", v.planned_end],
            ]}
          />
          <ReadinessView title="试产准备" value={v.trial_readiness} />
          <ReadinessView title="量产准备" value={v.bulk_readiness} />
          {(v.held_start_scopes||[]).length>0&&<section role="alert"><h4>MES 已接受，本地安全暂缓</h4><p>原开工范围仍占序列号与工单预算。请求 MES 停机，修复准备并接收新计划后恢复同一范围。</p>{(v.held_start_scopes||[]).map(s=><p key={s.id}>{s.mode==="trial"?"试产":"批量"} · {s.sns.join("、")} · <button onClick={()=>onOpen({projectId:data.summary.project_id,kind:"exchange",id:s.exchange_id})}>查看 MES 开工回执</button></p>)}</section>}
          <h4>工位来源事件（最近 100 条，共 {v.execution_event_total||0} 条）</h4><ol>{(v.execution_events||[]).map(e=><li key={e.id}>{e.claimed_sn} · {e.station} / {e.route_version} · {label(e.status)} · {e.reason||e.result} · {e.source?`${e.source.system} / ${e.source.external_id}`:"来源未通过准入，已保留拒绝记录"}</li>)}</ol>
        </>
      )}
      {v.kind === "plan" && <>
        <Facts items={[["计划状态",label(v.state)],["来源截止",v.cutoff||"未提供"],["拒绝原因",v.reason||"无"],
          ["计划固定修订数",v.input_revision_ids.length],["计划订单版本数",v.input_order_versions.length],
          ["已确认需求数",v.requirement_ids.length]]}/>
        {v.state==="rejected"&&<p>此计划未确认，不可作为开工物料依据。请提交新的来源版本。</p>}
      </>}
      {v.kind === "requirement" && <>
        <Facts items={[["物料业务编号",v.material_id],["物料所有者",v.owner_id],["执行范围",label(v.execution_scope)],
          ["计划需求",v.quantity+" "+v.unit],["来源截止",v.balance.cutoff||"未提供"],["来源版本",v.balance.source_version]]}/>
        <table><thead><tr><th>需求</th><th>在途</th><th>已接收</th><th>已检合格</th><th>拒收</th><th>确认预留</th><th>缺口</th><th>单位</th></tr></thead>
        <tbody><tr><td>{v.balance.required}</td><td>{v.balance.in_transit}</td><td>{v.balance.received}</td><td>{v.balance.qualified}</td><td>{v.balance.rejected}</td><td>{v.balance.reserved}</td><td>{v.balance.shortage}</td><td>{v.balance.unit}</td></tr></tbody></table>
        {v.balance.blocking_reasons?.map(reason=><p role="alert" key={reason}>{reason}</p>)}
        <p>库存预留由权威系统原子接受。当前人工到货及检验数量不会增加确认预留。</p>
      </>}
      {v.kind === "commitment" && <>
        <Facts items={[["供应类型",label(v.type)],["所有者",v.owner_id],["原始承诺数量",v.original_quantity+" "+v.unit],
          ["当前承诺数量",v.current_quantity+" "+v.unit],["原始承诺交期",v.original_due],["当前承诺交期",v.current_due],
          ["累计到货",v.received],["检验合格",v.qualified],["拒收",v.rejected]]}/>
        <h4>承诺版本</h4><ol>{v.promise_revisions.map((r,i)=><li key={i}>{r.current_due} · {r.quantity} {v.unit} · {r.source.external_id} · 版本 {r.source.version}</li>)}</ol>
      </>}
      {v.kind === "material_lot" && <Facts items={[["物料业务编号",v.material_id],["批次业务编号",v.lot_id],
        ["所有者",v.owner_id],["单位",v.unit],["计量精度",v.scale],["有效期",v.expiry],["状态",label(v.state)],
        ["累计到货",v.received],["检验合格",v.qualified],["拒收",v.rejected]]}/>}
      {v.kind === "receipt" && <Facts items={[["原始登记数量",(v.original_quantity||v.quantity)+" "+v.unit],["当前到货事实",v.quantity+" "+v.unit],["检验合格",v.accepted],
        ["拒收",v.rejected],["待检",v.uninspected]]}/>}
      {v.kind === "reservation" && <Facts items={[["请求预留",v.requested+" "+v.unit],["确认预留",v.confirmed],["尚未接受",v.remaining],["权威对象版本",v.source_version]]}/>}
      {v.kind === "unit" && <Facts items={[["序列号",v.sn],["状态",v.state==="start_pending"&&v.authority_start_accepted?"MES 已接受，本地安全暂缓":label(v.state)],["执行范围",v.mode?label(v.mode):"未开工"],["MES 开工确认",v.authority_start_accepted?"已确认":"尚未确认"],["来源事件数",v.execution_event_ids.length]]}/>}
      {v.kind === "unit" && <><h4>工位来源事件（最近 100 条，共 {v.execution_event_total} 条）</h4><ol>{v.execution_events.map(e=><li key={e.id}>{e.occurred_at} · {e.station} / {e.route_version} · {label(e.status)} · {e.reason||e.result} · {e.source?`${e.source.system} / ${e.source.external_id}`:"来源未通过准入，已保留拒绝记录"}{e.supersedes_event_id&&" · 新事件纠正旧记录"}{e.material_uses.map((u,i)=><p key={i}>用料：{u.material_id} · 所有者 {u.owner_id} · {u.quantity} {u.unit}</p>)}</li>)}</ol></>}
      {v.kind === "test" && <><p>历史测量判定：{v.outcome} · 当前资格：{v.current_qualified===true?"满足":v.current_qualified===false?"不满足":"尚未核验"}</p>{v.current_blocking_reasons?.map(reason=><p key={reason}>{reason}</p>)}<Facts items={[["次数",v.attempt],["判定",label(v.outcome)],["规范",v.scope.test_version],["程序",v.scope.program_version],["固件",v.scope.firmware_version],["校准依据",v.scope.equipment_check_id],["发生时间",v.occurred_at]]}/><table><thead><tr><th>测量</th><th>单位</th><th>下限</th><th>上限</th><th>实测</th></tr></thead><tbody>{v.measurements.map(m=><tr key={m.name}><td>{m.name}</td><td>{m.unit}</td><td>{m.lower}</td><td>{m.upper}</td><td>{m.value}</td></tr>)}</tbody></table>{v.source?<Source value={v.source}/>:<p>来源未通过准入，测量历史保留</p>}</>}
      {v.kind === "nonconformance" && <Facts items={[["缺陷",v.defect],["依据",v.evidence],["状态",label(v.state)],["处置",v.disposition||"待处置"],["处置依据",v.disposition_evidence||"无"]]}/>}
      {v.kind === "rework" && <><Facts items={[["返工路线",v.route_id],["状态",v.state],["执行凭据",v.execution_event_ids.length],["复测凭据",v.test_ids.length]]}/><ol>{v.route_steps.map(s=><li key={s.station}>{s.station} · {s.instruction_version}</li>)}</ol></>}
      {v.kind === "release" && <><Facts items={[["独立放行类型",v.release_kind],["决定",v.decision],["明确序列号数",v.unit_ids.length],["签署依据",v.evidence],["本地记录人",v.actor_id],["客户签署人",v.external_signatory||"不适用"],["客户",v.customer_id||"不适用"],["合同修订",v.customer_revision||"不适用"],["登记方式",v.method||"本地独立签批"]]}/>{v.source&&<Source value={v.source}/>}</>}
      {v.kind === "interruption" && <Facts items={[["异常类别",v.exception_kind],["中断原因",v.reason],["本地安全请求",v.requested_at],["MES 确认停机",v.authority_stopped_at||"尚未确认"],["MES 试产恢复",v.trial_resumed_at||"尚未确认"],["MES 全部恢复",v.resolved_at||"尚未确认"],["后续安全停机",v.superseded_by?"已移交新的停机请求":"无"]]}/>}
      {v.kind === "interruption" && <><h4>MES 操作历史</h4>{v.stop_exchange_ids.map((id,i)=><button key={id} onClick={()=>onOpen({projectId:data.summary.project_id,kind:"exchange",id})}>停机尝试 {i+1}</button>)}{v.resume_exchange_ids.map((id,i)=><button key={id} onClick={()=>onOpen({projectId:data.summary.project_id,kind:"exchange",id})}>恢复尝试 {i+1}</button>)}</>}
      {v.kind === "exchange" && <>
        <p>{v.mode==="mock"?"模拟权威系统":v.mode==="unavailable"?"权威系统未接入":label(v.mode)}</p>
        <Facts items={[["权威系统",v.system],["阶段",label(v.phase)],["请求数量",v.requested+" "+v.unit],["已接受",v.accepted],["未接受",v.rejected],["原因",v.reason]]}/>
        {!!v.discrepancies?.length&&<><h4>对账异常与处理</h4><ol>{v.discrepancies.map(d=><li key={d.sequence}>负责人 {d.owner_name} · {d.reason} · {d.evidence}{d.resolves_sequence&&" · 已追加处理记录"}</li>)}</ol></>}
        <h4>阶段记录（最近 100 条）</h4><ol>{v.events.map(e=><li key={e.sequence}>{label(e.phase)} · {e.reason}</li>)}</ol>
        {v.stock_basis_proof&&<><h4>已核验原始库存覆盖 · {label(v.stock_basis_proof.mode)}</h4>{v.stock_basis_proof.sources.map(s=><section key={s.source.external_id}><p>{s.material_id} · 所有者 {s.owner_id} · 原始实收 {s.quantity} {s.unit} · 来源顺序 {s.sequence}</p><Source value={s.source}/></section>)}</>}
        {v.receipt&&<><h4>权威明细</h4><p>来源版本 {v.receipt.source_version} · 来源顺序 {v.receipt.sequence}</p><table><thead><tr><th>对象</th><th>接受数量或状态</th><th>单位</th></tr></thead><tbody>{v.receipt.details.map(d=><tr key={d.key}><td>{"effect" in d?(d.effect==="cancel_remaining"?"取消原工单未执行范围":"创建新版工单"):"lot_id" in d?d.owner_id:"sn" in d?d.sn:"object_kind" in d?<button onClick={()=>onOpen({projectId:data.summary.project_id,kind:d.object_kind,id:d.object_id})}>{label(d.object_kind)} · 查看冻结范围</button>:d.scope==="trial"?"试产范围（批量保持停机）":"全部已开工范围"}</td><td>{"effect" in d?`${d.quantity} · 保留 ${d.retained_quantity}`:"lot_id" in d?d.quantity:"order_line_id" in d?"实物已发出"+(d.box_id?` · 箱 ${d.box_id}`:""):label(d.state)}</td><td>{"lot_id" in d?d.unit:"object_kind" in d?"—":"件"}</td></tr>)}</tbody></table></>}
      </>}
      {v.kind === "shipment" && <><Facts items={[["发货状态",label(v.state)],["实际发出",v.shipped+" "+v.unit],["已签收",v.signed],["已验收",v.accepted],["订单待发",v.remaining.remaining_to_ship],["订单待验收",v.remaining.remaining_to_accept]]}/>{v.blocking_reasons.map(reason=><p key={reason}>{reason}</p>)}<h4>箱与明确序列号</h4>{v.boxes.map(box=><p key={box.box_id}>箱 {box.box_id} · {box.unit_ids.length} 件</p>)}<h4>独立签收与验收事实</h4>{v.facts.map(f=><section key={f.id}><p>{f.action==="sign"?"签收":"验收"} {f.quantity} {v.unit} · 实际签署人 {f.external_signatory}</p>{f.source?<Source value={f.source}/>:<p>来源未通过准入</p>}</section>)}<h4>验收问题</h4>{v.issues.map(i=><p key={i.id}>{i.title} · 责任人 {i.owner_name} · {i.required?"必须解决":"一般"} · {i.resolved?"已解决":"未解决"} · {i.evidence}</p>)}</>}
      {v.kind === "closure" && <><Facts items={[["独立关闭类型",label(v.closure_kind)],["当前条件",label(v.status)],["证据",v.evidence]]}/>{v.blocking_reasons.map(reason=><p key={reason}>{reason}</p>)}</>}
      {v.kind === "material_lot" && v.ownership_balance && <><h4>实际所有权余额</h4><Facts items={[["所有者",v.ownership_balance.owner_id],["实收",v.ownership_balance.received],["已消耗",v.ownership_balance.consumed],["原料实际损耗",v.ownership_balance.scrapped],["实际退回",v.ownership_balance.returned],["余额",v.ownership_balance.balance+" "+v.unit],["来源完整",v.ownership_balance.complete?"是":"待权威核验"]]}/></>}
      {v.kind === "material_lot" && <>{v.ownership_balance?.hold_reason&&<p role="alert">{v.ownership_balance.hold_reason}</p>}<h4>实际原料移动（最近 100 条）</h4>{v.material_movements?.map(m=><section key={m.id}><p>{m.movement==="return"?"实物退回":"原料实际损耗"} {m.quantity} {v.unit} · {m.external_signatory} · {m.current?"当前事实":"已追加纠正，保留原始记录"} · {m.evidence}</p>{m.source?<Source value={m.source}/>:<p>来源未通过准入</p>}</section>)}<h4>所有权核对（最近 20 条）</h4>{v.ownership_reconciliations?.map(r=><section key={r.id}><p>{r.current?"与当前实际事实一致":"核对后实际事实已变化"} · 原料余额 {r.balance.balance} {v.unit}</p>{r.source&&<Source value={r.source}/>}</section>)}</>}
      {v.kind === "receipt" && v.corrections?.map(c=><p key={c.sequence}>追加纠正 · 到货 {c.received_delta} · 合格 {c.accepted_delta} · 拒收 {c.rejected_delta} · {c.evidence}</p>)}
      {v.kind === "receipt" && v.confirmations?.map(c=><section key={c.sequence}><h4>来源确认 · {label(c.source.mode)}</h4><p>外部签署人：{c.external_actor} · {c.signature}</p><Source value={c.source}/></section>)}
      {"source" in v && v.source && <Source value={v.source} />}
      <h4>关联记录</h4>
      {data.relations.map((r, i) => (
        <button
          key={i}
          onClick={() =>
            onOpen({ projectId: r.project_id, kind: r.kind, id: r.id })
          }
        >
          {label(r.kind)} · {label(r.relation)}
        </button>
      ))}
      <h4>凭据与历史</h4>
      {data.evidence.map((e, i) => (
        <section key={i}><p>{e.reference}</p>{e.source&&<Source value={e.source}/>}</section>
      ))}
      <ol>
        {data.history.map((h) => (
          <li key={h.event_id}>
            {h.occurred_at} · {label(h.action)} · 录入 {h.recorded_at}
            {h.evidence.map((e,i)=><section key={i}><p>{e.reference}</p>{e.source&&<Source value={e.source}/>}</section>)}
          </li>
        ))}
      </ol>
    </article>
  );
}
export function WorkflowDetail({
  api,
  target,
  onOpen,
  onLoaded,
}: {
  api: WorkflowApi;
  target: WorkflowTarget;
  onOpen(t: WorkflowTarget): void;
  onLoaded?(d: ObjectDetail): void;
}) {
  const [data, setData] = useState<ObjectDetail | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setData(null);
    setError("");
    api
      .object(target.projectId, target.kind, target.id)
      .then((d) => {
        if (active) {
          setData(d);
          onLoaded?.(d);
        }
      })
      .catch((e) => {
        if (active) setError(String(e));
      });
    return () => {
      active = false;
    };
  }, [api, target.projectId, target.kind, target.id]);
  return error ? (
    <p role="alert">{error}</p>
  ) : data ? (
    <DetailContent data={data} onOpen={onOpen} />
  ) : (
    <p>正在读取详情…</p>
  );
}
