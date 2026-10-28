import { useEffect, useRef, useState, type ReactNode } from "react";
import type {
  CommandFields,
  SourceRef,
  WorkspaceProps,
  WorkflowCommand,
  ObjectSummary,
} from "../types";
import { WorkflowError } from "../api";
export const labels: Record<string, string> = {
  "MES receipt matches fixed revision": "MES 接收版本与固定修订一致",
  "fixed revision lacks matching accepted MES receipt":
    "固定修订缺少匹配的 MES 接收回执",
  "equipment evidence valid at planned use": "设备依据在计划使用时有效",
  "equipment evidence missing, rejected, or expired at planned use":
    "设备依据缺失、被拒绝或在计划使用时过期",
  "people evidence valid at planned use": "人员依据在计划使用时有效",
  "people evidence missing, rejected, or expired at planned use":
    "人员依据缺失、被拒绝或在计划使用时过期",
  "matching customer approval recorded": "已登记匹配的客户批准",
  "customer approval or contractual revision is unknown or missing":
    "客户批准或合同版本尚未确认或缺失",
  "no authoritative material plan cutoff": "缺少权威物料计划截止事实",
  "no accepted scoped material reservation": "缺少已确认的范围内物料预留",
  "matching tested first article absent": "缺少匹配版本的首件检验证据",
  "trial does not require first article": "试产无需首件前置检验",
  "change disposition pending": "承诺变更影响尚待处理",
  authorized_by: "正式订单依据",
  fixed_revision: "固定工程修订",
  supersedes: "替代原需求",
  formal_demand: "正式需求依据",
  allocated_work_order: "已分配工单",
  changes_order: "变更订单",
  "demand.record": "登记需求",
  "demand.review": "需求评审",
  "order.register": "登记订单",
  "order.change": "承诺变更",
  "order.allocate": "分配工单",
  "order.resolve_change": "处理承诺影响",
  "engineering.revision": "固定修订",
  "engineering.handoff": "版本交接",
  "engineering.customer_approval": "人工客户批准",
  "work_order.register": "登记工单",
  "readiness.record": "准备核验",
  na: "不适用",
  firm: "正式需求",
  forecast: "预测",
  inquiry: "询价",
  approved: "通过",
  rejected: "拒绝",
  unknown: "待确认",
  accepted: "接收",
  verified: "已核验",
  active: "有效",
  cancelled: "已取消",
  pending: "待处理",
  applied: "已生效",
  planned: "已登记",
  fixed: "已固定",
  ready: "就绪",
  blocked: "阻断",
  not_required: "不适用",
  technical: "技术",
  material: "物料",
  capacity: "产能",
  commercial: "商务",
  quality: "质量",
  version: "版本",
  equipment: "设备",
  people: "人员",
  customer: "客户批准",
  plan: "计划",
  first_article: "首件",
  demand: "需求",
  order_line: "订单",
  commitment_change: "承诺变更",
  revision: "工程修订",
  work_order: "工单",
  trial: "试产",
  production: "生产",
  retain: "保留",
  cancel: "取消",
  transfer: "转移",
  rework: "返工",
  return: "退回",
};
export const label = (v: string) => labels[v] || v;
export const objectTitle = (v: ObjectSummary) =>
  v.kind === "revision"
    ? v.title.replace(/^[0-9a-f]{8}-[0-9a-f-]{27} /i, "工程修订 ")
    : v.title;
