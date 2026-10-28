import { useEffect, useRef, useState } from "react";
import type {
  WorkspaceProps,
  ObjectSummary,
  ObjectKind,
  CommandFields,
} from "./types";
import { OrdersForms } from "./forms/OrdersForms";
import { EngineeringForms } from "./forms/EngineeringForms";
import { label, objectTitle } from "./forms/shared";
const actions: Record<string, string> = {
  "demand.record": "登记需求",
  "demand.review": "评审需求",
  "order.register": "登记正式订单",
  "order.change": "变更订单承诺",
  "order.allocate": "分配订单工单",
  "contract.agree": "确认修订合同条件",
  "engineering.revision": "固定工程修订",
  "engineering.handoff": "登记版本交接",
  "engineering.customer_approval": "登记客户批准",
  "work_order.register": "登记固定版本工单",
  "readiness.record": "登记准备核验",
  "eco.open":"建立 ECO", "eco.disposition":"处置 ECO 影响", "eco.switch":"切换 ECO 边界", "eco.close":"关闭 ECO",
};
type OrdersKind = "demand" | "order_line" | "commitment_change" | "revision" | "work_order" | "eco" | "unit";
export function ObjectTable({
  items,
  onOpen,
}: {
  items: ObjectSummary[];
  onOpen: WorkspaceProps["onOpen"];
}) {
  return (
    <table>
      <thead>
        <tr>
          <th>业务记录</th>
          <th>状态</th>
          <th>数量 / 单位</th>
          <th>来源</th>
          <th>阻断原因</th>
        </tr>
      </thead>
      <tbody>
        {items.map((i) => (
          <tr key={i.id}>
            <td>
              <button
                onClick={() =>
                  onOpen({ projectId: i.project_id, kind: i.kind, id: i.id })
                }
              >
                {objectTitle(i)}
              </button>
            </td>
            <td>{label(i.state)}</td>
            <td>
              {i.quantity !== null ? `${i.quantity} ${i.unit || ""}` : "—"}
            </td>
            <td>
              {i.source
                ? `${i.source.system} · ${i.source.external_id} · ${i.source.mode === "manual" ? "人工登记" : i.source.mode}`
                : "固定业务记录"}
            </td>
            <td>{i.blocking_reasons.map(label).join("；") || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
export function OrdersWorkspace(
  p: WorkspaceProps & {
    engineering?: boolean;
    requestLeave(action: () => void): void;
    onReload?(): void;
  },
) {
  const [items, setItems] = useState<Record<OrdersKind, ObjectSummary[]>>({
      demand: [],
      order_line: [],
      commitment_change: [],
      revision: [],
      work_order: [],
      eco: [],
      unit: [],
    }),
    [error, setError] = useState(""),
    [action, setAction] = useState<CommandFields["action"] | null>(null),
    [epoch, setEpoch] = useState(0);
  const [totals, setTotals] = useState<Partial<Record<OrdersKind, number>>>({});
  const [loading, setLoading] = useState<Partial<Record<OrdersKind, boolean>>>(
    {},
  );
  const generation = useRef(0);
  useEffect(() => {
    const current = ++generation.current;
    setError("");
    Promise.all(
      (Object.keys(items) as OrdersKind[]).map(
        async (k) => [k, await p.api.objects(p.project.id, k, 50, 0)] as const,
      ),
    )
      .then((pages) => {
        if (current === generation.current) {
          setItems(
            Object.fromEntries(
              pages.map(([k, page]) => [k, page.items]),
            ) as typeof items,
          );
          setTotals(
            Object.fromEntries(pages.map(([k, page]) => [k, page.total])),
          );
        }
      })
      .catch((e) => {
        if (current === generation.current) setError(String(e));
      });
    return () => {
      generation.current++;
    };
  }, [p.api, p.project.id, p.project.version]);
  async function more(kind: OrdersKind) {
    if (loading[kind]) return;
    const current = generation.current;
    setLoading((old) => ({ ...old, [kind]: true }));
    try {
      const page = await p.api.objects(
        p.project.id,
        kind,
        50,
        items[kind].length,
      );
      if (current === generation.current) {
        setItems((old) => ({ ...old, [kind]: [...old[kind], ...page.items] }));
        setTotals((old) => ({ ...old, [kind]: page.total }));
      }
    } catch (e) {
      if (current === generation.current) setError(String(e));
    } finally {
      if (current === generation.current)
        setLoading((old) => ({ ...old, [kind]: false }));
    }
  }
  const available = Object.keys(actions).filter(
    (a) =>
      (p.engineering
        ? a.startsWith("contract.") || a.startsWith("engineering.") ||
          a.startsWith("work_order.") ||
          a.startsWith("readiness.") || a.startsWith("eco.")
        : a.startsWith("order.") || a.startsWith("demand.")) &&
      p.project.allowed_actions.includes(a as CommandFields["action"]),
  );
  const formProps = {
    ...p,
    orders: items.order_line,
    demands: items.demand,
    revisions: items.revision,
    workOrders: items.work_order,
    ecos: items.eco, units: items.unit,
    onChanged: (result: Parameters<WorkspaceProps["onChanged"]>[0]) => {
      setAction(null);
      p.onChanged(result);
    },
  };
  return (
    <section>
      <h3>{p.engineering ? "工程与固定版本工单" : "订单与需求"}</h3>
      {error && <p role="alert">{error}</p>}
      <div className="mf-actions">
        {!p.readOnly &&
          available.map((a) => (
            <button
              key={a}
              onClick={() =>
                p.requestLeave(() => {
                  setAction(a as CommandFields["action"]);
                  setEpoch((e) => e + 1);
                })
              }
            >
              {actions[a]}
            </button>
          ))}
      </div>
      <div className="mf-actions">
        {(Object.keys(items) as OrdersKind[])
          .filter((k) => items[k].length < (totals[k] || 0))
          .map((k) => (
            <button key={k} disabled={loading[k]} onClick={() => void more(k)}>
              读取更多{label(k)}（已读取 {items[k].length} / {totals[k]}
              ，可供表单选择）
            </button>
          ))}
      </div>
      {action && (
        <>
          <button
            onClick={() =>
              p.requestLeave(() => {
                setAction(null);
                setEpoch((e) => e + 1);
                p.onReload?.();
              })
            }
          >
            放弃草稿并重新读取
          </button>
          {p.engineering ? (
            <EngineeringForms
              key={p.project.id + action + epoch}
              {...formProps}
              action={action}
            />
          ) : (
            <OrdersForms key={p.project.id + action + epoch} {...formProps} action={action} />
          )}
        </>
      )}
      {(p.engineering
        ? ["revision", "work_order", "eco"]
        : ["demand", "order_line", "commitment_change"]
      ).map((k) => (
        <section key={k}>
          <h4>{label(k)}</h4>
          {items[k as OrdersKind].length ? (
            <ObjectTable items={items[k as OrdersKind]} onOpen={p.onOpen} />
          ) : (
            <p>尚无{label(k)}记录</p>
          )}
        </section>
      ))}
    </section>
  );
}
