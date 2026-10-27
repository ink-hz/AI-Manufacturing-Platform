import { useState } from "react";
import type { Api } from "../api";
import { Choice } from "../projects/ui";
import type {
  EngineeringPackage,
  Readiness,
  ReadinessFields,
  ReadinessItem,
} from "./types";
import { Field, MutationForm, type EditorHost } from "./ui";
import { readinessKinds } from "./labels";
import { newCheck } from "./readinessDraft";
export function ReadinessCreate({
  api,
  projectId,
  packages,
  old,
  ...host
}: {
  api: Api;
  projectId: string;
  packages: EngineeringPackage[];
  old?: Readiness;
} & EditorHost) {
  const source = old && packages.find((p) => p.id === old.package_id);
  const available = packages.filter(
    (p) =>
      p.status === "verified" &&
      (!old ||
        (p.family_id === source?.family_id &&
          p.revision > old.package_revision)),
  );
  function binding(item: ReadinessItem, packageId: string): ReadinessItem {
    const source = available.find((p) => p.id === packageId);
    const valid =
      source?.items.filter(
        (i) => item.kind !== "version" || i.status === "verified",
      ) || [];
    const id = valid.some((i) => i.id === item.package_item_id)
      ? item.package_item_id
      : item.kind === "version"
        ? valid[0]?.id || null
        : null;
    return {
      ...item,
      package_item_id: id,
      status: item.kind === "version" && !id && !old ? "na" : "pending",
    };
  }

  const [initial] = useState<ReadinessFields>(() => ({
    title: old?.title || "",
    package_id: available[0]?.id || "",
    work_order_ref: old?.work_order_ref || "",
    scope: old?.scope || "",
    planned_use_date: old?.planned_use_date || "",
    required: old?.required ?? true,
    owner: old?.owner || "",
    items: old
      ? old.items.map((i) => ({
          ...binding(i, available[0]?.id),
          status: "pending",
          evidence: "",
          source_ref: "",
          reason: "",
          valid_until: null,
          first_article_result: "unknown",
        }))
      : [binding(newCheck(), available[0]?.id)],
    ...(old ? { supersedes_id: old.id, supersedes_version: old.version } : {}),
  }));
  const [d, set] = useState(initial);
  const [item, setItem] = useState(0);
  const update = <K extends keyof ReadinessFields>(
    k: K,
    v: ReadinessFields[K],
  ) => set({ ...d, [k]: v });
  const current = d.items[item];
  const updateItem = (p: Partial<ReadinessItem>) =>
    update(
      "items",
      d.items.map((i, n) => (n === item ? { ...i, ...p } : i)),
    );
  if (!available.length)
    return (
      <>
        <h3>{old ? "替代此核对" : "新建准备核对"}</h3>
        <p className="mf-empty">
          {old
            ? "尚无同一资料家族的更新冻结修订。先建立并人工核对新资料修订，再替代本核对。"
            : "尚无已人工核对的冻结资料包。请先在工程资料中完成核对。"}
        </p>
        <button onClick={host.onCancel}>返回列表</button>
      </>
    );
  return (
    <>
      <h3>{old ? "建立替代核对" : "新建准备核对"}</h3>
      <p className="mf-muted">
        执行范围与必需项建立后固定；新版本以明确替代建立独立待核对记录，保留旧历史。
      </p>
      <MutationForm
        {...host}
        draft={d}
        initial={initial}
        changed={!!old}
        label={old ? "建立替代核对" : "建立核对"}
        write={async (body) => {
          if (
            body.items.some(
              (i) =>
                i.kind === "version" &&
                !i.package_item_id &&
                (old || i.status !== "na"),
            )
          )
            throw new Error("替代核对必须选择适用的冻结资料项");
          if (body.items.some((i) => i.status === "na" && !i.reason.trim()))
            throw new Error("不适用需填写原因");
          return api.createReadiness(projectId, body);
        }}
      >
        <Field
          label="核对名称"
          required
          maxLength={300}
          value={d.title}
          onChange={(v) => update("title", v)}
        />
        <Choice
          label="准备依据修订"
          value={d.package_id}
          values={Object.fromEntries(
            available.map((p) => [p.id, `${p.title} · 修订 ${p.revision}`]),
          )}
          onChange={(v) =>
            set({
              ...d,
              package_id: v,
              items: d.items.map((i) => binding(i, v)),
            })
          }
        />
        {old ? (
          <p className="mf-full-width">
            固定工单 {old.work_order_ref} / 范围 {old.scope} ·{" "}
            {old.required ? "必需" : "补充"}
          </p>
        ) : (
          <>
            <Field
              label="工单编号"
              required
              maxLength={300}
              value={d.work_order_ref}
              onChange={(v) => update("work_order_ref", v)}
            />
            <Field
              label="执行范围"
              required
              maxLength={300}
              value={d.scope}
              onChange={(v) => update("scope", v)}
            />
            <label>
              <input
                type="checkbox"
                checked={d.required}
                onChange={(e) => update("required", e.target.checked)}
              />
              纳入项目必需准备
            </label>
          </>
        )}
        <Field
          label="计划使用日期"
          type="date"
          required
          value={d.planned_use_date}
          onChange={(v) => update("planned_use_date", v)}
        />
        <Field
          label="核对负责人"
          required
          maxLength={300}
          value={d.owner}
          onChange={(v) => update("owner", v)}
        />
        <div className="mf-full-width mf-item-tabs">
          {d.items.map((i, n) => (
            <button
              type="button"
              key={i.id}
              onClick={() => setItem(n)}
              aria-current={item === n ? "page" : undefined}
            >
              {i.label}
            </button>
          ))}
          <button
            type="button"
            onClick={() => {
              update("items", [...d.items, newCheck("materials")]);
              setItem(d.items.length);
            }}
          >
            添加准备项
          </button>
        </div>
        {current && (
          <>
            {old && old.items.some((i) => i.id === current.id && i.required) ? (
              <p>{current.label} · 历史必需项（保留适用性）</p>
            ) : (
              <>
                <Choice
                  label="准备项类别"
                  value={current.kind}
                  values={readinessKinds}
                  onChange={(v) =>
                    updateItem(
                      binding(
                        {
                          ...current,
                          kind: v as ReadinessItem["kind"],
                          label: readinessKinds[v as ReadinessItem["kind"]],
                        },
                        d.package_id,
                      ),
                    )
                  }
                />
                <Field
                  label="准备项名称"
                  required
                  maxLength={300}
                  value={current.label}
                  onChange={(v) => updateItem({ label: v })}
                />
                <label>
                  <input
                    type="checkbox"
                    checked={current.required}
                    onChange={(e) => updateItem({ required: e.target.checked })}
                  />
                  必需准备项
                </label>
              </>
            )}
            {current.kind === "version" && (
              <Choice
                label="对应冻结资料项"
                value={current.package_item_id || ""}
                values={{
                  "": old
                    ? "请选择适用的冻结资料项"
                    : "无适用项（建立为不适用并说明原因）",
                  ...Object.fromEntries(
                    (available.find((p) => p.id === d.package_id)?.items || [])
                      .filter((i) => i.status === "verified")
                      .map((i) => [i.id, `${i.title} / ${i.revision}`]),
                  ),
                }}
                onChange={(v) =>
                  updateItem({
                    package_item_id: v || null,
                    status: !v && !old ? "na" : "pending",
                  })
                }
              />
            )}
            {current.status === "na" && (
              <Field
                label="不适用原因"
                required
                value={current.reason}
                onChange={(v) => updateItem({ reason: v })}
              />
            )}
            <Field
              label="准备项负责人"
              value={current.owner}
              onChange={(v) => updateItem({ owner: v })}
            />
            <p className="mf-muted">
              适用项从待核对开始；明确不适用需在建立时记录原因。凭据等后续逐项登记。
            </p>
          </>
        )}
      </MutationForm>
    </>
  );
}
