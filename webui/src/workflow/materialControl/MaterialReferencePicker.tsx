import { useEffect, useState } from "react";
import type { WorkflowApi } from "../api";
import { validateReferencePage } from "./api";
import type { TaskReferenceItem, TaskReferencePage } from "./types";

export function MaterialReferencePicker({ api, projectId, version, kind, onSelect, requirementId }: {
  api: WorkflowApi; projectId: string; version: number; kind: "verify" | "iqc";
  requirementId?: string; onSelect(item: TaskReferenceItem, pageVersion: number): void;
}) {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [loaded, setLoaded] = useState<{page:TaskReferencePage; api:WorkflowApi; scope:string} | null>(null);
  const scope = JSON.stringify([projectId, version, kind, query, offset, requirementId]);
  const page = loaded?.api === api && loaded.scope === scope ? loaded.page : null;
  const [error, setError] = useState("");
  useEffect(() => {
    const c = new AbortController();
    setLoaded(null);
    setError("");
    if (typeof api.materialReferences !== "function") {
      setError("引用查询不可用");
      return () => c.abort();
    }
    const request = requirementId
      ? api.materialReferences(projectId, kind, query, 50, offset, c.signal, requirementId)
      : api.materialReferences(projectId, kind, query, 50, offset, c.signal);
    request.then(v => { if (!c.signal.aborted) setLoaded({page:validateReferencePage(v, projectId, kind), api, scope}); })
      .catch(e => { if (!c.signal.aborted) setError(String(e)); });
    return () => c.abort();
  }, [api, projectId, version, kind, query, offset, requirementId]);
  return (
    <section aria-label="选择核实依据">
      <label>搜索引用<input aria-label="搜索引用" value={search} onChange={e => setSearch(e.target.value)} /></label>
      <button onClick={() => { setOffset(0); setQuery(search); }}>搜索引用</button>
      {error && <p role="alert">引用读取失败：{error}</p>}
      {!error && !page && <p role="status">正在读取引用…</p>}
      {page && <>
        <ul>{page.items.map((item, i) => <li key={JSON.stringify(item.reference) + i}>
          <button disabled={!item.can_open && !item.existing_task_id} onClick={() => onSelect(item, page.project_version)}>{item.evidence.title}</button>
          {" · 来源 "}{({ native: "原生", manual: "手工", file: "文件", mock: "模拟", unknown: "来源待核对" } as const)[item.evidence.origin]}
          {" · 环境 "}{item.evidence.environment === "unknown" ? "待核对" : item.evidence.environment}
          {item.reference.kind === "mes_component" && " · MES组件，非到货"}
          {item.reference.kind === "arrival" && !item.evidence.work_order_id && " · 待关联工单"}
        </li>)}</ul>
        <p>共 {page.total} 条</p>
        {offset > 0 && <button onClick={() => setOffset(Math.max(0, offset - 50))}>上一页引用</button>}
        {offset + page.items.length < page.total && <button onClick={() => setOffset(offset + 50)}>下一页引用</button>}
      </>}
    </section>
  );
}
