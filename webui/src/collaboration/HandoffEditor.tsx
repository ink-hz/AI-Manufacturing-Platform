import { SystemPicker } from "./SystemPicker";
import { useState } from "react";
import type { Api } from "../api";
import { Choice } from "../projects/ui";
import type {
  EngineeringPackage,
  Handoff,
  HandoffFields,
  HandoffAction,
} from "./types";
import { Field, Evidence, MutationForm, type EditorHost } from "./ui";
import { methods, handoffStates, handoffActions } from "./labels";
import { HandoffActionEditor } from "./ActionEditor";
export function HandoffEditor({
  api,
  projectId,
  packages,
  record,
  ...host
}: {
  api: Api;
  projectId: string;
  packages: EngineeringPackage[];
  record?: Handoff;
} & EditorHost) {
  const verified = packages.filter((p) => p.status === "verified");
  const [initial] = useState<HandoffFields>({
    package_id: verified[0]?.id || "",
    from_party: "",
    to_party: "",
    to_system_id: null,
    owner: "",
    due_date: null,
    method: "manual",
    evidence: "",
    occurred_at: null,
  });
  const [d, set] = useState(initial),
    [action, setAction] = useState<HandoffAction | null>(null);
  const update = <K extends keyof HandoffFields>(k: K, v: HandoffFields[K]) =>
    set({ ...d, [k]: v });
  if (record && action)
    return (
      <HandoffActionEditor
        {...host}
        api={api}
        projectId={projectId}
        record={record}
        action={action}
      />
    );
  if (record) {
    const allowed: HandoffAction[] =
      record.status === "draft"
        ? ["send", "cancel"]
        : record.status === "sent"
          ? ["receive", "return", "cancel"]
          : [];
    return (
      <>
        <h3>
          {record.from_party} → {record.to_party}
        </h3>
        <p>
          {record.code} · {handoffStates[record.status]} · 固定修订{" "}
          {record.package_revision}
        </p>
        <dl className="mf-facts">
          <dt>资料包</dt>
          <dd>
            {packages.find((p) => p.id === record.package_id)?.title ||
              record.package_id}
          </dd>
          <dt>负责人 / 目标日</dt>
          <dd>
            {record.owner} / {record.due_date || "未设日期"}
          </dd>
          <dt>传递方式</dt>
          <dd>{methods[record.method]}</dd>
          <dt>业务发生时间</dt>
          <dd>{record.occurred_at || "未登记"}</dd>
          <dt>登记时间</dt>
          <dd>{record.updated_at || "未登记"}</dd>
          <dt>凭据</dt>
          <dd>
            <Evidence value={record.evidence} />
          </dd>
          <dt>原因</dt>
          <dd>{record.reason || "未登记"}</dd>
        </dl>
        <p className="mf-muted">
          交接状态为人工事实登记，不代表外部系统已入账。退回后请建立新的独立交接。
        </p>
        <div className="mf-actions">
          {allowed.map((a) => (
            <button
              key={a}
              disabled={host.readOnly}
              onClick={() => setAction(a)}
            >
              {handoffActions[a]}
            </button>
          ))}
          <button onClick={host.onCancel}>返回列表</button>
        </div>
      </>
    );
  }
  return (
    <>
      <h3>新建交接</h3>
      <p className="mf-muted">
        每个接收方分别建立记录，绑定已人工核对的固定资料修订。
      </p>
      {!verified.length ? (
        <>
          <p>尚无可交接的冻结资料包，请先完成人工核对。</p>
          <button onClick={host.onCancel}>返回列表</button>
        </>
      ) : (
        <MutationForm
          {...host}
          draft={d}
          initial={initial}
          label="登记交接"
          write={(body) => api.createHandoff(projectId, body)}
        >
          <Choice
            label="固定资料修订"
            value={d.package_id}
            values={Object.fromEntries(
              verified.map((p) => [p.id, `${p.title} · 修订 ${p.revision}`]),
            )}
            onChange={(v) => update("package_id", v)}
          />
          <Field
            label="交出方"
            required
            maxLength={300}
            value={d.from_party}
            onChange={(v) => update("from_party", v)}
          />
          <Field
            label="接收方"
            required
            maxLength={300}
            value={d.to_party}
            onChange={(v) => update("to_party", v)}
          />
          <Field
            label="交接负责人"
            required
            maxLength={300}
            value={d.owner}
            onChange={(v) => update("owner", v)}
          />
          <SystemPicker
            api={api}
            label="接收系统（可选）"
            value={d.to_system_id}
            onChange={(v) => update("to_system_id", v || null)}
          />
          <Field
            label="交接目标日期"
            type="date"
            value={d.due_date}
            onChange={(v) => update("due_date", v || null)}
          />
          <Choice
            label="交接方式"
            value={d.method}
            values={methods}
            onChange={(v) => update("method", v as HandoffFields["method"])}
          />
          <Field
            label="交接凭据"
            value={d.evidence}
            onChange={(v) => update("evidence", v)}
          />
        </MutationForm>
      )}
    </>
  );
}
