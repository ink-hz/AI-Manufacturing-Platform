import { PackageItemFields } from "./PackageItemFields";
import { useState } from "react";
import type { Api } from "../api";
import { Choice } from "../projects/ui";
import { Field, MutationForm, type EditorHost } from "./ui";
import { packageActions, packageStates } from "./labels";
import type {
  EngineeringPackage,
  PackageFields,
  PackageItem,
  PackageAction,
} from "./types";
import { PackageActionEditor } from "./ActionEditor";
export const newPackageItem = (): PackageItem => ({
  id: crypto.randomUUID(),
  kind: "mbom",
  title: "",
  source_system_id: null,
  source_name: "",
  source_ref: "",
  revision: "",
  evidence: "",
  owner: "",
  status: "pending",
  reason: "",
});
const content = (p?: EngineeringPackage): PackageFields => ({
  title: p?.title || "",
  product_ref: p?.product_ref || "",
  scope: p?.scope || "",
  provider: p?.provider || "",
  owner: p?.owner || "",
  customer_version: p?.customer_version || "",
  internal_version: p?.internal_version || "",
  approval_party: p?.approval_party || "",
  approval_status: p?.approval_status || "unknown",
  approval_evidence: p?.approval_evidence || "",
  items: p?.items.map((i) => ({ ...i })) || [newPackageItem()],
});
export function PackageEditor({
  api,
  projectId,
  record,
  actionTarget,
  onAction,
  ...host
}: {
  api: Api;
  projectId: string;
  record?: EngineeringPackage;
  actionTarget?: PackageAction;
  onAction?: (action: PackageAction) => void;
} & EditorHost) {
  const [initial] = useState(() => content(record));
  const [d, set] = useState(initial),
    [tab, setTab] = useState("basics"),
    [item, setItem] = useState(0),
    [action, setAction] = useState<PackageAction | null>(actionTarget || null);
  const frozen = !!record && !["draft", "returned"].includes(record.status);
  const update = <K extends keyof PackageFields>(k: K, v: PackageFields[K]) =>
    set({ ...d, [k]: v });
  const updateItem = (patch: Partial<PackageItem>) =>
    update(
      "items",
      d.items.map((i, n) => (n === item ? { ...i, ...patch } : i)),
    );
  const allowed: PackageAction[] =
    record?.status === "draft" || record?.status === "returned"
      ? ["submit"]
      : record?.status === "review"
        ? ["verify", "return"]
        : record?.status === "verified"
          ? ["revise", "invalidate"]
          : record?.status === "invalid"
            ? ["revise"]
            : [];
  if (record && action)
    return (
      <PackageActionEditor
        {...host}
        api={api}
        projectId={projectId}
        record={record}
        action={action}
      />
    );
  const current = d.items[item];
  return (
    <>
      <div className="mf-section-heading">
        <div>
          <h3>{record ? record.title : "新建资料包"}</h3>
          {record && (
            <p className="mf-meta">
              修订 {record.revision} · {packageStates[record.status]} ·{" "}
              {record.updated_by || "人工登记"}
            </p>
          )}
        </div>
        {record && (
          <div className="mf-actions">
            {allowed.map((a) => (
              <button
                key={a}
                disabled={host.readOnly}
                onClick={() =>
                  onAction
                    ? onAction(a)
                    : host.requestLeave
                      ? host.requestLeave(() => setAction(a))
                      : setAction(a)
                }
              >
                {packageActions[a]}
              </button>
            ))}
          </div>
        )}
      </div>
      {record?.supersedes_id && (
        <p className="mf-muted">本修订延续历史资料包：{record.supersedes_id}</p>
      )}
      {record?.reason && <p>{record.reason}</p>}
      <nav className="mf-subnav" aria-label="资料包编辑步骤">
        {[
          ["basics", "基本资料"],
          ["items", "资料项目"],
          ["approval", "版本与外部确认"],
        ].map(([id, label]) => (
          <button
            key={id}
            aria-current={tab === id ? "page" : undefined}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </nav>
      <MutationForm
        {...host}
        readOnly={host.readOnly || frozen}
        draft={d}
        initial={initial}
        version={record?.version}
        label="保存资料包"
        write={(body) =>
          record
            ? api.savePackage(projectId, record.id, body)
            : api.createPackage(projectId, body)
        }
      >
        {tab === "basics" ? (
          <>
            <Field
              label="资料包名称"
              required
              maxLength={300}
              value={d.title}
              onChange={(v) => update("title", v)}
            />
            <Field
              label="产品型号"
              value={d.product_ref}
              onChange={(v) => update("product_ref", v)}
            />
            <Field
              label="适用范围"
              value={d.scope}
              onChange={(v) => update("scope", v)}
            />
            <Field
              label="资料提供方"
              value={d.provider}
              onChange={(v) => update("provider", v)}
            />
            <Field
              label="资料负责人"
              value={d.owner}
              onChange={(v) => update("owner", v)}
            />
            <p className="mf-muted">
              保存草稿后，逐项核对来源、修订和凭据，再提交人工核对。
            </p>
          </>
        ) : tab === "approval" ? (
          <>
            <Field
              label="客户版本"
              value={d.customer_version}
              onChange={(v) => update("customer_version", v)}
            />
            <Field
              label="内部版本"
              value={d.internal_version}
              onChange={(v) => update("internal_version", v)}
            />
            <Field
              label="外部确认责任方"
              value={d.approval_party}
              onChange={(v) => update("approval_party", v)}
            />
            <Choice
              label="外部确认情况"
              value={d.approval_status}
              values={{
                unknown: "尚未核实",
                confirmed: "有外部确认凭据",
                not_required: "不需要外部确认",
              }}
              onChange={(v) =>
                update("approval_status", v as PackageFields["approval_status"])
              }
            />
            <Field
              label="外部确认凭据"
              value={d.approval_evidence}
              onChange={(v) => update("approval_evidence", v)}
            />
            <p className="mf-muted">
              人工核对不代表客户批准；未知的外部确认保持未知。
            </p>
          </>
        ) : (
          <>
            <div className="mf-full-width mf-item-tabs">
              {d.items.map((i, n) => (
                <button
                  type="button"
                  key={i.id}
                  aria-current={item === n ? "page" : undefined}
                  onClick={() => setItem(n)}
                >
                  {i.title || `资料 ${n + 1}`}
                </button>
              ))}
              <button
                type="button"
                onClick={() => {
                  update("items", [...d.items, newPackageItem()]);
                  setItem(d.items.length);
                }}
              >
                添加资料项
              </button>
            </div>
            {current && (
              <>
                <PackageItemFields
                  api={api}
                  current={current}
                  updateItem={updateItem}
                />
                {d.items.length > 1 && (
                  <button
                    type="button"
                    onClick={() => {
                      update(
                        "items",
                        d.items.filter((_, n) => n !== item),
                      );
                      setItem(0);
                    }}
                  >
                    移除此草稿资料项
                  </button>
                )}
              </>
            )}
          </>
        )}
      </MutationForm>
      {frozen && (
        <p className="mf-muted">
          本记录内容已冻结。建立新修订保留旧凭据与历史引用。
        </p>
      )}
    </>
  );
}
