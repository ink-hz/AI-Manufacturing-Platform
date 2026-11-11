import { useEffect, useState } from "react";
import type { OEMWorkspaceProps } from "../OEMWorkspace";
import type { ObjectPage } from "../types";

export function MaterialTaskList({ p }: { p: OEMWorkspaceProps }) {
  const [page, setPage] = useState<ObjectPage | null>(null),
    [offset, setOffset] = useState(0),
    [error, setError] = useState("");
  const [names, setNames] = useState<Record<string, string>>({});
  useEffect(() => {
    if (typeof p.api.materialTasks !== "function") return;
    let active = true;
    const c = new AbortController();
    setPage(null);
    setError("");
    setNames({});
    p.api
      .materialTasks(p.project.id, 50, offset, c.signal)
      .then(async (value) => {
        if (!active) return;
        setPage(value);
        const people =
          value.items.some(
            (item) => item.assignee_id || item.proposed_assignee_id,
          ) && typeof p.api.materialAssignees === "function"
            ? await Promise.all(
                (["iqc", "trace"] as const).map((kind) =>
                  p.api
                    .materialAssignees(p.project.id, kind, c.signal)
                    .catch(() => ({ items: [], total: 0 })),
                ),
              )
            : [];
        if (active) {
          setNames(
            Object.fromEntries(
              people.flatMap((group) =>
                group.items.map((person) => [person.id, person.display_name]),
              ),
            ),
          );
        }
      })
      .catch((e) => {
        if (active) setError(String(e));
      });
    return () => {
      active = false;
      c.abort();
    };
  }, [p.api, p.project.id, p.project.version, offset]);
  return (
    <section aria-label="项目物料任务">
      <h4>物料任务</h4>
      {error ? (
        <p role="alert">任务读取失败：{error}</p>
      ) : !page ? (
        <p role="status">正在读取任务…</p>
      ) : (
        <>
          <p>
            本页 {page.items.length} 条，共 {page.total} 条。
          </p>
          {!page.items.length ? (
            <p>暂无物料任务</p>
          ) : (
            <ul>
              {page.items.map((t) => {
                const owner = t;
                return (
                  <li key={t.id}>
                    <button
                      className="wf-text-link"
                      onClick={() =>
                        p.requestLeave(() =>
                          p.onOpen({
                            projectId: p.project.id,
                            kind: "material_task",
                            id: t.id,
                          }),
                        )
                      }
                    >
                      {t.title}
                    </button>{" "}
                    ·{" "}
                    {(
                      {
                        pending: "待接单",
                        processing: "处理中",
                        verification: "待完成",
                        closed: "已完成",
                        cancelled: "已取消",
                      } as Record<string, string>
                    )[t.state] || t.state}
                    {owner.assignee_id &&
                      ` · 负责人：${names[owner.assignee_id] || "成员资料不可用"}${owner.proposed_assignee_id ? ` · 待接收：${names[owner.proposed_assignee_id] || "成员资料不可用"}` : ""}`}
                  </li>
                );
              })}
            </ul>
          )}
          {offset > 0 && (
            <button
              onClick={() =>
                p.requestLeave(() => setOffset(Math.max(0, offset - 50)))
              }
            >
              上一页任务
            </button>
          )}
          {offset + page.items.length < page.total && (
            <button
              onClick={() => p.requestLeave(() => setOffset(offset + 50))}
            >
              下一页任务
            </button>
          )}
        </>
      )}
    </section>
  );
}
