import { useEffect, useState } from "react";
import type { WorkflowApi } from "../api";
import type { MaterialHandoffValue } from "../materialHandoffTypes";
import type { ReceiptUse } from "../materialHandoffTypes";
import { executionScopeLabel, type MaterialRequirement } from "../materialControl/types";

interface UseValue { receipt_use: ReceiptUse; requirement_id: string | null }
export function ReceiptUseFields({ api, projectId, projectVersion, handoff, value, onChange, onReady,
  allowUnspecified = true, disabled = false }: {
  api: WorkflowApi; projectId: string; projectVersion: number; handoff: MaterialHandoffValue;
  value: UseValue; onChange(value: UseValue): void; onReady(ready: boolean): void;
  allowUnspecified?: boolean; disabled?: boolean;
}) {
  const [requirements, setRequirements] = useState<MaterialRequirement[]>([]);
  const [loading, setLoading] = useState(false), [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (value.receipt_use === "line_side")
      onReady(!loading && !error && requirements.some(r => r.id === value.requirement_id && ["trial", "bulk", "common"].includes(r.execution_scope || "")));
  }, [value.receipt_use, value.requirement_id, requirements, loading, error, onReady]);
  useEffect(() => {
    const c = new AbortController();
    setRequirements([]); setError(""); setLoading(false);
    if (value.receipt_use !== "line_side") { onReady(true); return () => c.abort(); }
    onReady(false);
    if (!handoff.work_order_id) {
      setError("这笔交接未关联工单，请先核对交接归属。");
      return () => c.abort();
    }
    setLoading(true);
    async function read() {
      try {
        const detail = await api.object(projectId, "material_lot", handoff.material_lot_id, c.signal);
        if (c.signal.aborted) return;
        if (detail.value.kind !== "material_lot") throw Error("批次资料不匹配，请重新读取。");
        const lot = detail.value;
        const matches: MaterialRequirement[] = [], seen = new Set<string>();
        let offset = 0, total: number | null = null, version: number | null = null;
        do {
          const page = await api.materialProject(projectId, 50, offset, c.signal,
            { work_order_id: handoff.work_order_id!, search: lot.material_id, problem: "all" });
          if (c.signal.aborted) return;
          if (page.project_version !== undefined && page.project_version !== projectVersion)
            throw Error("项目资料已变化，请放弃草稿并重新打开收料操作。");
          if (total !== null && page.total !== total || version !== null && page.project_version !== version)
            throw Error("物料需求已变化，请重新读取后选择。");
          total = page.total; version = page.project_version ?? null;
          if (page.requirements.length === 0 && offset < total) throw Error("物料需求未完整读取，请重试。");
          for (const requirement of page.requirements) {
            if (seen.has(requirement.id)) throw Error("物料需求已变化，请重新读取。");
            seen.add(requirement.id);
            if (requirement.work_order_id === handoff.work_order_id && requirement.material_id === lot.material_id
                && requirement.owner_id === lot.owner_id && requirement.unit === lot.unit
                && requirement.state !== "superseded") matches.push(requirement);
          }
          offset += page.requirements.length;
        } while (offset < total);
        if (!c.signal.aborted) { setRequirements(matches); setLoading(false); }
      } catch (e) {
        if (!c.signal.aborted) { setError(e instanceof Error ? e.message : "物料需求读取失败，请重试。"); setLoading(false); onReady(false); }
      }
    }
    void read();
    return () => c.abort();
  }, [api, projectId, projectVersion, handoff.id, handoff.material_lot_id, handoff.work_order_id, value.receipt_use, retry, onReady]);
  return <>
    <label>实收用途 <select aria-label="实收用途" disabled={disabled} value={value.receipt_use}
      onChange={e => onChange({ receipt_use: e.target.value as ReceiptUse, requirement_id: null })}>
      {allowUnspecified && <option value="unspecified">暂未核对用途</option>}
      <option value="transfer">中转接收</option><option value="line_side">线边实收</option>
    </select></label>
    {value.receipt_use === "line_side" && <>
      {loading && <p role="status">正在读取当前工单的物料需求…</p>}
      {error && <p role="alert">{error} <button type="button" disabled={disabled || loading} onClick={() => setRetry(v => v + 1)}>重新读取物料需求</button></p>}
      {!loading && !error && requirements.length === 0 && <p>没有匹配的当前物料需求，请核对工单、批次和物料归属。</p>}
      <label>对应物料需求 <select aria-label="对应物料需求" value={value.requirement_id || ""}
        disabled={disabled || loading || !!error} onChange={e => onChange({ ...value, requirement_id: e.target.value || null })}>
        <option value="">请选择本次实收对应的需求</option>
        {requirements.map(r => <option key={r.id} value={r.id} disabled={!["trial", "bulk", "common"].includes(r.execution_scope || "")}>{r.material_id} · {executionScopeLabel(r.execution_scope)} · 需求 {r.required} {r.unit} · {r.owner_id}</option>)}
      </select></label>
    </>}
  </>;
}
