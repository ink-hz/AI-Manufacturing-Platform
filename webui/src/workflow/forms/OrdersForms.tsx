import type {
  WorkspaceProps,
  ObjectSummary,
  DomainValue,
  CommandFields,
} from "../types";
import {
  CommandForm,
  Field,
  Choice,
  ObjectChoice,
  SourceFields,
  source,
} from "./shared";
type Props = WorkspaceProps & {
  action: CommandFields["action"];
  demands: ObjectSummary[];
  orders: ObjectSummary[];
  workOrders: ObjectSummary[];
  change?: Extract<DomainValue, { kind: "commitment_change" }>;
  changeId?: string;
};
export function OrdersForms(p: Props) {
  const common = { ...p };
  switch (p.action) {
    case "demand.record":
      return (
        <CommandForm
          key={p.action}
          {...common}
          title="登记需求"
          save="保存需求"
          initial={() => ({
            action: "demand.record" as const,
            kind: "firm" as const,
            product: p.project.product,
            quantity: "",
            unit: p.project.unit.code,
            due_date: "",
            source: source("demand"),
            supersedes_demand_id: null as string | null,
          })}
        >
          {(v, set) => (
            <>
              <Choice
                name="需求类型"
                value={v.kind}
                choices={{
                  firm: "正式需求",
                  forecast: "预测",
                  inquiry: "询价",
                }}
                onChange={(x) => set({ ...v, kind: x as typeof v.kind })}
              />
              <Field
                name="产品"
                value={v.product}
                onChange={(x) => set({ ...v, product: x })}
              />
              <Field
                name="需求数量"
                value={v.quantity}
                onChange={(x) => set({ ...v, quantity: x })}
              />
              <Field
                name="数量单位"
                value={v.unit}
                onChange={(x) => set({ ...v, unit: x })}
              />
              <Field
                name="需求交期"
                type="date"
                value={v.due_date}
                onChange={(x) => set({ ...v, due_date: x })}
              />
              <ObjectChoice
                name="替代原需求（可选）"
                required={false}
                items={p.demands}
                value={v.supersedes_demand_id || ""}
                onChange={(x) => set({ ...v, supersedes_demand_id: x || null })}
              />
              <SourceFields
                value={v.source}
                onChange={(x) => set({ ...v, source: x })}
              />
            </>
          )}
        </CommandForm>
      );
    case "demand.review":
      return (
        <CommandForm
          key={p.action}
          {...common}
          title="评审需求"
          save="保存评审"
          initial={() => ({
            action: "demand.review" as const,
            demand_id: "",
            dimension: "technical" as const,
            decision: "unknown" as const,
            evidence: "",
          })}
        >
          {(v, set) => (
            <>
              <ObjectChoice
                name="评审需求"
                items={p.demands}
                value={v.demand_id}
                onChange={(x) => set({ ...v, demand_id: x })}
              />
              <Choice
                name="评审维度"
                value={v.dimension}
                choices={{
                  technical: "技术",
                  material: "物料",
                  capacity: "产能",
                  commercial: "商务",
                  quality: "质量",
                }}
                onChange={(x) =>
                  set({ ...v, dimension: x as typeof v.dimension })
                }
              />
              <Choice
                name="评审结论"
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
                name="评审凭据"
                value={v.evidence}
                onChange={(x) => set({ ...v, evidence: x })}
              />
            </>
          )}
        </CommandForm>
      );
    case "order.register":
      return (
        <CommandForm
          key={p.action}
          {...common}
          title="登记正式订单"
          save="保存订单"
          initial={() => ({
            action: "order.register" as const,
            demand_id: "",
            quantity: "",
            unit: p.project.unit.code,
            due_date: "",
            source: source("order"),
          })}
        >
          {(v, set) => (
            <>
              <p>仅已完成五项评审的正式需求可登记订单。</p>
              <ObjectChoice
                name="订单依据需求"
                items={p.demands}
                value={v.demand_id}
                onChange={(x) => set({ ...v, demand_id: x })}
              />
              <Field
                name="订单数量"
                value={v.quantity}
                onChange={(x) => set({ ...v, quantity: x })}
              />
              <Field
                name="数量单位"
                value={v.unit}
                onChange={(x) => set({ ...v, unit: x })}
              />
              <Field
                name="订单交期"
                type="date"
                value={v.due_date}
                onChange={(x) => set({ ...v, due_date: x })}
              />
              <SourceFields
                value={v.source}
                onChange={(x) => set({ ...v, source: x })}
              />
            </>
          )}
        </CommandForm>
      );
    case "order.change":
      return (
        <CommandForm
          key={p.action}
          {...common}
          title="变更订单承诺"
          save="保存承诺变更"
          initial={() => ({
            action: "order.change" as const,
            order_line_id: "",
            new_quantity: "",
            new_due_date: "",
            cancel: false as boolean,
            reason: "",
            source: source("order_change"),
          })}
        >
          {(v, set) => (
            <>
              <ObjectChoice
                name="变更订单"
                items={p.orders}
                value={v.order_line_id}
                onChange={(x) => set({ ...v, order_line_id: x })}
              />
              <Field
                name="变更后数量"
                value={v.new_quantity}
                onChange={(x) => set({ ...v, new_quantity: x })}
              />
              <Field
                name="变更后交期"
                type="date"
                value={v.new_due_date}
                onChange={(x) => set({ ...v, new_due_date: x })}
              />
              <Choice
                name="取消订单"
                value={String(v.cancel)}
                choices={{ false: "否", true: "是" }}
                onChange={(x) => set({ ...v, cancel: x === "true" })}
              />
              <Field
                name="变更原因"
                value={v.reason}
                onChange={(x) => set({ ...v, reason: x })}
              />
              <SourceFields
                value={v.source}
                onChange={(x) => set({ ...v, source: x })}
              />
            </>
          )}
        </CommandForm>
      );
    case "order.allocate":
      return (
        <CommandForm
          key={p.action}
          {...common}
          title="分配订单工单"
          save="保存分配"
          initial={() => ({
            action: "order.allocate" as const,
            order_line_id: "",
            work_order_id: "",
            quantity: "",
            unit: p.project.unit.code,
          })}
        >
          {(v, set) => (
            <>
              <p>工单必须永久绑定本订单。服务端核验数量和订单依据。</p>
              <ObjectChoice
                name="分配订单"
                items={p.orders}
                value={v.order_line_id}
                onChange={(x) => set({ ...v, order_line_id: x })}
              />
              <ObjectChoice
                name="分配工单"
                items={p.workOrders}
                value={v.work_order_id}
                onChange={(x) => set({ ...v, work_order_id: x })}
              />
              <Field
                name="分配数量"
                value={v.quantity}
                onChange={(x) => set({ ...v, quantity: x })}
              />
              <Field
                name="数量单位"
                value={v.unit}
                onChange={(x) => set({ ...v, unit: x })}
              />
            </>
          )}
        </CommandForm>
      );
    case "order.resolve_change":
      return p.change && p.changeId ? (
        <CommandForm
          key={p.action}
          {...common}
          title="处理承诺影响"
          save="保存影响处理"
          initial={() => ({
            action: "order.resolve_change" as const,
            change_id: p.changeId!,
            dispositions: p.change!.impacts.map((i) => ({
              object_type: i.object_type,
              object_id: i.object_id,
              decision: "retain" as const,
              evidence: "",
            })),
          })}
        >
          {(v, set) => (
            <>
              <p>
                现阶段仅保留且符合新数量的工单可完成处理。取消或拆分仍需权威回执能力。
              </p>
              {v.dispositions.map((d, i) => (
                <fieldset key={d.object_id}>
                  <legend>
                    受影响工单 {i + 1} · {p.change!.impacts[i].quantity}{" "}
                    {p.change!.unit}
                  </legend>
                  <p>处置：保留</p>
                  <Field
                    name={`影响处理凭据 ${i + 1}`}
                    value={d.evidence}
                    onChange={(x) =>
                      set({
                        ...v,
                        dispositions: v.dispositions.map((e, n) =>
                          n === i ? { ...e, evidence: x } : e,
                        ),
                      })
                    }
                  />
                </fieldset>
              ))}
            </>
          )}
        </CommandForm>
      ) : null;
    default:
      return null;
  }
}
