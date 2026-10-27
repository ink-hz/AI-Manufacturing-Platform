import { ControlAttention } from "../collaboration/ControlAttention";
import type { ControlTarget } from "../collaboration/types";
import type { Dashboard } from "./types";
import { kinds, priorities, workStatus } from "./types";
import { ProjectCard } from "./ProjectList";
import { ActivityFeed } from "./ActivityFeed";
import { Status } from "./ui";
export function ProjectHome({
  data,
  onOpen,
  onFilter,
  onTasks,
  onControl,
}: {
  data: Dashboard;
  onOpen: (id: string, stage?: string, task?: string) => void;
  onFilter: (status: string) => void;
  onTasks: () => void;
  onControl?: (id: string, target: ControlTarget) => void;
}) {
  return (
    <>
      <div className="mf-summary-strip" aria-label="工作摘要">
        {(
          [
            ["在管项目", data.counts.active_projects, "incomplete"],
            ["受阻项目", data.counts.blocked_projects, "blocked"],
            ["近七天到期", data.counts.due_soon, "soon"],
          ] as const
        ).map(([name, count, filter]) => (
          <button key={name} onClick={() => onFilter(filter)}>
            <strong>{count}</strong>
            <span>{name}</span>
          </button>
        ))}
        <button onClick={onTasks}>
          <strong>{data.counts.open_tasks}</strong>
          <span>未完成事项</span>
        </button>
      </div>
      <div className="mf-home-grid">
        <section>
          <div className="mf-section-heading">
            <h2>正在推进</h2>
            <button className="mf-link" onClick={() => onFilter("current")}>
              查看全部项目
            </button>
          </div>
          {data.projects.length ? (
            <div className="mf-project-grid">
              {data.projects.map((p) => (
                <ProjectCard key={p.id} project={p} onOpen={onOpen} />
              ))}
            </div>
          ) : (
            <div className="mf-empty">
              <h3>从第一项真实交付开始</h3>
              <p>新建制造项目，登记负责人和交付目标，再进入阶段分派事项。</p>
              <p className="mf-muted">
                目前没有项目，摘要和动态仅显示已保存的工作。
              </p>
            </div>
          )}
          <div className="mf-surface mf-activity-panel">
            <ActivityFeed items={data.activity.slice(0, 8)} onOpen={onOpen} />
          </div>
        </section>
        <aside className="mf-surface mf-attention">
          <h2>需要关注</h2>
          <p className="mf-muted">
            {data.counts.pending_confirmations} 项待确认 ·
            优先处理受阻与临期工作
          </p>
          {onControl && (
            <ControlAttention
              items={data.control_attention || []}
              onOpen={onControl}
            />
          )}
          {data.blockers.length > 0 && (
            <section>
              <h3>阻塞问题</h3>
              {data.blockers.slice(0, 5).map((b, i) => (
                <div className="mf-attention-row" key={i}>
                  <button
                    className="mf-link"
                    onClick={() =>
                      onOpen(b.project_id, b.stage_id, b.task_id || undefined)
                    }
                  >
                    {b.title}
                  </button>
                  <p>{b.reason || "请核对受阻说明"}</p>
                  <small>
                    {b.project_name} · {b.owner || "未分派"} ·{" "}
                    {b.due_date || "未设日期"}
                  </small>
                </div>
              ))}
            </section>
          )}
          {data.attention.slice(0, 8).map((t) => (
            <div className="mf-attention-row" key={t.id}>
              <div className="mf-section-heading">
                <span className="mf-eyebrow">
                  {kinds[t.kind]} · {priorities[t.priority]}
                </span>
                <Status value={t.status} text={workStatus[t.status]} />
              </div>
              <button
                className="mf-link"
                onClick={() => onOpen(t.project_id, t.stage_id, t.id)}
              >
                {t.title}
              </button>
              <small>
                {t.project_name} · {t.owner || "未分派"}
                <br />
                目标 {t.due_date || "未设日期"}
              </small>
            </div>
          ))}
          {!data.attention.length && !data.blockers.length && (
            <p className="mf-muted">
              没有待处理事项。进入项目可登记任务、问题和确认事项。
            </p>
          )}
        </aside>
      </div>
    </>
  );
}
