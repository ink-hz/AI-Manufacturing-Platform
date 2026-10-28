import { useEffect, useRef, useState } from "react";
import type { WorkflowError, WorkflowApi } from "./api";
import type {
  CommandFields,
  DomainValue,
  Grant,
  ProjectDetail,
  WorkflowTarget,
} from "./types";
import { label } from "./labels";
function targets(projectId: string, draft?: CommandFields): WorkflowTarget[] {
  if (!draft) return [];
  const target = (kind: WorkflowTarget["kind"], id: string) =>
    id ? [{ projectId, kind, id }] : [];
  switch (draft.action) {
    case "demand.record":
      return target("demand", draft.supersedes_demand_id || "");
    case "demand.review":
    case "order.register":
      return target("demand", draft.demand_id);
    case "order.change":
      return target("order_line", draft.order_line_id);
    case "order.allocate":
      return [
        ...target("order_line", draft.order_line_id),
        ...target("work_order", draft.work_order_id),
      ];
    case "order.resolve_change":
      return target("commitment_change", draft.change_id);
    case "engineering.handoff":
    case "engineering.customer_approval":
      return target("revision", draft.revision_id);
    case "work_order.register":
      return [
        ...target("order_line", draft.order_line_id),
        ...target("revision", draft.revision_id),
      ];
    case "readiness.record":
      return target("work_order", draft.work_order_id);
    case "plan.receive":
      return draft.requirements.flatMap(r=>target("work_order",r.work_order_id));
    case "supply.commit":
      return [...target("requirement",draft.requirement_id),...target("commitment",draft.commitment_id||"")];
    case "supply.receive":
      return [...target("commitment",draft.commitment_id),...target("material_lot",draft.material_lot_id)];
    case "supply.inspect":
      return target("receipt",draft.receipt_id);
    default:
      return [];
  }
}
function facts(v: DomainValue): [string, string][] {
  switch (v.kind) {
    case "demand":
      return [
        ["需求类别", label(v.demand_kind)],
        ["需求数量", v.quantity + " " + v.unit],
        ["需求交期", v.due_date],
        ...Object.entries(v.reviews).map(([k, value]): [string, string] => [
          label(k) + "评审",
          label(value),
        ]),
      ];
    case "order_line":
      return [
        ["原始承诺", v.original_quantity + " " + v.unit],
        ["当前承诺", v.current_quantity + " " + v.unit],
        ["当前交期", v.current_due],
        ["已分配合计", v.allocated + " " + v.unit],
        [
          "已登记工单总量",
          v.work_order_impact.registered_quantity + " " + v.unit,
        ],
        ["已登记工单数量", String(v.work_order_impact.total)],
        ["已发运", v.shipped + " " + v.unit],
        ["已验收", v.accepted + " " + v.unit],
      ];
    case "commitment_change":
      return [
        ["原承诺", v.old_quantity + " " + v.unit],
        ["拟变更承诺", v.new_quantity + " " + v.unit],
        ["新交期", v.new_due],
        ["变更状态", label(v.state)],
        ["原因", v.reason],
      ];
    case "revision":
      return [
        ["固定修订", v.revision],
        ["客户版本", v.customer_revision],
        ["内部版本", v.internal_revision],
        ["固件版本", v.firmware_version],
        ["测试规范", v.test_spec.version],
      ];
    case "work_order":
      return [
        ["工单数量", v.quantity + " " + v.unit],
        ["试产数量", v.trial_quantity + " " + v.unit],
        ["计划开始", v.planned_start],
        ["计划结束", v.planned_end],
        ["试产准备", v.trial_readiness.ready ? "就绪" : "阻断"],
        ["量产准备", v.bulk_readiness.ready ? "就绪" : "阻断"],
      ];
    case "plan":
      return [["计划状态",label(v.state)],["来源截止",v.cutoff||"未提供"],["拒绝原因",v.reason]];
    case "requirement":
      return [["需求数量",v.quantity+" "+v.unit],["在途",v.balance.in_transit],["已检合格",v.balance.qualified],["确认预留",v.balance.reserved],["缺口",v.balance.shortage]];
    case "commitment":
      return [["原始承诺",v.original_quantity+" "+v.unit],["当前承诺",v.current_quantity+" "+v.unit],["原始交期",v.original_due],["当前交期",v.current_due]];
    case "material_lot":
      return [["批次",v.lot_id],["所有者",v.owner_id],["单位",v.unit],["有效期",v.expiry],["状态",label(v.state)]];
    case "receipt":
      return [["本次到货",v.quantity+" "+v.unit],["检验合格",v.accepted],["拒收",v.rejected],["待检",v.uninspected]];
  }
}
const grantLabels: Record<string, string> = {
  project_owner: "项目负责人",
  engineering: "工程",
  planner: "计划",
  supply: "供应",
  production: "生产",
  quality: "质量",
  warehouse: "仓储",
  inspection: "检验资格",
  disposition: "处置资格",
  quality_release: "质量放行资格",
  readiness_verification: "准备依据核验资格",
};
export function ConflictComparison({
  api,
  projectId,
  version,
  error,
  draft,
  memberId,
}: {
  api: WorkflowApi;
  projectId: string;
  version: number;
  error: WorkflowError;
  draft?: CommandFields;
  memberId?: string;
}) {
  const [data, setData] = useState<{
      project: ProjectDetail;
      objects: { title: string; value: DomainValue }[];
      grant?: Grant;
    } | null>(null),
    [busy, setBusy] = useState(false),
    [failure, setFailure] = useState("");
  const generation = useRef(0);
  useEffect(
    () => () => {
      generation.current++;
    },
    [],
  );
  return (
    <section aria-label="当前服务端资料对照" className="wf-comparison">
      <p>
        草稿固定版本：{version}。
        {typeof error.fields.current_version === "number" && (
          <>服务端冲突版本：{error.fields.current_version}。</>
        )}
        对照读取保留全部草稿与原操作编号，不会自动更新提交版本。
      </p>
      <button
        type="button"
        disabled={busy}
        onClick={async () => {
          const current = ++generation.current;
          setBusy(true);
          setFailure("");
          try {
            const [project, objects, members] = await Promise.all([
              api.project(projectId),
              Promise.all(
                targets(projectId, draft).map((t) =>
                  api.object(t.projectId, t.kind, t.id),
                ),
              ),
              memberId ? api.members(projectId) : Promise.resolve(null),
            ]);
            if (current === generation.current)
              setData({
                project,
                objects: objects.map((d) => ({
                  title: d.summary.title,
                  value: d.value,
                })),
                grant: members?.items.find((g) => g.user_id === memberId),
              });
          } catch (e) {
            if (current === generation.current) setFailure(String(e));
          } finally {
            if (current === generation.current) setBusy(false);
          }
        }}
      >
        保留草稿并对照当前资料
      </button>
      {failure && <p role="alert">{failure}</p>}
      {data && (
        <>
          <h4>服务端当前项目版本：{data.project.version}</h4>
          <p>
            当前资料仅供对照；继续编辑与原样重试均保留草稿。放弃草稿并重新读取是独立操作。
          </p>
          <table>
            <thead>
              <tr>
                <th>当前项目事实</th>
                <th>服务端值</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>当前承诺</td>
                <td>
                  {data.project.summary.current_order_quantity}{" "}
                  {data.project.unit.code}
                </td>
              </tr>
              <tr>
                <td>已分配合计</td>
                <td>
                  {data.project.summary.allocated} {data.project.unit.code}
                </td>
              </tr>
            </tbody>
          </table>
          {data.objects.map((o, i) => (
            <section key={i}>
              <h4>
                {o.title} · 当前{label(o.value.kind)}
              </h4>
              <table>
                <thead>
                  <tr>
                    <th>业务字段</th>
                    <th>服务端值</th>
                  </tr>
                </thead>
                <tbody>
                  {facts(o.value).map(([name, value]) => (
                    <tr key={name}>
                      <td>{name}</td>
                      <td>{value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ))}
          {memberId && (
            <section>
              <h4>所选成员当前授权</h4>
              <p>状态：{data.grant?.active ? "启用" : "未授权或已撤销"}</p>
              <p>
                职责：
                {data.grant?.roles.map((r) => grantLabels[r] || r).join("、") ||
                  "无"}
              </p>
              <p>
                资格：
                {data.grant?.qualifications
                  .map((q) => grantLabels[q] || q)
                  .join("、") || "无"}
              </p>
            </section>
          )}
        </>
      )}
    </section>
  );
}
