import { useState } from "react";
import type { Api } from "../api";
import { Choice } from "../projects/ui";
import { priorities } from "../projects/types";
import type { Readiness, ReadinessItem, IssueFields } from "./types";
import { Field, MutationForm, type EditorHost } from "./ui";
export function IssueEditor({
  api,
  projectId,
  record,
  item,
  ...host
}: {
  api: Api;
  projectId: string;
  record: Readiness;
  item: ReadinessItem;
} & EditorHost) {
  const [initial] = useState<IssueFields>({
      item_id: item.id,
      title: "",
      owner: item.owner,
      due_date: item.due_date,
      priority: "normal",
      notes: "",
    }),
    [d, set] = useState(initial);
  return (
    <section className="mf-surface">
      <h3>登记关联问题 · {item.label}</h3>
      <p className="mf-muted">问题完成后仍需独立核对准备项。</p>
      <MutationForm
        {...host}
        dirtyKey="control-issue"
        draft={d}
        initial={initial}
        label="创建关联问题"
        write={(body) => api.createReadinessIssue(projectId, record.id, body)}
      >
        <Field
          label="问题标题"
          required
          maxLength={300}
          value={d.title}
          onChange={(v) => set({ ...d, title: v })}
        />
        <Field
          label="问题负责人"
          maxLength={200}
          value={d.owner}
          onChange={(v) => set({ ...d, owner: v })}
        />
        <Field
          label="问题目标日期"
          type="date"
          value={d.due_date}
          onChange={(v) => set({ ...d, due_date: v || null })}
        />
        <Choice
          label="问题优先级"
          value={d.priority}
          values={priorities}
          onChange={(v) =>
            set({ ...d, priority: v as IssueFields["priority"] })
          }
        />
        <Field
          label="问题说明"
          value={d.notes}
          onChange={(v) => set({ ...d, notes: v })}
        />
      </MutationForm>
    </section>
  );
}
