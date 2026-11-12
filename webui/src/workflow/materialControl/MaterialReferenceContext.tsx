import { useEffect, useState } from "react";
import type { WorkflowApi } from "../api";
import type { TaskReferenceEvidence, TaskReference } from "./types";

export function MaterialReferenceContext({ api, projectId, evidence, current, currentReference, issue }: {
  api: WorkflowApi; projectId: string; evidence: TaskReferenceEvidence;
  current: boolean | null; currentReference: TaskReference | null; issue: string | null;
}) {
  const [arrival, setArrival] = useState<{
    arrival_number: string; location: string; package_count: number; description: string; state: string;
  } | null>(null);
  const [error, setError] = useState("");
  const id = evidence.reference.kind === "arrival" ? evidence.reference.id : null;
  useEffect(() => {
    setArrival(null);
    setError("");
    if (!id) return;
    const c = new AbortController();
    api.object(projectId, "arrival", id, c.signal).then(d => {
      if (c.signal.aborted) return;
      if (d.summary.project_id !== projectId || d.summary.id !== id || d.value.kind !== "arrival")
        throw Error("记录身份不匹配");
      setArrival(d.value);
    }).catch(e => { if (!c.signal.aborted) setError(String(e)); });
    return () => c.abort();
  }, [api, projectId, id]);
  const currentLabel = currentReference?.kind === "arrival" ? `版本 ${currentReference.version}`
    : currentReference?.kind === "source_receipt" ? `版本 ${currentReference.source_key.version}`
    : currentReference?.kind === "mes_component" ? `组件 ${currentReference.component_key}` : "收货单";
  return (
    <section aria-label="核实依据">
      <h4>{evidence.title}</h4>
      <p>初始依据 · 来源：{({ native: "原生", manual: "手工", file: "文件", mock: "模拟", unknown: "待核对" } as const)[evidence.origin]} · 环境：{evidence.environment === "unknown" ? "待核对" : evidence.environment}</p>
      <p>来源系统：{evidence.system || "未提供"} · 单据：{evidence.external_id || "未提供"} · 版本：{evidence.version ?? "未提供"}</p>
      <p>{current === true ? "引用当前有效" : current === false ? "引用已变化" : "当前状态待核对"}{issue && ` · ${issue}`}</p>
      {currentReference && current === false && <p>已有同范围当前引用（{currentLabel}），须明确采用。</p>}
      {evidence.reference.kind === "mes_component" && <p>MES组件不表示到货。</p>}
      {id && <>
        {arrival && <p>到件编号 {arrival.arrival_number} · 观察位置 {arrival.location} · 包裹数 {arrival.package_count} · {arrival.description} · {arrival.state === "matched" ? "已关联收货" : "待关联收货"}</p>}
        {error && <p role="alert">到场观察读取失败：{error}</p>}
      </>}
      {evidence.reference.kind === "arrival" && !evidence.work_order_id && <p>待关联工单。</p>}
    </section>
  );
}
