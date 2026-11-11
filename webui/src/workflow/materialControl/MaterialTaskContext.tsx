import { useEffect, useState } from "react";
import type { WorkflowApi } from "../api";
import type { ObjectDetail } from "../types";

function equalQuantity(a: string, b: string) {
  const normalize = (s: string) => {
    const [whole, fraction = ""] = s.split(".");
    return [whole.replace(/^0+/, "") || "0", fraction.replace(/0+$/, "")].join(
      ".",
    );
  };
  return normalize(a) === normalize(b);
}

export function MaterialTaskContext({
  api,
  projectId,
  receiptId,
  handoffId,
  version,
  onReceipt,
}: {
  api: WorkflowApi;
  projectId: string;
  receiptId: string | null;
  handoffId: string | null;
  version: number;
  onReceipt?(detail: ObjectDetail): void;
}) {
  const [record, setRecord] = useState<ObjectDetail | null>(null);
  const [lot, setLot] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    const id = receiptId || handoffId;
    if (!id) return;
    const c = new AbortController();
    setRecord(null);
    setLot("");
    setError("");
    api
      .object(
        projectId,
        receiptId ? "receipt" : "material_handoff",
        id,
        c.signal,
      )
      .then(async (detail) => {
        if (c.signal.aborted) return;
        setRecord(detail);
        if (receiptId) onReceipt?.(detail);
        const value = detail.value;
        if (
          value &&
          (value.kind === "receipt" || value.kind === "material_handoff") &&
          value.material_lot_id
        ) {
          const batch = await api.object(
            projectId,
            "material_lot",
            value.material_lot_id,
            c.signal,
          );
          if (!c.signal.aborted) setLot(batch.summary.title);
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(String(e));
      });
    return () => c.abort();
  }, [api, projectId, receiptId, handoffId, version]);
  if (error && !record) return <p role="alert">关联记录读取失败：{error}</p>;
  if (!record) return <p>正在读取关联记录…</p>;
  const value = record.value;
  if (value?.kind === "receipt")
    return (
      <section aria-label="检验到货">
        <h4>{record.summary.title}</h4>
        <p>批次：{lot || "未取得"}</p>
        <p>
          到货 {value.quantity ?? "未取得"} {value.unit} · 检验合格{" "}
          {value.accepted ?? "未取得"} {value.unit} · 拒收{" "}
          {value.rejected ?? "未取得"} {value.unit} · 待检{" "}
          {value.uninspected ?? "未取得"} {value.unit}
        </p>
        <p>
          质量状态：
          {(
            {
              pending_inspection: "待检",
              partially_inspected: "部分已检",
              accepted: "合格",
              rejected: "拒收",
              mixed: "合格与拒收",
            } as Record<string, string>
          )[value.quantity_state || ""] || "未取得"}
        </p>
        <details>
          <summary>查看到货详情</summary>
          <p>
            来源：{value.source?.system || "未取得"} ·{" "}
            {value.source?.external_id || "未取得"}
          </p>
          <p>
            原始到货 {value.original_quantity ?? value.quantity} {value.unit}
          </p>
        </details>
      </section>
    );
  if (value?.kind === "material_handoff")
    return (
      <section aria-label="原交料">
        <h4>{value.handoff_number}</h4>
        <p>
          批次：{lot || "未取得"} · 接收人：{value.receiver_name} · 送达：
          {value.to_location}
        </p>
        <p>
          应收 {value.quantity} {value.unit} ·{" "}
          {value.receipt
            ? `已签收 ${value.receipt.received_quantity} ${value.unit}，位置 ${value.receipt.received_location}`
            : "尚未签收"}
        </p>
        <details>
          <summary>查看交料详情</summary>
          <p>
            交出位置：{value.from_location} · 交出人：{value.sender_name}
          </p>
          <p>
            {value.receipt
              ? `签收人：${value.receipt.actor_name} · ${value.receipt.occurred_at}`
              : "尚无签收记录"}
          </p>
          {value.resolution && <p>处理说明：{value.resolution.resolution}</p>}
        </details>
        {value.receipt &&
          (!equalQuantity(value.quantity, value.receipt.received_quantity) ||
            value.receipt.received_location !== value.to_location) && (
            <p>
              交接差异{value.state === "resolved" ? "已处理" : "待处理"}：
              {value.receipt?.note || "请核对实际交料"}
            </p>
          )}
      </section>
    );
  return <p>关联记录类型不符，请重新读取。</p>;
}
