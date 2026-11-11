import { useEffect, useState } from "react";
import type { WorkflowApi } from "../api";
import type { MaterialOverview } from "./types";
export function MaterialControlOverview({
  api,
  refresh,
  onProject,
}: {
  api: WorkflowApi;
  refresh: number;
  onProject(id: string): void;
}) {
  const [page, setPage] = useState<MaterialOverview | null>(null),
    [offset, setOffset] = useState(0),
    [error, setError] = useState("");
  useEffect(() => {
    const c = new AbortController();
    let active = true;
    setPage(null);
    setError("");
    api
      .materialOverview(50, offset, c.signal)
      .then((v) => {
        if (active) setPage(v);
      })
      .catch((e) => {
        if (active) setError(String(e));
      });
    return () => {
      active = false;
      c.abort();
    };
  }, [api, refresh, offset]);
  return (
    <section className="wf-panel" aria-label="项目料况概览">
      <h2>项目料况</h2>
      {error ? (
        <p role="alert">项目料况读取失败：{error}</p>
      ) : !page ? (
        <p role="status">正在读取项目料况…</p>
      ) : !page.items.length ? (
        <p>暂无项目料况。</p>
      ) : (
        <>
          <div className="wf-table-scroll">
            <table>
              <thead>
                <tr>
                  <th>项目</th>
                  <th>产品</th>
                  <th>工单</th>
                  <th>物料需求</th>
                  <th>催料中</th>
                  <th>待收料</th>
                  <th>物料任务</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((p) => (
                  <tr key={p.project_id}>
                    <td>{p.name}</td>
                    <td>{p.product}</td>
                    <td>{p.work_order_count ?? "—"}</td>
                    <td>{p.requirement_count}</td>
                    <td>{p.open_expedite_count}</td>
                    <td>{p.unreceived_handoff_count}</td>
                    <td>{p.open_material_task_count}</td>
                    <td>
                      <button onClick={() => onProject(p.project_id)}>
                        查看料况
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {offset > 0 && (
            <button onClick={() => setOffset(Math.max(0, offset - 50))}>
              上一页
            </button>
          )}
          {offset + page.items.length < page.total && (
            <button onClick={() => setOffset(offset + 50)}>下一页</button>
          )}
        </>
      )}
    </section>
  );
}
