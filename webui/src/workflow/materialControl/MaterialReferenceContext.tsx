import { useEffect, useState, type ReactNode } from "react";
import type { WorkflowApi } from "../api";
import type { TaskReferenceEvidence, TaskReference } from "./types";

export function MaterialReferenceContext({ api, projectId, projectVersion, evidence, current, currentReference, issue, resolved = true, renderCurrentReceipt }: {
  api: WorkflowApi; projectId: string; projectVersion: number; renderCurrentReceipt?: (receiptId: string | null) => ReactNode; resolved?: boolean; evidence: TaskReferenceEvidence;
  current: boolean | null; currentReference: TaskReference | null; issue: string | null;
}) {
  type ArrivalView = {
    arrival_number: string; location: string; package_count: number; description: string; state: string;
  };
  const id = evidence.reference.kind === "arrival" ? evidence.reference.id : null;
  const referenceKey = JSON.stringify([evidence.reference, currentReference, current]);
  const key = JSON.stringify([projectId, projectVersion, referenceKey]);
  const [read, setRead] = useState<{
    api: WorkflowApi; key: string; arrival?: ArrivalView; receiptId?: string; error?: string;
  } | null>(null);
  // Hide the previous read synchronously, before replacement effects run.
  const visible = resolved && read?.api === api && read.key === key ? read : null;
  const arrival = visible?.arrival;
  const error = visible?.error;
  useEffect(() => {
    setRead(null);
    if (!id || !resolved) return;
    const c = new AbortController();
    api.object(projectId, "arrival", id, c.signal).then(d => {
      if (c.signal.aborted) return;
      if (d.summary.project_id !== projectId || d.summary.id !== id || d.value.kind !== "arrival" || d.value.id !== id)
        throw Error("记录身份不匹配");
      const value = d.value;
      let receiptId: string | undefined;
      if (value.state === "matched") {
        const latest = value.matches?.at(-1);
        if (!value.receipt_id || latest?.receipt_id !== value.receipt_id)
          throw Error("当前收货关联不一致");
        if (currentReference?.kind === "arrival" && currentReference.id === id &&
            currentReference.version === value.matches.length + 1) receiptId = value.receipt_id;
      }
      setRead({ api, key, arrival: value, receiptId });
    }).catch(e => { if (!c.signal.aborted) setRead({ api, key, error: String(e) }); });
    return () => c.abort();
  }, [api, projectId, id, key, resolved]);
  const currentLabel = currentReference?.kind === "arrival" ? `版本 ${currentReference.version}`
    : currentReference?.kind === "source_receipt" ? `版本 ${currentReference.source_key.version}`
    : currentReference?.kind === "mes_component" ? `组件 ${currentReference.component_key} · 快照 ${currentReference.snapshot_id}` : "收货单";
  return (
    <section aria-label="核实依据">
      <h4>{evidence.title}</h4>
      <p>初始依据 · 来源：{({ native: "原生", manual: "手工", file: "文件", mock: "模拟", unknown: "待核对" } as const)[evidence.origin]} · 环境：{evidence.environment === "unknown" ? "待核对" : evidence.environment}</p>
      <p>来源系统：{evidence.system || "未提供"} · 单据：{evidence.external_id || "未提供"} · 版本：{evidence.version ?? "未提供"}</p>
      <p>{!resolved ? "当前状态正在核对" : current === true ? "引用当前有效" : current === false ? "引用已变化" : "当前状态待核对"}{resolved && issue && ` · ${issue}`}</p>
      {resolved && currentReference && current === false && <p>已有同范围当前引用（{currentLabel}），须明确采用。</p>}
      {evidence.reference.kind === "mes_component" && <p>MES组件不表示到货。</p>}
      {id && <>
        {arrival && <p>到件编号 {arrival.arrival_number} · 观察位置 {arrival.location} · 包裹数 {arrival.package_count} · {arrival.description} · {arrival.state === "matched" ? "已关联收货" : "待关联收货"}</p>}
        {error && <p role="alert">到场观察读取失败：{error}</p>}
      </>}
      {/* The composer owns its draft; a refreshing read only changes its eligibility. */}
      {renderCurrentReceipt?.(id ? visible?.receiptId || null
        : resolved && current === true ? evidence.receipt_id || null : null)}
      {evidence.reference.kind === "arrival" && !evidence.work_order_id && <p>待关联工单。</p>}
    </section>
  );
}
