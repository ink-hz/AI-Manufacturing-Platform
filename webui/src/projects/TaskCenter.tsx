import type { ControlTarget } from "../collaboration/types";
import { useState } from "react";
import type { Catalog } from "../types";
import { kinds, priorities, workStatus, type FlatTask } from "./types";
import { Choice, Status } from "./ui";
export function TaskCenter({
  items,
  catalog,
  onOpen,
  onControl,
}: {
  items: FlatTask[];
  catalog: Catalog;
  onOpen: (id: string, stage: string, task: string) => void;
  onControl?: (id: string, target: ControlTarget) => void;
}) {
  const [query, setQuery] = useState(""),
    [kind, setKind] = useState(""),
    [status, setStatus] = useState("open"),
    [line, setLine] = useState("");
  const shown = items.filter(
    (t) =>
      (!query ||
        `${t.title} ${t.project_name} ${t.owner}`
          .toLowerCase()
          .includes(query.toLowerCase())) &&
      (!kind || t.kind === kind) &&
      (!line || t.line_id === line) &&
      (status === "all" ||
        (status === "open" && t.status !== "done") ||
        status === t.status),
  );
  return (
    <>
      <div className="mf-section-heading">
        <div>
          <h2>事项中心</h2>
          <p className="mf-muted">
            {shown.length} 项工作 · 所有未归档项目的任务、问题和确认事项
          </p>
        </div>
      </div>
      <div className="mf-filters">
        <label className="mf-field">
          搜索事项
          <input
            aria-label="搜索事项"
            value={query}
            placeholder="事项、项目、负责人"
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <Choice
          label="筛选事项类型"
          value={kind}
          values={{ "": "全部类型", ...kinds }}
          onChange={setKind}
        />
        <Choice
          label="筛选事项状态"
          value={status}
          values={{ open: "未完成", all: "全部状态", ...workStatus }}
          onChange={setStatus}
        />
        <Choice
          label="事项业务线"
          value={line}
          values={{
            "": "全部业务线",
            ...Object.fromEntries(catalog.lines.map((l) => [l.id, l.name])),
          }}
          onChange={setLine}
        />
      </div>
      <div className="mf-surface">
        {shown.map((t) => (
          <div key={t.id} className="mf-task mf-center-task">
            <div className="mf-task-title">
              <span className="mf-eyebrow">
                {kinds[t.kind]} · {priorities[t.priority]}
              </span>
              <button
                className="mf-link"
                onClick={() => onOpen(t.project_id, t.stage_id, t.id)}
              >
                {t.title}
              </button>
              {t.source && onControl && (
                <button
                  className="mf-link mf-small"
                  onClick={() =>
                    onControl(t.project_id, {
                      object_type: "readiness",
                      object_id: t.source!.id,
                      item_id: t.source!.item_id,
                    })
                  }
                >
                  查看来源准备项
                </button>
              )}
              <small className="mf-muted">
                {t.project_name} / {t.stage_id} {t.stage_name} · {t.line_name}
              </small>
            </div>
            <span>
              {t.owner || "未分派"}
              <small className="mf-muted">
                目标 {t.due_date || "未设日期"}
              </small>
            </span>
            <Status value={t.status} text={workStatus[t.status]} />
          </div>
        ))}
        {!shown.length && (
          <div className="mf-empty">
            没有符合筛选的事项。进入项目可创建任务、问题或确认事项。
          </div>
        )}
      </div>
    </>
  );
}
