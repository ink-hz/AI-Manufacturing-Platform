import { useEffect, useState } from "react";
import type { WorkspaceProps, ObjectSummary, CommandFields } from "../types";
import type { PackageItem } from "../../collaboration/types";
import {
  CommandForm,
  Field,
  Choice,
  ObjectChoice,
  SourceFields,
  source,
} from "./shared";
const item = (): PackageItem => ({
  id: crypto.randomUUID(),
  kind: "drawing",
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
type Props = WorkspaceProps & {
  action: CommandFields["action"];
  orders: ObjectSummary[];
  revisions: ObjectSummary[];
  workOrders: ObjectSummary[];
};
export function EngineeringForms(p: Props) {
  const [families, setFamilies] = useState<Record<string, string>>({});
  const [familyError, setFamilyError] = useState("");
  useEffect(() => {
    let active = true;
    if (p.action !== "engineering.revision") return;
    setFamilyError("");
    Promise.all(
      p.revisions.map((r) => p.api.object(p.project.id, "revision", r.id)),
    )
      .then((details) => {
        if (active)
          setFamilies(
            Object.fromEntries(
              details.flatMap((d) =>
                d.value.kind === "revision"
                  ? [
                      [
                        d.value.package_id,
                        `${d.value.items[0]?.title || "工程资料"} · ${d.value.revision}`,
                      ],
                    ]
                  : [],
              ),
            ),
          );
      })
      .catch(() => {
        if (active) setFamilyError("资料系列读取失败，请重新读取项目后重试。");
      });
    return () => {
      active = false;
    };
  }, [p.api, p.project.id, p.action, p.revisions]);
  switch (p.action) {
    case "engineering.revision":
      return (
        <CommandForm
          key={p.action}
          {...p}
          title="固定工程修订"
          save="固定修订"
          initial={() => ({
            action: "engineering.revision" as const,
            package_id: crypto.randomUUID() as string,
            revision: "",
            customer_revision: p.project.contract.customer_revision,
            internal_revision: p.project.contract.internal_revision,
            firmware_version: "",
            items: [item()],
            route_steps: [{ station: "", instruction_version: "" }],
            test_spec: {
              version: "",
              program_version: "",
              measurements: [{ name: "", unit: "", lower: "", upper: "" }],
            },
          })}
        >
          {(v, set) => (
            <>
              <p>
                固定后内容不可修改。新资料系列自动编号；选择既有系列可追加修订。
              </p>
              {familyError && <p role="alert">{familyError}</p>}
              <Choice
                name="资料系列"
                value={families[v.package_id] ? v.package_id : "new"}
                choices={{ new: "新资料系列", ...families }}
                onChange={(x) =>
                  set({
                    ...v,
                    package_id: x === "new" ? crypto.randomUUID() : x,
                  })
                }
              />
              {(
                [
                  "revision",
                  "customer_revision",
                  "internal_revision",
                  "firmware_version",
                ] as const
              ).map((k, i) => (
                <Field
                  key={k}
                  name={["修订号", "客户版本", "内部版本", "固件版本"][i]}
                  value={v[k]}
                  onChange={(x) => set({ ...v, [k]: x })}
                />
              ))}
              {v.items.map((it, i) => (
                <fieldset key={it.id}>
                  <legend>资料项 {i + 1}</legend>
                  <Choice
                    name={`资料类别 ${i + 1}`}
                    value={it.kind}
                    choices={{
                      ebom: "工程 BOM",
                      mbom: "制造 BOM",
                      drawing: "图纸",
                      route: "工艺路线",
                      sop: "作业指导",
                      firmware: "固件",
                      test_program: "测试程序",
                      test_spec: "测试规范",
                      other: "其他",
                    }}
                    onChange={(x) =>
                      set({
                        ...v,
                        items: v.items.map((e, n) =>
                          n === i
                            ? { ...e, kind: x as PackageItem["kind"] }
                            : e,
                        ),
                      })
                    }
                  />
                  {(
                    [
                      "title",
                      "source_name",
                      "source_ref",
                      "revision",
                      "owner",
                      "evidence",
                      "reason",
                    ] as const
                  ).map((k, j) => (
                    <Field
                      key={k}
                      name={`${["资料名称", "来源名称", "资料业务编号或链接", "资料版本", "资料负责人", "资料凭据", "核对理由"][j]} ${i + 1}`}
                      value={it[k]}
                      onChange={(x) =>
                        set({
                          ...v,
                          items: v.items.map((e, n) =>
                            n === i ? { ...e, [k]: x } : e,
                          ),
                        })
                      }
                    />
                  ))}
                  <Choice
                    name={`资料核对 ${i + 1}`}
                    value={it.status}
                    choices={{
                      pending: "待核对（不可固定）",
                      verified: "已核对",
                      na: "不适用",
                    }}
                    onChange={(x) =>
                      set({
                        ...v,
                        items: v.items.map((e, n) =>
                          n === i
                            ? { ...e, status: x as PackageItem["status"] }
                            : e,
                        ),
                      })
                    }
                  />
                  <button
                    type="button"
                    disabled={v.items.length === 1}
                    onClick={() =>
                      set({ ...v, items: v.items.filter((_, n) => n !== i) })
                    }
                  >
                    移除资料项 {i + 1}
                  </button>
                </fieldset>
              ))}
              <button
                type="button"
                onClick={() => set({ ...v, items: [...v.items, item()] })}
              >
                添加资料项
              </button>
              {v.route_steps.map((s, i) => (
                <fieldset key={i}>
                  <legend>工序 {i + 1}</legend>
                  <Field
                    name={`工位 ${i + 1}`}
                    value={s.station}
                    onChange={(x) =>
                      set({
                        ...v,
                        route_steps: v.route_steps.map((e, n) =>
                          n === i ? { ...e, station: x } : e,
                        ),
                      })
                    }
                  />
                  <Field
                    name={`作业指导版本 ${i + 1}`}
                    value={s.instruction_version}
                    onChange={(x) =>
                      set({
                        ...v,
                        route_steps: v.route_steps.map((e, n) =>
                          n === i ? { ...e, instruction_version: x } : e,
                        ),
                      })
                    }
                  />
                </fieldset>
              ))}
              <button
                type="button"
                onClick={() =>
                  set({
                    ...v,
                    route_steps: [
                      ...v.route_steps,
                      { station: "", instruction_version: "" },
                    ],
                  })
                }
              >
                添加工序
              </button>
              <Field
                name="测试规范版本"
                value={v.test_spec.version}
                onChange={(x) =>
                  set({ ...v, test_spec: { ...v.test_spec, version: x } })
                }
              />
              <Field
                name="测试程序版本"
                value={v.test_spec.program_version}
                onChange={(x) =>
                  set({
                    ...v,
                    test_spec: { ...v.test_spec, program_version: x },
                  })
                }
              />
              {v.test_spec.measurements.map((m, i) => (
                <fieldset key={i}>
                  <legend>测量项目 {i + 1}</legend>
                  {(["name", "unit", "lower", "upper"] as const).map((k, j) => (
                    <Field
                      key={k}
                      name={`${["测量名称", "测量单位", "测量下限", "测量上限"][j]} ${i + 1}`}
                      value={m[k]}
                      onChange={(x) =>
                        set({
                          ...v,
                          test_spec: {
                            ...v.test_spec,
                            measurements: v.test_spec.measurements.map(
                              (e, n) => (n === i ? { ...e, [k]: x } : e),
                            ),
                          },
                        })
                      }
                    />
                  ))}
                </fieldset>
              ))}
              <button
                type="button"
                onClick={() =>
                  set({
                    ...v,
                    test_spec: {
                      ...v.test_spec,
                      measurements: [
                        ...v.test_spec.measurements,
                        { name: "", unit: "", lower: "", upper: "" },
                      ],
                    },
                  })
                }
              >
                添加测量项目
              </button>
            </>
          )}
        </CommandForm>
      );
    case "engineering.handoff":
      return (
        <CommandForm
          key={p.action}
          {...p}
          title="登记版本交接"
          save="保存交接事实"
          initial={() => ({
            action: "engineering.handoff" as const,
            revision_id: "",
            to_system: "MES",
            received_revision: "",
            decision: "accepted" as const,
            evidence: "",
          })}
        >
          {(v, set) => (
            <>
              <ObjectChoice
                name="交接修订"
                items={p.revisions}
                value={v.revision_id}
                onChange={(x) => set({ ...v, revision_id: x })}
              />
              <Field
                name="接收系统"
                value={v.to_system}
                onChange={(x) => set({ ...v, to_system: x })}
              />
              <Field
                name="实际收到修订号"
                value={v.received_revision}
                onChange={(x) => set({ ...v, received_revision: x })}
              />
              <Choice
                name="接收结论"
                value={v.decision}
                choices={{ accepted: "接收", rejected: "拒绝" }}
                onChange={(x) =>
                  set({ ...v, decision: x as typeof v.decision })
                }
              />
              <Field
                name="交接凭据"
                value={v.evidence}
                onChange={(x) => set({ ...v, evidence: x })}
              />
              <p>错版接收将被记录为拒绝，请以详情中的核验结果为准。</p>
            </>
          )}
        </CommandForm>
      );
    case "engineering.customer_approval":
      return (
        <CommandForm
          key={p.action}
          {...p}
          title="登记客户批准"
          save="保存人工批准记录"
          initial={() => ({
            action: "engineering.customer_approval" as const,
            revision_id: "",
            method: "manual" as const,
            decision: "unknown" as const,
            customer_id: p.project.customer_id,
            external_signatory: "",
            evidence: "",
          })}
        >
          {(v, set) => (
            <>
              <p>人工登记外部签署证据。</p>
              <ObjectChoice
                name="批准修订"
                items={p.revisions}
                value={v.revision_id}
                onChange={(x) => set({ ...v, revision_id: x })}
              />
              <Field
                name="客户"
                value={v.customer_id}
                onChange={(x) => set({ ...v, customer_id: x })}
              />
              <Field
                name="外部签署人"
                value={v.external_signatory}
                onChange={(x) => set({ ...v, external_signatory: x })}
              />
              <Choice
                name="客户批准结论"
                value={v.decision}
                choices={{
                  unknown: "待确认",
                  approved: "通过",
                  rejected: "拒绝",
                }}
                onChange={(x) =>
                  set({ ...v, decision: x as typeof v.decision })
                }
              />
              <Field
                name="批准凭据"
                value={v.evidence}
                onChange={(x) => set({ ...v, evidence: x })}
              />
            </>
          )}
        </CommandForm>
      );
    case "work_order.register":
      return (
        <CommandForm
          key={p.action}
          {...p}
          title="登记固定版本工单"
          save="保存工单"
          initial={() => ({
            action: "work_order.register" as const,
            order_line_id: "",
            revision_id: "",
            source: source("work_order"),
            quantity: "",
            unit: p.project.unit.code,
            purpose: "trial" as const,
            trial_quantity: "",
            planned_start: "",
            planned_end: "",
          })}
        >
          {(v, set) => (
            <>
              <ObjectChoice
                name="工单依据订单"
                items={p.orders}
                value={v.order_line_id}
                onChange={(x) => set({ ...v, order_line_id: x })}
              />
              <ObjectChoice
                name="工单固定修订"
                items={p.revisions}
                value={v.revision_id}
                onChange={(x) => set({ ...v, revision_id: x })}
              />
              <Field
                name="工单数量"
                value={v.quantity}
                onChange={(x) => set({ ...v, quantity: x })}
              />
              <Field
                name="数量单位"
                value={v.unit}
                onChange={(x) => set({ ...v, unit: x })}
              />
              <Field
                name="试产数量"
                value={v.trial_quantity}
                onChange={(x) => set({ ...v, trial_quantity: x })}
              />
              <Choice
                name="工单用途"
                value={v.purpose}
                choices={{ trial: "试产", production: "生产" }}
                onChange={(x) => set({ ...v, purpose: x as typeof v.purpose })}
              />
              <Field
                name="计划开始"
                type="datetime-local"
                value={v.planned_start}
                onChange={(x) =>
                  set({
                    ...v,
                    planned_start: x,
                  })
                }
              />
              <Field
                name="计划结束"
                type="datetime-local"
                value={v.planned_end}
                onChange={(x) => set({ ...v, planned_end: x })}
              />
              <SourceFields
                value={v.source}
                onChange={(x) => set({ ...v, source: x })}
              />
            </>
          )}
        </CommandForm>
      );
    case "readiness.record":
      return (
        <CommandForm
          key={p.action}
          {...p}
          title="登记准备核验"
          save="保存准备证据"
          initial={() => ({
            action: "readiness.record" as const,
            work_order_id: "",
            kind: "equipment" as const,
            reference: "",
            evidence: "",
            valid_until: "",
            decision: "verified" as const,
          })}
        >
          {(v, set) => (
            <>
              <ObjectChoice
                name="准备核验工单"
                items={p.workOrders}
                value={v.work_order_id}
                onChange={(x) => set({ ...v, work_order_id: x })}
              />
              <Choice
                name="核验类别"
                value={v.kind}
                choices={{ equipment: "设备", people: "人员" }}
                onChange={(x) => set({ ...v, kind: x as typeof v.kind })}
              />
              <Field
                name="核验业务编号"
                value={v.reference}
                onChange={(x) => set({ ...v, reference: x })}
              />
              <Field
                name="核验凭据"
                value={v.evidence}
                onChange={(x) => set({ ...v, evidence: x })}
              />
              <Field
                name="有效期至"
                type="datetime-local"
                value={v.valid_until}
                onChange={(x) => set({ ...v, valid_until: x })}
              />
              <Choice
                name="核验结论"
                value={v.decision}
                choices={{ verified: "已核验", rejected: "拒绝" }}
                onChange={(x) =>
                  set({ ...v, decision: x as typeof v.decision })
                }
              />
            </>
          )}
        </CommandForm>
      );
    default:
      return null;
  }
}