export function Field({
  name,
  value,
  onChange,
  type = "text",
  required = true,
}: {
  name: string;
  value: string;
  onChange(v: string): void;
  type?: string;
  required?: boolean;
}) {
  return (
    <label>
      {name}
      <input
        aria-label={name}
        type={type}
        required={required}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}
export function Choice({
  name,
  value,
  onChange,
  choices,
  required = true,
}: {
  name: string;
  value: string;
  onChange(v: string): void;
  choices: Record<string, string>;
  required?: boolean;
}) {
  return (
    <label>
      {name}
      <select
        aria-label={name}
        required={required}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {Object.entries(choices).map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </label>
  );
}
export function ObjectChoice({
  name,
  value,
  onChange,
  items,
  required = true,
}: {
  name: string;
  value: string;
  onChange(v: string): void;
  items: ObjectSummary[];
  required?: boolean;
}) {
  return (
    <Choice
      required={required}
      name={name}
      value={value}
      onChange={onChange}
      choices={{
        "": "请选择",
        ...Object.fromEntries(
          items.map((i) => [
            i.id,
            `${objectTitle(i)} · ${label(i.state)}${i.quantity !== null ? " · " + i.quantity + " " + i.unit : ""}`,
          ]),
        ),
      }}
    />
  );
}
export const source = (object_type: string): SourceRef => ({
  system: "人工登记",
  object_type,
  external_id: "",
  version: 1,
  mode: "manual",
  occurred_at: "",
  collected_at: "",
  cutoff: null,
  evidence: "",
});
export function SourceFields({
  value,
  onChange,
}: {
  value: SourceRef;
  onChange(v: SourceRef): void;
}) {
  return (
    <fieldset>
      <legend>来源依据 · 人工登记</legend>
      <Field
        name="来源系统"
        value={value.system}
        onChange={(v) => onChange({ ...value, system: v })}
      />
      <Field
        name="来源业务编号"
        value={value.external_id}
        onChange={(v) => onChange({ ...value, external_id: v })}
      />
      <Field
        name="来源版本"
        type="number"
        value={String(value.version)}
        onChange={(v) => onChange({ ...value, version: Number(v) })}
      />
      <Field
        name="来源发生时间"
        type="datetime-local"
        required={false}
        value={value.occurred_at}
        onChange={(v) => onChange({ ...value, occurred_at: v })}
      />
      <Field
        name="来源凭据"
        value={value.evidence}
        onChange={(v) => onChange({ ...value, evidence: v })}
      />
    </fieldset>
  );
}
export function CommandForm<T extends CommandFields>({
  initial,
  title,
  save,
  children,
  ...props
}: WorkspaceProps & {
  initial: () => T;
  title: string;
  save: string;
  children: (v: T, set: (v: T) => void) => ReactNode;
}) {
  const [value, setValue] = useState(initial),
    [version] = useState(props.project.version),
    [dirty, setDirty] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const pending = useRef<WorkflowCommand | null>(null),
    alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      props.onDirty(title, false);
    };
  }, []);
  function set(v: T) {
    if (!alive.current) return;
    pending.current = null;
    setValue(v);
    setDirty(true);
    props.onDirty(title, true);
  }
  return (
    <form
      aria-label={title}
      className="wf-form"
      onSubmit={async (e) => {
        e.preventDefault();
        if (busy || props.readOnly) return;
        setBusy(true);
        setError("");
        try {
          if (!pending.current) {
            const fields = structuredClone(value);
            if ("source" in fields) {
              const now = new Date().toISOString();
              fields.source = {
                ...fields.source,
                occurred_at: fields.source.occurred_at
                  ? new Date(fields.source.occurred_at).toISOString()
                  : now,
                collected_at: now,
              };
            }
            if (fields.action === "work_order.register") {
              fields.planned_start = new Date(
                fields.planned_start,
              ).toISOString();
              fields.planned_end = new Date(fields.planned_end).toISOString();
            }
            if (fields.action === "readiness.record")
              fields.valid_until = new Date(fields.valid_until).toISOString();
            pending.current = {
              ...fields,
              expected_version: version,
              operation_id: crypto.randomUUID(),
            };
          }
          const result = await props.api.command(
            props.project.id,
            pending.current,
          );
          if (alive.current) {
            setDirty(false);
            props.onDirty(title, false);
            props.onChanged(result);
          }
        } catch (e) {
          if (alive.current)
            setError(
              e instanceof WorkflowError
                ? e.message +
                    (e.reasons.length ? " " + e.reasons.join("；") : "")
                : String(e),
            );
        } finally {
          if (alive.current) setBusy(false);
        }
      }}
    >
      <h3>{title}</h3>
      <p>
        草稿依据：项目版本 {version}
        {dirty ? " · 未保存" : ""}
      </p>
      <fieldset disabled={busy || props.readOnly}>
        {children(value, set)}
      </fieldset>
      {error && <p role="alert">{error}</p>}
      <button disabled={busy || props.readOnly} type="submit">
        {save}
      </button>
    </form>
  );
}
