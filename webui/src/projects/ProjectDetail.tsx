import { useCallback, useEffect, useRef, useState } from "react";
import type { Api } from "../api";
import type { Catalog } from "../types";
import {
  projectStatus,
  workStatus,
  kinds,
  priorities,
  message,
  type ProjectDetailData,
  type ProjectTask,
} from "./types";
import { StagePanel } from "./StagePanel";
import { TaskEditor } from "./TaskEditor";
import { ProjectForm } from "./ProjectForm";
import { ActivityFeed } from "./ActivityFeed";
import { ReadError, SaveError, Status, type DirtyChange } from "./ui";
export function ProjectDetail({
  api,
  draftEpoch,
  id,
  initial,
  stageTarget,
  taskTarget,
  catalog,
  readOnly,
  onDirty,
  onChanged,
  onBack,
  onHandbook,
  onLegacy,
  requestLeave,
}: {
  api: Api;
  draftEpoch: number;
  id: string;
  initial?: ProjectDetailData;
  stageTarget?: string;
  taskTarget?: string;
  catalog: Catalog;
  readOnly: boolean;
  onDirty: DirtyChange;
  onChanged: () => void;
  onBack: () => void;
  onHandbook: (stage: string) => void;
  onLegacy: () => void;
  requestLeave: (action: () => void) => void;
}) {
  const [data, setData] = useState<ProjectDetailData | null>(initial || null),
    [stageId, setStageId] = useState(
      stageTarget || initial?.project.current_stage_id || "",
    ),
    [error, setError] = useState(""),
    [readError, setReadError] = useState(""),
    [editing, setEditing] = useState(false),
    [taskEdit, setTaskEdit] = useState<ProjectTask | "new" | null>(null),
    [busy, setBusy] = useState(false),
    [reload, setReload] = useState(0);
  const itemsElement = useRef<HTMLElement>(null);
  const active = useRef(true),
    readSequence = useRef(0),
    lock = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const readDetail = useCallback(async () => {
    // Initial, retry and independent post-save reads share one ordering.
    const sequence = ++readSequence.current;
    setReadError("");
    try {
      const d = await api.project(id);
      if (active.current && sequence === readSequence.current) {
        setData(d);
        setStageId((s) => s || d.project.current_stage_id || d.stages[0]?.id);
      }
    } catch (e) {
      if (active.current && sequence === readSequence.current)
        setReadError(message(e));
    }
  }, [api, id]);
  useEffect(() => {
    setError("");
    void readDetail();
    return () => {
      ++readSequence.current;
    };
  }, [readDetail, reload]);
  useEffect(() => {
    if (stageTarget) setStageId(stageTarget);
  }, [stageTarget]);
  useEffect(() => {
    if (!taskTarget || !data) return;
    const target = [
      ...(itemsElement.current?.querySelectorAll<HTMLElement>("[id]") || []),
    ].find((element) => element.id === `mf-task-${taskTarget}`);
    target?.scrollIntoView?.({ block: "center" });
  }, [taskTarget, stageId, data]);
  async function refreshed() {
    // The write has committed. A following GET failure must never turn it
    // back into an unsaved mutation or cause a new create operation.
    onChanged();
    await readDetail();
  }
  async function mutate(action: () => Promise<unknown>) {
    if (lock.current || readOnly) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await action();
      if (active.current) {
        if (result && typeof result === "object" && "project" in result) {
          ++readSequence.current;
          setData(result as ProjectDetailData);
        }
        await refreshed();
      }
    } catch (e) {
      if (active.current) setError(message(e));
    } finally {
      lock.current = false;
      if (active.current) setBusy(false);
    }
  }
  if (!data)
    return (
      <div>
        {readError ? (
          <ReadError
            error={readError}
            onRetry={() => setReload((x) => x + 1)}
          />
        ) : (
          <p role="status">正在读取项目…</p>
        )}
        <button onClick={onBack}>返回项目列表</button>
      </div>
    );
  const p = data.project,
    stage = data.stages.find((s) => s.id === stageId) || data.stages[0],
    tasks = data.tasks.filter((t) => t.stage_id === stage?.id);
  const disabled = readOnly || busy;
  return (
    <>
      <button className="mf-link" onClick={onBack}>
        返回项目列表
      </button>
      <div className="mf-detail-heading">
        <div>
          <div className="mf-eyebrow">
            {p.code} ·{" "}
            {catalog.groups.find((g) => g.id === p.group_id)?.name ||
              p.group_id}{" "}
            / {p.line_name}
          </div>
          <h2>{p.name}</h2>
          <p className="mf-meta">
            负责人 {p.owner} · 目标交期 {p.due_date || "未设日期"} ·{" "}
            {p.target_quantity ? `${p.target_quantity} 件` : "未设数量"}
          </p>
        </div>
        <div className="mf-actions">
          <Status value={p.status} text={projectStatus[p.status]} />
          <button disabled={disabled} onClick={() => setEditing(true)}>
            编辑项目资料
          </button>
          <button
            disabled={disabled}
            onClick={() =>
              requestLeave(
                () =>
                  void mutate(() =>
                    api.updateProject(id, {
                      expected_version: p.version,
                      archived: !p.archived,
                    }),
                  ),
              )
            }
          >
            {p.archived ? "恢复项目" : "归档项目"}
          </button>
        </div>
      </div>
      {readError && (
        <ReadError
          error={readError}
          retained
          onRetry={() => requestLeave(() => setReload((x) => x + 1))}
        />
      )}
      {error && (
        <SaveError
          error={error}
          onKeep={() => setError("")}
          onReload={() => requestLeave(() => setReload((x) => x + 1))}
        />
      )}
      {editing && (
        <ProjectForm
          key={`project-core-${draftEpoch}`}
          api={api}
          catalog={catalog}
          project={p}
          readOnly={disabled}
          onDirty={onDirty}
          onCancel={() => setEditing(false)}
          onSaved={(d) => {
            // A committed core aggregate also supersedes any pending GET.
            ++readSequence.current;
            setReadError("");
            setData(d);
            setEditing(false);
            onChanged();
          }}
          onReload={() =>
            requestLeave(() => {
              setEditing(false);
              setReload((x) => x + 1);
            })
          }
        />
      )}
      <nav className="mf-phase-rail" aria-label="项目阶段">
        {data.stages.map((s) => (
          <button
            key={s.id}
            aria-current={s.id === stage?.id ? "step" : undefined}
            className={`mf-phase mf-phase-${s.status}`}
            disabled={busy}
            onClick={() => {
              if (s.id !== stage?.id)
                requestLeave(() => {
                  setStageId(s.id);
                  setTaskEdit(null);
                });
            }}
          >
            <strong>{s.id}</strong>
            <span>{s.name}</span>
            <small>{workStatus[s.status]}</small>
          </button>
        ))}
      </nav>
      <div className="mf-detail-grid">
        <div>
          {stage && (
            <StagePanel
              key={`${stage.id}-${draftEpoch}`}
              api={api}
              projectId={id}
              stage={stage}
              readOnly={disabled}
              onDirty={onDirty}
              onSaved={refreshed}
              onHandbook={() => onHandbook(stage.id)}
              requestLeave={requestLeave}
            />
          )}
          <section className="mf-surface mf-items" ref={itemsElement}>
            <div className="mf-section-heading">
              <h3>
                阶段事项{" "}
                <small>
                  {tasks.filter((t) => t.status !== "done").length} 项未完成
                </small>
              </h3>
              <button
                disabled={disabled}
                onClick={() =>
                  taskEdit
                    ? requestLeave(() => setTaskEdit("new"))
                    : setTaskEdit("new")
                }
              >
                新建事项
              </button>
            </div>
            {taskEdit && (
              <TaskEditor
                key={`${draftEpoch}-${taskEdit === "new" ? "new" : taskEdit.id}`}
                api={api}
                projectId={id}
                stageId={stage?.id || ""}
                stages={data.stages}
                task={taskEdit === "new" ? undefined : taskEdit}
                readOnly={disabled}
                onDirty={onDirty}
                onSaved={refreshed}
                onCancel={() => setTaskEdit(null)}
                onReload={() =>
                  requestLeave(() => {
                    setTaskEdit(null);
                    setReload((x) => x + 1);
                  })
                }
              />
            )}
            {tasks.map((t) => (
              <article
                className={`mf-task ${taskTarget === t.id ? "mf-task-highlight" : ""}`}
                id={`mf-task-${t.id}`}
                key={t.id}
              >
                <div className="mf-task-title">
                  <span className="mf-eyebrow">
                    {kinds[t.kind]} · {priorities[t.priority]}
                  </span>
                  <strong>{t.title}</strong>
                  <small className="mf-muted">
                    {t.owner || "未分派"} · 目标 {t.due_date || "未设日期"}
                  </small>
                  {t.notes && <p className="mf-practice">{t.notes}</p>}
                </div>
                <div>
                  <Status value={t.status} text={workStatus[t.status]} />
                  <div className="mf-actions">
                    <button
                      disabled={disabled}
                      onClick={() =>
                        taskEdit
                          ? requestLeave(() => setTaskEdit(t))
                          : setTaskEdit(t)
                      }
                    >
                      编辑事项
                    </button>
                    <button
                      disabled={disabled}
                      onClick={() =>
                        requestLeave(
                          () =>
                            void mutate(() =>
                              api.updateProjectTask(id, t.id, {
                                expected_version: t.version,
                                status: t.status === "done" ? "todo" : "done",
                              }),
                            ),
                        )
                      }
                    >
                      {t.status === "done" ? "重新打开事项" : "完成事项"}
                    </button>
                  </div>
                </div>
              </article>
            ))}
            {!tasks.length && !taskEdit && (
              <p className="mf-muted">
                本阶段还没有事项。可登记待办、阻塞问题或需要确认的工作。
              </p>
            )}
          </section>
        </div>
        <aside className="mf-detail-context">
          <section className="mf-surface">
            <h3>交付资料</h3>
            <dl className="mf-facts">
              <dt>产品 / 型号</dt>
              <dd>{p.product || "未填写"}</dd>
              <dt>{p.group_id === "internal" ? "接收方" : "委托客户"}</dt>
              <dd>{p.customer || "未填写"}</dd>
              <dt>项目说明</dt>
              <dd className="mf-practice">{p.summary || "未填写"}</dd>
            </dl>
            <p className="mf-muted">
              {p.completed_stages}/{p.total_stages} 阶段已完成 · {p.open_tasks}{" "}
              项未完成
            </p>
            <button className="mf-link mf-small" onClick={onLegacy}>
              流程现状参考
            </button>
          </section>
          <section className="mf-surface">
            <ActivityFeed items={data.activity} />
          </section>
        </aside>
      </div>
    </>
  );
}
