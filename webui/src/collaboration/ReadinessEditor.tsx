import { SystemPicker } from "./SystemPicker";
import { useState } from "react";
import type { Api } from "../api";
import { Choice } from "../projects/ui";
import { ReadinessCreate } from "./ReadinessCreate";
import { IssueEditor } from "./ReadinessIssue";
import type { EngineeringPackage, Readiness, ReadinessItem } from "./types";
import { Field, Evidence, MutationForm, type EditorHost } from "./ui";
import { assertions, readinessKinds, readinessStates } from "./labels";
export function ReadinessEditor({
  api,
  projectId,
  packages,
  record,
  targetItem,
  replacement = false,
  onReplace,
  ...host
}: {
  api: Api;
  projectId: string;
  packages: EngineeringPackage[];
  record?: Readiness;
  targetItem?: string | null;
  replacement?: boolean;
  onReplace?: () => void;
} & EditorHost) {
  const [replace, setReplace] = useState(replacement),
    [selected, setSelected] = useState(
      targetItem || record?.items[0]?.id || "",
    ),
    [issue, setIssue] = useState(false);
  const [initial] = useState(() => record?.items.map((i) => ({ ...i })) || []),
    [items, setItems] = useState(initial);
  const current = items.find((i) => i.id === selected);
  const historical = !!record?.superseded_by;
  if (!record || replace)
    return (
      <ReadinessCreate
        key={replace ? "replacement" : "new"}
        {...host}
        api={api}
        projectId={projectId}
        packages={packages}
        old={replace ? record : undefined}
      />
    );
  const update = (patch: Partial<ReadinessItem>) =>
    setItems(items.map((i) => (i.id === selected ? { ...i, ...patch } : i)));
  return (
    <>
      <div className="mf-section-heading">
        <div>
          <h3>{record.title}</h3>
          <p className="mf-meta">
            {historical
              ? "已被替代 / 历史记录"
              : readinessStates[record.status]}{" "}
            · 资料修订 {record.package_revision}
          </p>
        </div>
        {!historical && (
          <button
            disabled={host.readOnly}
            onClick={() =>
              onReplace
                ? onReplace()
                : host.requestLeave
                  ? host.requestLeave(() => setReplace(true))
                  : setReplace(true)
            }
          >
            替代此核对
          </button>
        )}
      </div>
      <dl className="mf-facts mf-control-scope">
        <dt>固定执行范围</dt>
        <dd>
          {record.work_order_ref} / {record.scope}
        </dd>
        <dt>计划使用日期</dt>
        <dd>{record.planned_use_date}</dd>
        <dt>负责人 / 适用性</dt>
        <dd>
          {record.owner} / {record.required ? "必需准备核对" : "补充准备核对"}
        </dd>
      </dl>
      {historical && (
        <p className="mf-muted">
          已被新记录 {record.superseded_by}{" "}
          替代。旧结论、凭据与关联问题保留，只读查看。
        </p>
      )}
      {record.supersedes_id && (
        <p className="mf-muted">
          替代历史记录 {record.supersedes_id}；本次各项需独立重新核对。
        </p>
      )}
      <nav className="mf-item-tabs" aria-label="准备核对项目" hidden={issue}>
        {items.map((i) => (
          <button
            key={i.id}
            onClick={() => setSelected(i.id)}
            aria-current={selected === i.id ? "page" : undefined}
          >
            {i.label}
          </button>
        ))}
      </nav>
      {current && (
        <>
          {issue ? (
            <IssueEditor
              {...host}
              api={api}
              projectId={projectId}
              record={record}
              item={current}
              onCancel={() => setIssue(false)}
            />
          ) : null}
          <div hidden={issue}>
            <MutationForm
              {...host}
              readOnly={host.readOnly || historical}
              draft={{ items }}
              initial={{ items: initial }}
              version={record.version}
              label="保存核对"
              write={(body) => api.saveReadiness(projectId, record.id, body)}
            >
              <p className="mf-full-width mf-muted">
                {readinessKinds[current.kind]} ·{" "}
                {current.required ? "必需项" : "补充项"}
                ；保存只登记人工证据结论，不自动完成关联事项。
              </p>
              <Choice
                label="核对状态"
                value={current.status}
                values={assertions}
                onChange={(v) =>
                  update({ status: v as ReadinessItem["status"] })
                }
              />
              <Field
                label="检查负责人"
                value={current.owner}
                onChange={(v) => update({ owner: v })}
              />
              <Field
                label="检查目标日期"
                type="date"
                value={current.due_date}
                onChange={(v) => update({ due_date: v || null })}
              />
              <Field
                label="核对凭据"
                value={current.evidence}
                onChange={(v) => update({ evidence: v })}
              />
              <Field
                label="核对来源"
                value={current.source_ref}
                onChange={(v) => update({ source_ref: v })}
              />
              <SystemPicker
                api={api}
                label="核对来源系统（可选）"
                value={current.source_system_id}
                onChange={(v) => update({ source_system_id: v || null })}
              />
              <Field
                label="核对原因"
                value={current.reason}
                onChange={(v) => update({ reason: v })}
              />
              {current.kind === "version" && (
                <p className="mf-field">
                  固定资料项：
                  {packages
                    .find((p) => p.id === record.package_id)
                    ?.items.find((i) => i.id === current.package_item_id)
                    ?.title ||
                    current.package_item_id ||
                    "未绑定适用资料项"}
                  （建立时已固定）
                </p>
              )}
              {current.kind === "equipment" && (
                <Field
                  label="设备有效期至"
                  type="date"
                  value={current.valid_until}
                  onChange={(v) => update({ valid_until: v || null })}
                />
              )}{" "}
              {["materials", "customer_material"].includes(current.kind) && (
                <Choice
                  label="供料责任"
                  value={current.supply_mode}
                  values={{
                    unknown: "待核实",
                    self: "自购",
                    customer: "客供",
                    mixed: "混合供料",
                  }}
                  onChange={(v) =>
                    update({ supply_mode: v as ReadinessItem["supply_mode"] })
                  }
                />
              )}{" "}
              {current.kind === "first_article" && (
                <Choice
                  label="首件实际结果"
                  value={current.first_article_result}
                  values={{
                    unknown: "尚未核实",
                    planned: "计划中",
                    passed: "实际通过",
                    failed: "实际未通过",
                    na: "不适用",
                  }}
                  onChange={(v) =>
                    update({
                      first_article_result:
                        v as ReadinessItem["first_article_result"],
                    })
                  }
                />
              )}
              <p className="mf-full-width">
                来源：
                <Evidence value={current.source_ref} /> · 凭据：
                <Evidence value={current.evidence} />
              </p>
            </MutationForm>
            {!historical &&
              ["pending", "blocked"].includes(
                record.items.find((i) => i.id === selected)?.status || "",
              ) && (
                <button
                  className="mf-link"
                  disabled={host.readOnly}
                  onClick={() => setIssue(true)}
                >
                  登记关联问题
                </button>
              )}
          </div>
        </>
      )}
    </>
  );
}
