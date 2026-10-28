import type { Dashboard, WorkflowTarget } from "./types";
import { ObjectTable } from "./OrdersWorkspace";
import { label } from "./forms/shared";
export function WorkflowHome({
  data,
  onOpen,
}: {
  data: Dashboard;
  onOpen(t: WorkflowTarget): void;
}) {
  return (
    <section>
      <h2>授权项目业务概览</h2>
      <dl className="wf-facts">
        {Object.entries(data.counts).map(([k, v]) => (
          <div key={k}>
            <dt>{label(k)}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      {data.cards?.length ? (
        <ObjectTable items={data.cards} onOpen={onOpen} />
      ) : (
        <p>暂无业务记录。请选择制造项目开始登记需求与工程资料。</p>
      )}
    </section>
  );
}
