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
      <p>
        计划与物料需后续权威事实；量产首件需实际试产检验，当前不提供开工操作。
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
          <h4>客户批准 · 人工登记</h4>
          {v.customer_approvals.map((a) => (
            <p key={a.id}>
              {a.customer_id} · {a.external_signatory} · {label(a.decision)} ·{" "}
              {a.evidence}
            </p>
          ))}
        </>
      )}
      {v.kind === "work_order" && (
        <>
          <Facts
            items={[
              ["数量", v.quantity + " " + v.unit],
              ["用途", label(v.purpose)],
              ["试产数量", v.trial_quantity + " " + v.unit],
              ["计划开始", v.planned_start],
              ["计划结束", v.planned_end],
            ]}
          />
          <ReadinessView title="试产准备" value={v.trial_readiness} />
          <ReadinessView title="量产准备" value={v.bulk_readiness} />
        </>
      )}
      {"source" in v && <Source value={v.source} />}
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
        <p key={i}>{e.reference}</p>
      ))}
      <ol>
        {data.history.map((h) => (
          <li key={h.event_id}>
            {h.occurred_at} · {label(h.action)} · 录入 {h.recorded_at}
            {h.evidence.map((e,i)=><p key={i}>{e.reference}</p>)}
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
