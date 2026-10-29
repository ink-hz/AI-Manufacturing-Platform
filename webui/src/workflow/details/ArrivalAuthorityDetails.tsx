import type { ObjectDetail, WorkflowTarget } from "../types";
import { label } from "../labels";
export function ArrivalAuthorityDetails({
  data,
  onOpen,
}: {
  data: ObjectDetail;
  onOpen(t: WorkflowTarget): void;
}) {
  const v = data.value;
  if (v.kind === "arrival")
    return (
      <section>
        <p>
          到件编号 {v.arrival_number} · 观察位置 {v.location} · 包裹数{" "}
          {v.package_count}
        </p>
        <p>
          {v.description} · {v.actor_id} · {v.recorded_at}
        </p>
        <p>
          匹配状态：{label(v.state)}。此记录不代表库存移动、IQC 合格或预留。
        </p>
        <h4>完整匹配与纠正历史</h4>
        {v.matches.map((r) => (
          <section key={r.id}>
            <button
              onClick={() =>
                onOpen({
                  projectId: data.summary.project_id,
                  kind: "receipt",
                  id: r.receipt_id,
                })
              }
            >
              查看此次到货凭据
            </button>
            {r.previous_receipt_id && (
              <button
                onClick={() =>
                  onOpen({
                    projectId: data.summary.project_id,
                    kind: "receipt",
                    id: r.previous_receipt_id!,
                  })
                }
              >
                查看纠正前凭据
              </button>
            )}
            <p>
              {r.evidence} · {r.correction_reason || "首次匹配"} · {r.actor_id}{" "}
              · {r.recorded_at}
            </p>
          </section>
        ))}
      </section>
    );
  if (v.kind === "authority_rule")
    return (
      <section>
        <p>
          责任对象 {label(v.object_category)} · 范围 {v.business_scope}
        </p>
        <p>
          候选系统 {v.system} · 责任人或组织 {v.responsible_identity}
        </p>
        <p>
          责任映射状态：{label(v.state)} · 修订 {v.revision} ·{" "}
          {v.active ? "当前修订" : "历史修订"}
        </p>
        <p>
          实际连接状态：
          {v.connection_state === "demo" ? "隔离演示适配器" : "未接入"}
        </p>
        <p>
          {label(v.origin)} · {v.evidence} · {v.actor_id} · {v.recorded_at}
        </p>
        {v.verification && (
          <p>
            责任契约核验：{v.verification.contract_evidence} ·{" "}
            {v.verification.actor_id} · {v.verification.recorded_at}
          </p>
        )}
        <p>契约核验不会连接系统或更改现有生产路由。</p>
      </section>
    );
  if (v.kind === "receipt")
    return (
      <section>
        <p>
          数量状态：{label(v.quantity_state || "unknown")} · 下一步：
          {label(v.next_step || "unknown")}
        </p>
        <p>
          已接收 {v.quantity} · 已检合格 {v.accepted} · 拒收 {v.rejected} · 待检{" "}
          {v.uninspected} {v.unit}
        </p>
      </section>
    );
  return null;
}
