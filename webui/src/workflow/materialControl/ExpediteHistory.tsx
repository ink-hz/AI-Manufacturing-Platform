import { useState } from "react";
import type { WorkflowApi } from "../api";
export function ExpediteHistory({
  api,
  projectId,
  id,
  total,
}: {
  api: WorkflowApi;
  projectId: string;
  id: string;
  total?: number;
}) {
  const [items, setItems] = useState<
      { note: string; actor_name?: string; recorded_at?: string }[] | null
    >(null),
    [error, setError] = useState("");
  async function load() {
    try {
      const detail = await api.object(projectId, "material_expedite", id);
      const value = detail.value as unknown as {
        progress: { note: string; actor_name?: string; recorded_at?: string }[];
      };
      setItems(value.progress);
    } catch (e) {
      setError(String(e));
    }
  }
  return (
    <div>
      <p>已显示部分进展{total != null && `，共 ${total} 条`}。</p>
      {error && <p role="alert">{error}</p>}
      {!items ? (
        <button onClick={() => void load()}>查看全部催料进展</button>
      ) : (
        <details open>
          <summary>全部催料进展</summary>
          {items.map((v, i) => (
            <p key={i}>
              {v.recorded_at} {v.actor_name} {v.note}
            </p>
          ))}
        </details>
      )}
    </div>
  );
}
