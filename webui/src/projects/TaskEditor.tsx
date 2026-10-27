import { useEffect, useRef, useState } from "react";
import type { Api } from "../api";
import {
  kinds,
  priorities,
  workStatus,
  message,
  type ProjectTask,
  type ProjectTaskCreate,
  type ProjectStage,
  type TaskFields,
  type Kind,
  type Priority,
  type WorkStatus,
} from "./types";
import { Choice, SaveError, useDirty, type DirtyChange } from "./ui";
export function TaskEditor({
  api,
  projectId,
  stageId,
  stages,
  task,
  readOnly,
  onDirty,
  onSaved,
  onCancel,
  onReload,
}: {
  api: Api;
  projectId: string;
  stageId: string;
  stages: ProjectStage[];
  task?: ProjectTask;
  readOnly: boolean;
  onDirty: DirtyChange;
  onSaved: () => Promise<void>;
  onCancel: () => void;
  onReload: () => void;
}) {
  const initial: TaskFields = {
    stage_id: task?.stage_id || stageId,
    title: task?.title || "",
    kind: task?.kind || "task",
    owner: task?.owner || "",
    due_date: task?.due_date || null,
    priority: task?.priority || "normal",
    notes: task?.notes || "",
  };
  const [draft, setDraft] = useState(initial),
    [status, setStatus] = useState<WorkStatus>(task?.status || "todo"),
    [busy, setBusy] = useState(false),
    [frozen, setFrozen] = useState(false),
    [error, setError] = useState("");
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const operation = useRef<ProjectTaskCreate | null>(null),
    lock = useRef(false);
  useDirty(
    "task-editor",
    JSON.stringify(draft) !== JSON.stringify(initial) ||
      status !== (task?.status || "todo") ||
      !!operation.current ||
      busy,
    onDirty,
  );
  const update = (key: keyof TaskFields, value: string | null) =>
    setDraft({ ...draft, [key]: value });
  async function save() {
    if (lock.current || readOnly) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      if (task)
        await api.updateProjectTask(projectId, task.id, {
          ...draft,
          status,
          expected_version: task.version,
        });
      else {
        operation.current ??= { ...draft, operation_id: crypto.randomUUID() };
        setFrozen(true);
        await api.createProjectTask(projectId, operation.current);
      }
      operation.current = null;
      if (active.current) {
        await onSaved();
        if (active.current) onCancel();
      }
    } catch (e) {
      if (active.current) setError(message(e));
    } finally {
      lock.current = false;
      if (active.current) setBusy(false);
    }
  }
  return (
    <form
      className="mf-task-editor mf-editor"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <h3>{task ? "编辑事项" : "新建事项"}</h3>
      <fieldset disabled={busy || readOnly || frozen} className="mf-form-grid">
        <label className="mf-field mf-full-width">
          事项标题 *
          <input
            aria-label="事项标题"
            required
            maxLength={300}
            value={draft.title}
            onChange={(e) => update("title", e.target.value)}
          />
        </label>
        <Choice
          label="事项类型"
          value={draft.kind}
          values={kinds}
          onChange={(v) => update("kind", v as Kind)}
        />
        <Choice
          label="所属阶段"
          value={draft.stage_id}
          values={Object.fromEntries(
            stages.map((s) => [s.id, `${s.id} ${s.name}`]),
          )}
          onChange={(v) => update("stage_id", v)}
        />
        <label className="mf-field">
          事项负责人
          <input
            aria-label="事项负责人"
            maxLength={200}
            value={draft.owner}
            onChange={(e) => update("owner", e.target.value)}
          />
        </label>
        <label className="mf-field">
          目标日期
          <input
            aria-label="事项日期"
            type="date"
            value={draft.due_date || ""}
            onChange={(e) => update("due_date", e.target.value || null)}
          />
        </label>
        <Choice
          label="事项优先级"
          value={draft.priority}
          values={priorities}
          onChange={(v) => update("priority", v as Priority)}
        />
        {task && (
          <Choice
            label="事项状态"
            value={status}
            values={workStatus}
            onChange={(v) => setStatus(v as WorkStatus)}
          />
        )}
        <label className="mf-field mf-full-width">
          事项说明
          <textarea
            aria-label="事项说明"
            maxLength={6000}
            rows={3}
            value={draft.notes}
            onChange={(e) => update("notes", e.target.value)}
          />
        </label>
      </fieldset>
      <p className="mf-muted mf-small">
        负责人为业务责任登记；确认事项由人工登记处理结果。
      </p>
      {error && (
        <SaveError
          error={error}
          onKeep={() => setError("")}
          onReload={onReload}
        />
      )}
      {frozen && (
        <p className="mf-muted">
          本次创建已锁定，重试使用同一操作标识；修改内容请先取消本次创建。
        </p>
      )}
      <div className="mf-actions">
        <button
          type="submit"
          disabled={busy || readOnly || !draft.title.trim()}
          className="mf-primary"
        >
          {busy ? "正在保存…" : task ? "保存事项" : "创建事项"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            operation.current = null;
            onCancel();
          }}
        >
          {frozen ? "取消本次创建" : "取消事项编辑"}
        </button>
      </div>
    </form>
  );
}
