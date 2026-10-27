import { useEffect, useRef, useState } from "react";
import { ApiError, type Api } from "../api";
import type {
  RecordContent,
  StageRecord,
  StageResponse,
  Task,
  TaskCreate,
} from "../types";
import { RelationshipsEditor } from "./RelationshipsEditor";
const content = (record: StageRecord): RecordContent => ({
  practice: record.practice,
  participants: record.participants,
  handoffs: record.handoffs,
  systems: record.systems,
});
export function StageWorkspace({
  api,
  lineId,
  stageId,
  groupName,
  readOnly,
  onBack,
  onDirtyChange,
}: {
  api: Api;
  lineId: string;
  stageId: string;
  groupName: string;
  readOnly: boolean;
  onBack: () => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [data, setData] = useState<StageResponse | null>(null),
    [readError, setReadError] = useState(false),
    [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState<RecordContent | null>(null),
    [editing, setEditing] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [newTitle, setNewTitle] = useState(""),
    [taskEdit, setTaskEdit] = useState<{
      task: Task;
      title: string;
      completed: boolean;
    } | null>(null);
  const [dialog, setDialog] = useState<"leave" | "reload" | "conflict" | null>(
    null,
  );
  const dialogElement = useRef<HTMLDivElement>(null);
  const operation = useRef<TaskCreate | null>(null),
    readSequence = useRef(0),
    lock = useRef(false),
    active = useRef(true);
  const recordDirty =
    !!data &&
    !!draft &&
    JSON.stringify(draft) !== JSON.stringify(content(data.record));
  const dirty = recordDirty || !!newTitle || !!taskEdit || busy;
  const writable = !!data?.can_edit && !readOnly && !loading;
  useEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (!dialog) return;
    const previous = document.activeElement as HTMLElement | null;
    const panel = dialogElement.current;
    panel?.querySelector<HTMLButtonElement>("button")?.focus();
    const handle = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        if (!lock.current) setDialog(null);
        return;
      }
      if (event.key !== "Tab" || !panel) return;
      const buttons = [
        ...panel.querySelectorAll<HTMLButtonElement>("button:not(:disabled)"),
      ];
      const first = buttons[0],
        last = buttons.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", handle);
    return () => {
      document.removeEventListener("keydown", handle);
      if (previous?.isConnected) previous.focus();
    };
  }, [dialog]);
  async function load() {
    const sequence = ++readSequence.current;
    setLoading(true);
    setReadError(false);
    try {
      const next = await api.stage(lineId, stageId);
      if (!active.current || sequence !== readSequence.current) return;
      setData(next);
      setDraft(content(next.record));
      setEditing(false);
      setNewTitle("");
      setTaskEdit(null);
      operation.current = null;
      setError("");
      setDialog(null);
    } catch {
      if (active.current && sequence === readSequence.current)
        setReadError(true);
    } finally {
      if (active.current && sequence === readSequence.current)
        setLoading(false);
    }
  }
  useEffect(() => {
    active.current = true;
    void load();
    return () => {
      active.current = false;
      readSequence.current++;
    };
  }, [api, lineId, stageId]);
  function failed(error: unknown) {
    setNotice("");
    setError(
      error instanceof ApiError && error.status === 409
        ? "内容已更新，本地编辑尚未保存。"
        : "操作失败，编辑尚未保存，请重试。",
    );
    if (error instanceof ApiError && error.status === 409)
      setDialog("conflict");
  }
  async function perform(action: () => Promise<void>, success = "待办已保存") {
    if (lock.current || !writable) return false;
    lock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      if (active.current) setNotice(success);
      return true;
    } catch (e) {
      if (active.current) failed(e);
      return false;
    } finally {
      lock.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function saveRecord() {
    if (!data || !draft) return false;
    const invalid = [
      ...draft.participants,
      ...draft.handoffs,
      ...draft.systems,
    ].some((row) => !row.name.trim());
    if (invalid) {
      setError("请填写关系名称；编辑尚未保存。");
      return false;
    }
    return perform(async () => {
      const record = await api.saveRecord(lineId, stageId, {
        ...draft,
        expected_version: data.record.version,
      });
      if (active.current) {
        setData((current) => (current ? { ...current, record } : current));
        setDraft(content(record));
        setEditing(false);
      }
    }, "现状与关系已保存");
  }
  async function addTask() {
    if (!newTitle.trim()) return false;
    if (!operation.current || operation.current.title !== newTitle.trim())
      operation.current = {
        title: newTitle.trim(),
        operation_id: crypto.randomUUID(),
      };
    const pending = operation.current;
    return perform(async () => {
      const task = await api.createTask(lineId, stageId, pending);
      if (active.current) {
        setData((current) =>
          current
            ? {
                ...current,
                tasks: [...current.tasks.filter((t) => t.id !== task.id), task],
              }
            : current,
        );
        setNewTitle("");
        operation.current = null;
      }
    });
  }
  async function updateTask(edit: NonNullable<typeof taskEdit>) {
    if (!edit.title.trim()) return false;
    return perform(async () => {
      const task = await api.updateTask(lineId, stageId, edit.task.id, {
        title: edit.title.trim(),
        completed: edit.completed,
        expected_version: edit.task.version,
      });
      if (active.current) {
        setData((current) =>
          current
            ? {
                ...current,
                tasks: current.tasks.map((t) => (t.id === task.id ? task : t)),
              }
            : current,
        );
        setTaskEdit(null);
      }
    });
  }
  async function saveAndLeave() {
    if (recordDirty && !(await saveRecord())) return;
    if (newTitle.trim() && !(await addTask())) return;
    if (taskEdit && !(await updateTask(taskEdit))) return;
    onBack();
  }
  function taskRow(task: Task) {
    return (
      <li key={task.id} className="mf-task">
        <span className="mf-task-title">{task.title}</span>
        <div className="mf-actions">
          <button
            disabled={!writable || busy || !!taskEdit}
            onClick={() => {
              const edit = {
                task,
                title: task.title,
                completed: !task.completed,
              };
              setTaskEdit(edit);
              void updateTask(edit);
            }}
          >
            {task.completed ? "重新打开" : "标记完成"}
          </button>
          <button
            disabled={!writable || busy || !!taskEdit}
            onClick={() =>
              setTaskEdit({
                task,
                title: task.title,
                completed: task.completed,
              })
            }
          >
            修改待办
          </button>
        </div>
      </li>
    );
  }
  return (
    <div className="mf-workspace" aria-busy={loading || busy}>
      <div className="mf-toolbar">
        <button
          className="mf-link"
          disabled={busy}
          onClick={() => (dirty ? setDialog("leave") : onBack())}
        >
          ← 返回流程
        </button>
        <button
          disabled={busy || loading}
          onClick={() => (dirty ? setDialog("reload") : void load())}
        >
          重新读取
        </button>
      </div>
      {loading && <p role="status">正在读取…</p>}
      {readError && (
        <div role="alert" className="mf-error">
          读取失败。
          {data ? "保留上次读取的内容及更新时间。" : "尚未取得业务记录。"}{" "}
          <button onClick={() => void load()}>重试读取</button>
        </div>
      )}
      {data && draft && (
        <>
          <p className="mf-breadcrumb">
            {groupName} / {data.line.name}
            {data.line.description ? `（${data.line.description}）` : ""}
          </p>
          <h2>{data.stage.name}</h2>
          <p className="mf-purpose">{data.stage.purpose}</p>
          <details className="mf-help">
            <summary>了解这一步</summary>
            <p>{data.stage.help}</p>
            <ul>
              {data.stage.prompts.map((prompt) => (
                <li key={prompt}>{prompt}</li>
              ))}
            </ul>
            <h3>参考分工 · 尚待核实</h3>
            <p className="mf-muted">以下为调研参考，不是已保存的实际关系。</p>
            {data.stage.reference_participants.map((p, i) => (
              <p key={`p${i}`}>
                {p.name} · {p.role} · {p.responsibility}
              </p>
            ))}
            {data.stage.reference_handoffs.map((h, i) => (
              <p key={`h${i}`}>
                {h.name}：{h.from_party} → {h.to_party}；{h.version_reference}；
                {h.notes}
              </p>
            ))}
            {data.stage.reference_systems.map((s, i) => (
              <p key={`s${i}`}>
                {s.name} · {s.kind} · {s.objects} · {s.notes}
              </p>
            ))}
          </details>
          {!writable && (
            <p className="mf-muted">当前为只读，可查看已保存的现状和待办。</p>
          )}
          <div role="status" aria-live="polite">
            {busy ? "正在保存…" : notice}
          </div>
          {error && (
            <p className="mf-error" role="alert">
              {error}
            </p>
          )}
          <section className="mf-panel">
            <div className="mf-section-heading">
              <h3>我们现在怎么做</h3>
              {!editing && (
                <button
                  disabled={!writable || busy}
                  onClick={() => {
                    setEditing(true);
                    setNotice("");
                  }}
                >
                  编辑
                </button>
              )}
            </div>
            {editing ? (
              <>
                <label className="mf-field">
                  现状说明
                  <textarea
                    aria-label="现状说明"
                    value={draft.practice}
                    maxLength={12000}
                    rows={7}
                    disabled={busy || !writable}
                    placeholder={data.stage.prompts.join(" ")}
                    onChange={(e) =>
                      setDraft({ ...draft, practice: e.target.value })
                    }
                  />
                </label>
                <p className="mf-muted">
                  {data.stage.prompts.join(" ")} 现状与下方关系会一起保存。
                </p>
                <div className="mf-actions">
                  <button
                    className="mf-primary"
                    disabled={busy || !writable}
                    onClick={() => void saveRecord()}
                  >
                    保存
                  </button>
                  <button
                    disabled={busy}
                    onClick={() => {
                      setDraft(content(data.record));
                      setEditing(false);
                      setError("");
                      setNotice("");
                    }}
                  >
                    取消
                  </button>
                </div>
              </>
            ) : (
              <p className="mf-practice">
                {data.record.practice || "尚未记录，先补充已了解的情况。"}
              </p>
            )}
            {data.record.updated_at && (
              <p className="mf-meta">
                {data.record.updated_by} ·{" "}
                {new Date(data.record.updated_at).toLocaleString("zh-CN")}
              </p>
            )}
          </section>
          <section className="mf-panel">
            <h3>待办</h3>
            <form
              className="mf-task-form"
              onSubmit={(e) => {
                e.preventDefault();
                void addTask();
              }}
            >
              <label className="mf-field">
                新待办
                <input
                  aria-label="新待办"
                  maxLength={300}
                  value={newTitle}
                  disabled={!writable || busy}
                  onChange={(e) => setNewTitle(e.target.value)}
                  placeholder="下一步需要确认什么？"
                />
              </label>
              <button disabled={!writable || busy || !newTitle.trim()}>
                添加待办
              </button>
            </form>
            {taskEdit && (
              <form
                className="mf-task-edit"
                onSubmit={(e) => {
                  e.preventDefault();
                  void updateTask(taskEdit);
                }}
              >
                <label className="mf-field">
                  待办标题
                  <input
                    aria-label="待办标题"
                    maxLength={300}
                    value={taskEdit.title}
                    disabled={busy || !writable}
                    onChange={(e) =>
                      setTaskEdit({ ...taskEdit, title: e.target.value })
                    }
                  />
                </label>
                <div className="mf-actions">
                  <button
                    disabled={busy || !writable || !taskEdit.title.trim()}
                  >
                    保存待办
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => setTaskEdit(null)}
                  >
                    取消修改
                  </button>
                </div>
              </form>
            )}
            {!data.tasks.some((t) => !t.completed) && (
              <p className="mf-muted">目前没有待办。</p>
            )}
            <ul className="mf-task-list">
              {data.tasks.filter((t) => !t.completed).map(taskRow)}
            </ul>
            <details>
              <summary>
                已完成（{data.tasks.filter((t) => t.completed).length}）
              </summary>
              <ul className="mf-task-list">
                {data.tasks.filter((t) => t.completed).map(taskRow)}
              </ul>
            </details>
          </section>
          <details className="mf-panel" data-section="relationships">
            <summary>协作与数据关系</summary>
            <p className="mf-muted">
              实际登记 ·{" "}
              {editing
                ? "草稿尚未保存，将与现状一起保存。"
                : "以下为已保存的关系；未登记不代表没有参与方。"}
            </p>
            {!editing && (
              <button
                disabled={!writable || busy}
                onClick={() => setEditing(true)}
              >
                编辑关系
              </button>
            )}
            <RelationshipsEditor
              value={editing ? draft : content(data.record)}
              editing={editing}
              disabled={busy || !writable}
              onChange={setDraft}
            />
            {editing && (
              <div className="mf-actions">
                <button
                  disabled={busy || !writable}
                  onClick={() => void saveRecord()}
                >
                  保存现状与关系
                </button>
              </div>
            )}
          </details>
        </>
      )}
      {dialog && (
        <div className="mf-dialog-backdrop">
          <div
            ref={dialogElement}
            className="mf-dialog"
            role="dialog"
            aria-modal="true"
            aria-label={
              dialog === "leave" ? "离开未保存的编辑" : "重新读取确认"
            }
          >
            <h3>
              {dialog === "leave"
                ? "有尚未保存的编辑"
                : dialog === "conflict"
                  ? "内容已更新"
                  : "重新读取会放弃草稿"}
            </h3>
            <p>
              {dialog === "conflict"
                ? "本地草稿已保留。可继续核对，或明确放弃草稿后读取最新记录。"
                : "未保存的现状、关系与待办草稿会在离开或重新读取后丢弃。"}
            </p>
            <div className="mf-actions">
              {dialog === "leave" ? (
                <>
                  <button disabled={busy} onClick={() => setDialog(null)}>
                    继续编辑
                  </button>
                  <button
                    disabled={busy}
                    onClick={() => {
                      setDialog(null);
                      onBack();
                    }}
                  >
                    放弃并离开
                  </button>
                  <button
                    disabled={busy || !writable}
                    onClick={() => void saveAndLeave()}
                  >
                    保存并返回
                  </button>
                </>
              ) : (
                <>
                  <button disabled={busy} onClick={() => setDialog(null)}>
                    保留草稿
                  </button>
                  <button disabled={busy} onClick={() => void load()}>
                    放弃草稿并重新读取
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
