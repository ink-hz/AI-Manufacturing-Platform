import type { ObjectDetail, WorkflowTarget, AssetContent } from "../types";
import { label } from "../labels";
export function AssetContentView({ value: v }: { value: AssetContent }) {
  return (
    <section>
      <h4>{v.title}</h4>
      <p>
        {label(v.category)} · 适用产品族：{v.product_families.join("、")}
      </p>
      <h5>执行内容</h5>
      <p>{v.execution_content}</p>
      <h5>验证方法</h5>
      <p>{v.verification_method}</p>
    </section>
  );
}
export function IntroductionDetails({
  data,
  onOpen,
}: {
  data: ObjectDetail;
  onOpen(t: WorkflowTarget): void;
}) {
  const v = data.value;
  const open = (kind: WorkflowTarget["kind"], id: string, text: string) => (
    <button
      type="button"
      onClick={() => onOpen({ projectId: data.summary.project_id, kind, id })}
    >
      {text}
    </button>
  );
  if (v.kind === "npi")
    return (
      <section>
        <p>
          产品族：{v.product_family} · {label(v.scenario)}
        </p>
        {open("revision", v.revision_id, "查看导入固定修订")}
        <p>历史导入状态：{label(v.state)}</p>
        <p>当前批量资格：{v.bulk_eligible ? "具备当前资格" : "当前受阻"}</p>
        {v.blocking_reasons.map((r, i) => (
          <p key={i}>{r}</p>
        ))}
        <p>必需检查：{v.required_checks.join("、")}</p>
        {v.work_order_ids.map((id) => (
          <span key={id}>{open("work_order", id, "查看参与工单")}</span>
        ))}
        <h4>评审历史</h4>
        {v.reviews.map((r) => (
          <section key={r.id}>
            <p>
              {r.recorded_at} · {r.actor_id}
            </p>
            <table>
              <thead>
                <tr>
                  <th>检查</th>
                  <th>必需</th>
                  <th>结论</th>
                  <th>证据</th>
                  <th>理由</th>
                </tr>
              </thead>
              <tbody>
                {r.checks.map((c) => (
                  <tr key={c.code}>
                    <td>{c.code}</td>
                    <td>{c.required ? "是" : "否"}</td>
                    <td>{label(c.decision)}</td>
                    <td>{c.evidence}</td>
                    <td>{c.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ))}
        <h4>试做历史与当前资格</h4>
        {v.trials.map((r) => (
          <section key={r.id}>
            {open("work_order", r.work_order_id, "查看试做工单")}
            <p>
              历史结果 {label(r.outcome)} · 当前资格{" "}
              {r.qualified ? "有效" : "无效"} · {r.evidence} · {r.actor_id} ·{" "}
              {r.recorded_at}
            </p>
            {r.test_ids.map((id) => (
              <span key={id}>{open("test", id, "查看试做测试")}</span>
            ))}
          </section>
        ))}
        <h4>批准历史</h4>
        {v.approvals.map((r) => (
          <p key={r.id}>
            证据代次 {r.generation} · {r.evidence} · {r.actor_id} ·{" "}
            {r.recorded_at}
          </p>
        ))}
      </section>
    );
  if (v.kind === "npi_issue")
    return (
      <section>
        {open("npi", v.npi_id, "查看所属导入")}
        <p>现象：{v.phenomenon}</p>
        <p>风险：{v.risk}</p>
        <p>遏制：{v.containment}</p>
        <p>
          当前解决验证：{v.verified ? "有效" : "未具备当前有效验证"} ·{" "}
          {label(v.state)}
        </p>
        <h4>完整解决验证历史</h4>
        {v.resolutions.map((r, i) => (
          <section key={i}>
            <h5>
              {i === v.resolutions.length - 1 ? "当前依据" : "历史依据"} ·{" "}
              {i + 1}
            </h5>
            <p>已验证原因：{r.verified_cause}</p>
            <p>对策：{r.countermeasure}</p>
            <p>
              {r.verification_evidence} · {r.actor_id} · {r.recorded_at}
            </p>
            {r.test_ids.map((id) => (
              <span key={id}>{open("test", id, "查看验证测试")}</span>
            ))}
          </section>
        ))}
      </section>
    );
  if (v.kind === "reusable_asset")
    return (
      <section>
        <p>
          固定修订 {v.revision} · {v.published_by} · {v.published_at}
        </p>
        <AssetContentView value={v.content} />
        {open("npi_issue", v.issue_id, "查看授权来源问题")}
        {v.supersedes_id &&
          open("reusable_asset", v.supersedes_id, "查看前一资产修订")}
        {v.public_content && (
          <details>
            <summary>单独批准的公共内容</summary>
            <AssetContentView value={v.public_content} />
          </details>
        )}
      </section>
    );
  if (v.kind === "asset_use")
    return (
      <section>
        {open("npi", v.npi_id, "查看采用目标导入")}
        <p>
          采用固定修订 {v.revision} · {v.required ? "必需检查" : "可选检查"}
        </p>
        <AssetContentView value={v.snapshot} />
        <p>采用快照独立保留；源资产后续变化不改写此内容。</p>
        <h4>独立验证历史</h4>
        {v.verifications.map((r) => (
          <p key={r.id}>
            {label(r.decision)} · {r.evidence} · {r.actor_id} · {r.recorded_at}
          </p>
        ))}
      </section>
    );
  return null;
}
