import type { Catalog } from "../types";
import { projectStatus, type ProjectSummary } from "./types";
import { Choice, Status } from "./ui";
export interface ProjectFilters {
  query: string;
  group: string;
  line: string;
  status: string;
  view: "list" | "board";
}
export const defaultFilters: ProjectFilters = {
  query: "",
  group: "",
  line: "",
  status: "current",
  view: "list",
};
export function Progress({ project: p }: { project: ProjectSummary }) {
  return (
    <div
      className="mf-progress"
      role="img"
      aria-label={`已完成 ${p.completed_stages}/${p.total_stages} 个阶段`}
    >
      {Array.from({ length: p.total_stages }, (_, i) => (
        <span
          key={i}
          className={i < p.completed_stages ? "mf-progress-done" : ""}
        />
      ))}
    </div>
  );
}
export function ProjectCard({
  project: p,
  onOpen,
}: {
  project: ProjectSummary;
  onOpen: (id: string) => void;
}) {
  return (
    <article className="mf-project-card">
      <div className="mf-section-heading">
        <span className="mf-eyebrow">
          {p.line_name} · {p.code.slice(0, 15)}
        </span>
        <Status value={p.status} text={projectStatus[p.status]} />
      </div>
      <button className="mf-project-title mf-link" onClick={() => onOpen(p.id)}>
        {p.name}
      </button>
      <p className="mf-meta">
        {p.owner} · 目标 {p.due_date || "未设日期"}
      </p>
      <div className="mf-card-foot">
        <span>
          {p.current_stage_id} {p.current_stage_name}
        </span>
        <small>
          {p.completed_stages}/{p.total_stages} 阶段 · {p.open_tasks} 项未完成
        </small>
      </div>
      <Progress project={p} />
      {p.status === "blocked" && (
        <p className="mf-blocked-note">存在受阻工作，进入项目处理</p>
      )}
    </article>
  );
}
export function filterProjects(items: ProjectSummary[], f: ProjectFilters) {
  return items.filter(
    (p) =>
      (!f.query ||
        `${p.name} ${p.code} ${p.owner} ${p.product} ${p.customer}`
          .toLowerCase()
          .includes(f.query.toLowerCase())) &&
      (!f.group || p.group_id === f.group) &&
      (!f.line || p.line_id === f.line) &&
      (f.status === "all" ||
        (f.status === "current" && !p.archived) ||
        (f.status === "incomplete" &&
          !["archived", "completed"].includes(p.status)) ||
        p.status === f.status ||
        (f.status === "soon" &&
          !p.archived &&
          p.status !== "completed" &&
          !!p.due_date &&
          p.due_date >= new Date().toISOString().slice(0, 10) &&
          p.due_date <=
            new Date(Date.now() + 6 * 86400000).toISOString().slice(0, 10))),
  );
}
export function ProjectList({
  items,
  catalog,
  filters: f,
  onFilters,
  onOpen,
}: {
  items: ProjectSummary[];
  catalog: Catalog;
  filters: ProjectFilters;
  onFilters: (f: ProjectFilters) => void;
  onOpen: (id: string) => void;
}) {
  const shown = filterProjects(items, f);
  const set = (key: keyof ProjectFilters, value: string) =>
    onFilters({ ...f, [key]: value });
  return (
    <>
      <div className="mf-section-heading">
        <div>
          <h2>制造项目</h2>
          <p className="mf-muted">
            {shown.length} 个项目 · 用阶段与事项推进交付
          </p>
        </div>
        <div className="mf-actions" aria-label="项目视图">
          <button
            aria-pressed={f.view === "list"}
            onClick={() => set("view", "list")}
          >
            列表
          </button>
          <button
            aria-pressed={f.view === "board"}
            onClick={() => set("view", "board")}
          >
            看板
          </button>
        </div>
      </div>
      <div className="mf-filters">
        <label className="mf-field">
          搜索项目
          <input
            aria-label="搜索项目"
            placeholder="项目、型号、负责人"
            value={f.query}
            onChange={(e) => set("query", e.target.value)}
          />
        </label>
        <Choice
          label="业务归属"
          value={f.group}
          values={{
            "": "全部归属",
            ...Object.fromEntries(catalog.groups.map((g) => [g.id, g.name])),
          }}
          onChange={(v) => onFilters({ ...f, group: v, line: "" })}
        />
        <Choice
          label="项目业务线"
          value={f.line}
          values={{
            "": "全部业务线",
            ...Object.fromEntries(
              catalog.lines
                .filter((l) => !f.group || l.group_id === f.group)
                .map((l) => [l.id, l.name]),
            ),
          }}
          onChange={(v) => set("line", v)}
        />
        <Choice
          label="项目状态"
          value={f.status}
          values={{
            current: "未归档",
            all: "全部状态",
            incomplete: "在管项目",
            soon: "近七天到期",
            ...projectStatus,
          }}
          onChange={(v) => set("status", v)}
        />
      </div>
      {!shown.length && (
        <div className="mf-empty">
          没有符合筛选的项目。可调整筛选或新建项目。
        </div>
      )}
      {f.view === "board" ? (
        <div className="mf-board">
          {Object.entries(projectStatus)
            .filter(
              ([id]) => id !== "archived" || shown.some((p) => p.archived),
            )
            .map(([id, name]) => (
              <section key={id} className="mf-board-column">
                <h3>
                  {name}{" "}
                  <small>{shown.filter((p) => p.status === id).length}</small>
                </h3>
                {shown
                  .filter((p) => p.status === id)
                  .map((p) => (
                    <ProjectCard key={p.id} project={p} onOpen={onOpen} />
                  ))}
              </section>
            ))}
        </div>
      ) : (
        <div className="mf-project-table">
          {shown.map((p) => (
            <div className="mf-project-row" key={p.id}>
              <div>
                <button
                  className="mf-link mf-project-title"
                  onClick={() => onOpen(p.id)}
                >
                  {p.name}
                </button>
                <small className="mf-muted">
                  {p.line_name} · {p.code.slice(0, 15)}
                </small>
              </div>
              <div>
                {p.current_stage_id} {p.current_stage_name}
                <Progress project={p} />
              </div>
              <div>
                {p.owner}
                <small className="mf-muted">
                  目标 {p.due_date || "未设日期"}
                </small>
              </div>
              <Status value={p.status} text={projectStatus[p.status]} />
              <small>{p.open_tasks} 项未完成</small>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
