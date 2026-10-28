import { useEffect, useState } from "react";
import type { WorkflowApi } from "../api";
import type { DomainValue } from "../types";
export function OrderChangePreview({
  api,
  projectId,
  orderId,
  quantity,
  dueDate,
  cancel,
  onReady,
}: {
  api: WorkflowApi;
  projectId: string;
  orderId: string;
  quantity: string;
  dueDate: string;
  cancel: boolean;
  onReady(id: string | null): void;
}) {
  const [data, setData] = useState<Extract<
      DomainValue,
      { kind: "order_line" }
    > | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setData(null);
    setError("");
    onReady(null);
    if (!orderId) return;
    api
      .object(projectId, "order_line", orderId)
      .then((detail) => {
        if (!active) return;
        if (detail.value.kind !== "order_line")
          throw new Error("订单资料类型不匹配");
        setData(detail.value);
        onReady(orderId);
      })
      .catch((e) => {
        if (active)
          setError("无法读取承诺影响，请重新选择订单后重试。" + String(e));
      });
    return () => {
      active = false;
    };
  }, [api, projectId, orderId, onReady]);
  if (!orderId) return <p>选择订单后读取承诺、已分配合计与已登记工单总量。</p>;
  return (
    <section aria-label="承诺变更影响预览" className="wf-comparison">
      <h4>提交前影响预览</h4>
      {error ? (
        <p role="alert">{error}</p>
      ) : !data ? (
        <p role="status">正在读取订单与工单影响…</p>
      ) : (
        <>
          <p>
            当前 → 拟变更承诺：{data.current_quantity} →{" "}
            {cancel ? "0" : quantity || "待填写"} {data.unit}
          </p>
          <p>
            当前 → 拟变更交期：{data.current_due} → {dueDate || "待填写"}
          </p>
          <p>
            变更来源须沿用 {data.source.system} · {data.source.external_id}，来源版本须大于 {data.source.version}。
          </p>
          {cancel && <p>取消时变更后数量仍须填写当前数量 {data.current_quantity}，作为撤销依据；实际承诺为 0。</p>}
          <p>
            已分配合计：{data.allocated} {data.unit}（订单级事实）
          </p>
          <p>
            已登记工单总量：{data.work_order_impact.registered_quantity}{" "}
            {data.unit}
          </p>
          <p>
            显示 {data.work_order_impact.shown} / {data.work_order_impact.total}{" "}
            个工单
            {data.work_order_impact.has_more
              ? " · 仅展示部分业务编号；上述总量包含全部工单"
              : " · 业务编号已全部展示"}
          </p>
          <table>
            <thead>
              <tr>
                <th>受影响工单业务编号</th>
                <th>已登记工单数量</th>
              </tr>
            </thead>
            <tbody>
              {data.work_order_impact.items.map((w) => (
                <tr key={w.id}>
                  <td>
                    {w.source_system} · {w.external_id}
                  </td>
                  <td>
                    {w.quantity} {w.unit}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.work_order_impact.total === 0 && <p>未发现已登记工单。</p>}
          <p>
            已登记但尚未分配的工单同样列入影响。保存后仍需按实际影响清单处理；取消或拆分需权威业务回执。
          </p>
        </>
      )}
    </section>
  );
}
export function ImpactReference({
  api,
  projectId,
  id,
}: {
  api: WorkflowApi;
  projectId: string;
  id: string;
}) {
  const [name, setName] = useState("正在读取工单业务编号…");
  useEffect(() => {
    let active = true;
    api
      .object(projectId, "work_order", id)
      .then((d) => {
        if (active) setName(d.summary.title);
      })
      .catch(() => {
        if (active) setName("工单业务编号读取失败，请重新读取");
      });
    return () => {
      active = false;
    };
  }, [api, projectId, id]);
  return <span>{name}</span>;
}
