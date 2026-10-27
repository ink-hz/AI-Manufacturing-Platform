import { useState } from "react";
import type { Api } from "../api";
import type {
  EngineeringPackage,
  Handoff,
  PackageAction,
  HandoffAction,
  ReceiptAction,
} from "./types";
import { Field, MutationForm, type EditorHost } from "./ui";
import { packageActions, handoffActions } from "./labels";
export function PackageActionEditor({
  api,
  projectId,
  record,
  action,
  ...host
}: {
  api: Api;
  projectId: string;
  record: EngineeringPackage;
  action: PackageAction;
} & EditorHost) {
  const [d, set] = useState({ action, reason: "" });
  return (
    <>
      <h3>{packageActions[action]}</h3>
      <p className="mf-muted">
        {record.title} · 修订 {record.revision}
        。此操作为人工业务登记，保留原始记录。
      </p>
      <MutationForm
        {...host}
        draft={d}
        initial={{ action, reason: "" }}
        changed
        version={record.version}
        label="确认操作"
        write={(body) => api.packageAction(projectId, record.id, body)}
      >
        <Field
          label="操作原因"
          value={d.reason}
          required={["return", "invalidate"].includes(action)}
          onChange={(v) => set({ ...d, reason: v })}
        />
      </MutationForm>
    </>
  );
}
export function HandoffActionEditor({
  api,
  projectId,
  record,
  action,
  ...host
}: {
  api: Api;
  projectId: string;
  record: Handoff;
  action: HandoffAction;
} & EditorHost) {
  const [d, set] = useState<ReceiptAction>({
    action,
    received_revision: action === "receive" ? record.package_revision : null,
    evidence: "",
    occurred_at: null,
    reason: "",
  });
  const [local, setLocal] = useState("");
  return (
    <>
      <h3>{handoffActions[action]}</h3>
      <p>固定资料修订 {record.package_revision} · 仅登记人工交接事实</p>
      <MutationForm
        {...host}
        draft={d}
        initial={{ ...d, reason: "", evidence: "", occurred_at: null }}
        changed
        version={record.version}
        label="确认操作"
        write={(body) => api.handoffAction(projectId, record.id, body)}
      >
        {action === "receive" && (
          <Field
            label="接收版本"
            type="number"
            value={String(d.received_revision || "")}
            required
            onChange={(v) => set({ ...d, received_revision: Number(v) })}
          />
        )}
        <Field
          label="操作凭据"
          value={d.evidence}
          required={action === "send" || action === "receive"}
          onChange={(v) => set({ ...d, evidence: v })}
        />
        <Field
          label="业务发生时间"
          type="datetime-local"
          required={action === "send" || action === "receive"}
          value={local}
          onChange={(v) => {
            setLocal(v);
            set({ ...d, occurred_at: v ? new Date(v).toISOString() : null });
          }}
        />
        <p className="mf-muted">
          按本机时区填写，保存为带时区的时间；登记时间由服务器记录。
        </p>
        <Field
          label="操作原因"
          value={d.reason}
          required={action === "return"}
          onChange={(v) => set({ ...d, reason: v })}
        />
      </MutationForm>
    </>
  );
}
