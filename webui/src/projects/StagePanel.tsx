import { useRef, useState } from "react";
import type { Api } from "../api";
import { RelationshipsEditor } from "../components/RelationshipsEditor";
import {
  workStatus,
  message,
  type ProjectStage,
  type StageFields,
  type WorkStatus,
} from "./types";
import { useDirty, SaveError, Choice, Status, type DirtyChange } from "./ui";
function fields(s: ProjectStage): StageFields {
  return {
    status: s.status,
    owner: s.owner,
    due_date: s.due_date,
    blocker: s.blocker,
    practice: s.practice,
    participants: s.participants,
    handoffs: s.handoffs,
    systems: s.systems,
  };
}
export function StagePanel({
  api,
  projectId,
  stage,
  readOnly,
  onDirty,
  onSaved,
  onHandbook,
  requestLeave,
}: {
  api: Api;
  projectId: string;
  stage: ProjectStage;
  readOnly: boolean;
  onDirty: DirtyChange;
  onSaved: () => Promise<void>;
  onHandbook: () => void;
  requestLeave: (action: () => void) => void;
}) {
  const [draft, setDraft] = useState(() => fields(stage)),
    [editing, setEditing] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const locked = useRef(false);
  const baseline = useRef(stage.version);
  const dirty =
    editing && JSON.stringify(draft) !== JSON.stringify(fields(stage));
  useDirty(`stage-${stage.id}`, dirty, onDirty);
  function edit() {
    setDraft(fields(stage));
    baseline.current = stage.version;
    setEditing(true);
    setError("");
    setNotice("");
  }
  async function save(value = draft) {
    if (locked.current || readOnly) return;
    locked.current = true;
    setBusy(true);
    setError("");
    setDraft(value);
    setEditing(true);
    try {
      await api.saveProjectStage(projectId, stage.id, {
        ...value,
        expected_version: baseline.current,
      });
      setEditing(false);
      setNotice("阶段已保存");
      await onSaved();
    } catch (e) {
      setError(message(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  function transition(status: WorkStatus) {
    baseline.current = stage.version;
    const next = {
      ...fields(stage),
      status,
      blocker: status === "blocked" ? stage.blocker : "",
    };
    setDraft(next);
    setNotice("");
    if (status === "blocked") {
      setEditing(true);
    } else void save(next);
  }
  return (
    <section className="mf-surface mf-stage-workspace">
      <div className="mf-section-heading">
        <div>
          <span className="mf-eyebrow">当前选择 · {stage.id}</span>
          <h2>{stage.name}</h2>
        </div>
        <button className="mf-link" onClick={onHandbook}>
          了解这个阶段
        </button>
      </div>
      <p className="mf-muted">{stage.purpose}</p>
      {!editing ? (
        <>
          <div className="mf-stage-meta">
            <Status value={stage.status} text={workStatus[stage.status]} />
            <span>负责人 {stage.owner || "未分派"}</span>
            <span>目标 {stage.due_date || "未设日期"}</span>
          </div>
          {stage.blocker && (
            <p className="mf-blocked-note">受阻原因：{stage.blocker}</p>
          )}
          <div className="mf-actions mf-stage-actions">
            <button disabled={readOnly || busy} onClick={edit}>
              编辑阶段
            </button>
            {stage.status === "todo" && (
              <button
                disabled={readOnly || busy}
                onClick={() => transition("doing")}
              >
                开始阶段
              </button>
            )}
            {stage.status !== "blocked" && stage.status !== "done" && (
              <button
                disabled={readOnly || busy}
                onClick={() => transition("blocked")}
              >
                标记受阻
              </button>
            )}
            {stage.status !== "done" ? (
              <button
                disabled={readOnly || busy}
                onClick={() => transition("done")}
              >
                完成阶段
              </button>
            ) : (
              <button
                disabled={readOnly || busy}
                onClick={() => transition("doing")}
              >
                重新打开阶段
              </button>
            )}
          </div>
          <p className="mf-practice">
            {stage.practice || "尚未记录推进说明。"}
          </p>
          <details className="mf-help">
            <summary>
              资料与协作 ·{" "}
              {stage.participants.length +
                stage.handoffs.length +
                stage.systems.length}{" "}
              条登记
            </summary>
            <RelationshipsEditor
              value={stage}
              editing={false}
              disabled={true}
              onChange={() => {}}
            />
          </details>
        </>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <fieldset disabled={readOnly || busy} className="mf-form-grid">
            <Choice
              label="阶段状态"
              value={draft.status}
              values={workStatus}
              onChange={(v) => setDraft({ ...draft, status: v as WorkStatus })}
            />
            <label className="mf-field">
              阶段负责人
              <input
                aria-label="阶段负责人"
                maxLength={200}
                value={draft.owner}
                onChange={(e) => setDraft({ ...draft, owner: e.target.value })}
              />
            </label>
            <label className="mf-field">
              阶段日期
              <input
                aria-label="阶段日期"
                type="date"
                value={draft.due_date || ""}
                onChange={(e) =>
                  setDraft({ ...draft, due_date: e.target.value || null })
                }
              />
            </label>
            <label className="mf-field mf-full-width">
              受阻原因{draft.status === "blocked" ? " *" : ""}
              <input
                aria-label="受阻原因"
                required={draft.status === "blocked"}
                maxLength={2000}
                value={draft.blocker}
                onChange={(e) =>
                  setDraft({ ...draft, blocker: e.target.value })
                }
              />
            </label>
            <label className="mf-field mf-full-width">
              推进说明
              <textarea
                aria-label="阶段说明"
                rows={4}
                maxLength={12000}
                value={draft.practice}
                onChange={(e) =>
                  setDraft({ ...draft, practice: e.target.value })
                }
              />
            </label>
          </fieldset>
          <details className="mf-help" open>
            <summary>资料与协作</summary>
            <RelationshipsEditor
              value={draft}
              editing
              disabled={readOnly || busy}
              onChange={(value) => setDraft({ ...draft, ...value })}
            />
          </details>
          <details className="mf-help">
            <summary>阶段参考（需核对后登记为项目事实）</summary>
            <p>{stage.help}</p>
            <ul>
              {stage.prompts.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
            <RelationshipsEditor
              value={{
                practice: "",
                participants: stage.reference_participants,
                handoffs: stage.reference_handoffs,
                systems: stage.reference_systems,
              }}
              editing={false}
              disabled
              onChange={() => {}}
            />
            <button
              type="button"
              disabled={readOnly || busy}
              onClick={() =>
                setDraft({
                  ...draft,
                  participants: structuredClone(stage.reference_participants),
                  handoffs: structuredClone(stage.reference_handoffs),
                  systems: structuredClone(stage.reference_systems),
                })
              }
            >
              采用参考关系并核对
            </button>
          </details>
          {error && (
            <SaveError
              error={error}
              onKeep={() => setError("")}
              onReload={() =>
                requestLeave(() => {
                  setEditing(false);
                  setError("");
                  void onSaved();
                })
              }
            />
          )}
          <div className="mf-actions mf-save-bar">
            <button
              type="submit"
              className="mf-primary"
              disabled={
                readOnly ||
                busy ||
                (draft.status === "blocked" && !draft.blocker.trim())
              }
            >
              {busy ? "正在保存…" : "保存阶段"}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setEditing(false);
                setError("");
              }}
            >
              取消阶段编辑
            </button>
          </div>
        </form>
      )}
      {notice && (
        <p className="mf-muted" role="status">
          {notice}
        </p>
      )}
      <p className="mf-muted mf-small">
        阶段由负责人明确推进，可并行开展；完成事项不会自动完成阶段。
      </p>
    </section>
  );
}
