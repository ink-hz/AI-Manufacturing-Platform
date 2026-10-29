import { useEffect, useState } from "react";
import type {
  AssistanceKind,
  AssistanceResult,
  AssistanceTarget,
  PublicAssetEntry,
  WorkflowTarget,
} from "./types";
import type { WorkflowApi } from "./api";
import { Source } from "./WorkflowDetail";
import { AssetContentView } from "./details/IntroductionDetails";
import { ParameterTable } from "./details/LaboratoryDetails";
import { label, objectStateLabel } from "./labels";
export const assistanceModes: Record<AssistanceKind, string> = {
  introduction: "导入证据",
  materials: "物料与收货",
  change: "变更影响",
  knowledge: "资产适用性",
  testing: "测试证据",
  quality: "质量 8D 证据草稿",
};
export function AssistancePanel({
  api,
  projectId,
  version,
  onOpen,
  initialKind = "introduction",
}: {
  api: WorkflowApi;
  projectId: string;
  version: number;
  onOpen(t: WorkflowTarget): void;
  initialKind?: AssistanceKind;
}) {
  const [kind, setKind] = useState<AssistanceKind>(initialKind),
    [data, setData] = useState<AssistanceResult | null>(null),
    [error, setError] = useState(""),
    [retry, setRetry] = useState(0),
    [publicEntry, setPublicEntry] = useState<PublicAssetEntry | null>(null);
  useEffect(() => {
    const c = new AbortController();
    setData(null);
    setError("");
    setPublicEntry(null);
    api
      .assistance(projectId, kind, c.signal)
      .then((d) => {
        if (!c.signal.aborted) setData(d);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(String(e));
      });
    return () => c.abort();
  }, [api, projectId, version, kind, retry]);
  function target(t: AssistanceTarget, entry?: PublicAssetEntry | null) {
    if (t.scope === "public_catalog") {
      if (entry && entry.asset_revision_id === t.id) setPublicEntry(entry);
      return;
    }
    if (t.project_id)
      onOpen({ projectId: t.project_id, kind: t.kind, id: t.id });
  }
  const link = (
    t: AssistanceTarget,
    text: string,
    entry?: PublicAssetEntry | null,
  ) => (
    <button
      type="button"
      disabled={t.scope === "public_catalog" && !entry}
      onClick={() => target(t, entry)}
    >
      {text}
    </button>
  );
  return (
    <section className="wf-panel" aria-label="规则分析">
      <h3>规则分析 · 只读证据辅助</h3>
      <label>
        分析范围
        <select
          aria-label="分析范围"
          value={kind}
          onChange={(e) => setKind(e.target.value as AssistanceKind)}
        >
          {Object.entries(assistanceModes).map(([k, title]) => (
            <option value={k} key={k}>
              {title}
            </option>
          ))}
        </select>
      </label>
      <button type="button" onClick={() => setRetry((n) => n + 1)}>
        刷新规则分析
      </button>
      <p>
        依据当前授权项目与已批准公共内容提供核对建议；不执行 AI
        模型、设备动作、原因验证或客户批准。
      </p>
      {error ? (
        <p role="alert">{error}</p>
      ) : !data ? (
        <p role="status">正在读取规则证据…</p>
      ) : (
        <>
          <p>
            {data.state === "no_evidence" ? "暂无适用证据" : "已读取登记证据"} ·{" "}
            {data.truncated
              ? "分析范围有界，部分证据未纳入"
              : "本次范围未报告截断"}
          </p>
          {data.unknowns.map((text, i) => (
            <p key={i}>{text}</p>
          ))}
          {data.items.map((item, i) => (
            <details
              key={`${item.target.scope}-${item.target.id}-${i}`}
              open={data.items.length === 1}
            >
              <summary>
                {item.title} · {objectStateLabel(item.state, item.target.kind)}
              </summary>
              <p>{item.suggestion}</p>
              {link(
                item.target,
                item.target.scope === "public_catalog"
                  ? "查看公共内容"
                  : "查看依据记录",
                item.public_asset,
              )}
              {item.blockers.map((r, n) => (
                <p key={n}>阻断：{r}</p>
              ))}
              {item.unknowns.map((r, n) => (
                <p key={n}>未知：{r}</p>
              ))}
              {item.evidence_truncated && (
                <p>此记录证据有界，完整历史请查看依据记录。</p>
              )}
              {item.evidence.map((r, n) => (
                <p key={n}>凭据：{r}</p>
              ))}
              {item.source && <Source value={item.source} />}{" "}
              {item.quantities && (
                <p>
                  合格 {item.quantities.accepted} · 拒收{" "}
                  {item.quantities.rejected} · 待检 {item.quantities.pending}{" "}
                  {item.quantities.unit}
                </p>
              )}
              {item.material_balance && (
                <p>
                  需求 {item.material_balance.required} · 在途{" "}
                  {item.material_balance.in_transit} · 实收{" "}
                  {item.material_balance.received} · 合格{" "}
                  {item.material_balance.qualified} · 已预留{" "}
                  {item.material_balance.reserved} · 缺口{" "}
                  {item.material_balance.shortage} {item.material_balance.unit}
                </p>
              )}
              {item.testing && (
                <section>
                  <p>
                    运行生命周期{" "}
                    {item.testing.run_state
                      ? objectStateLabel(item.testing.run_state, "test_run")
                      : "不适用"}{" "}
                    · 历史判定{" "}
                    {item.testing.outcome
                      ? label(item.testing.outcome)
                      : "无判定"}{" "}
                    · 当前资格{" "}
                    {item.testing.current_qualified === null
                      ? "未知（查看关联质量测试）"
                      : item.testing.current_qualified
                        ? "有效"
                        : "无效"}
                  </p>
                  <p>
                    比较依据：相同固定修订与程序 {item.testing.program_version}
                    ；相似不代表因果。
                  </p>
                  <ParameterTable
                    title="实际测试测量"
                    items={item.testing.measurements}
                  />
                  <ParameterTable
                    title="超出限值的测量"
                    items={item.testing.failed_measurements}
                  />
                  {item.testing.similar_targets.map((t, n) => (
                    <span key={n}>{link(t, "查看同范围测试")}</span>
                  ))}
                </section>
              )}
              {item.quality_outline && (
                <section>
                  <h4>8D 证据草稿</h4>
                  {item.quality_outline.facts.map((t, n) => (
                    <p key={n}>{t}</p>
                  ))}
                  {(
                    [
                      "containment",
                      "registered_causes",
                      "actions",
                      "verification",
                    ] as const
                  ).map((key) => (
                    <section key={key}>
                      <h5>
                        {
                          {
                            containment: "遏制",
                            registered_causes: "已登记原因",
                            actions: "行动",
                            verification: "验证记录",
                          }[key]
                        }
                      </h5>
                      {item.quality_outline![key].map((step) => (
                        <p key={step.sequence}>
                          {step.description} · {step.evidence} · 实施{" "}
                          {step.implementation_evidence || "未提供"} · 有效性{" "}
                          {step.effective === null
                            ? "未登记"
                            : step.effective
                              ? "登记为有效"
                              : "登记为无效"}
                        </p>
                      ))}
                    </section>
                  ))}
                  <p>
                    处置 {item.quality_outline.disposition || "未登记"} ·{" "}
                    {item.quality_outline.disposition_evidence}
                  </p>
                  <p>
                    缺失字段：{item.quality_outline.missing_fields.join("、")}
                  </p>
                </section>
              )}
              {item.related_targets.map((t, n) => (
                <span key={n}>{link(t, `关联${label(t.kind)}`)}</span>
              ))}
            </details>
          ))}
        </>
      )}
      {publicEntry && (
        <section aria-label="公共资产内容">
          <h4>已批准公共资产 · 修订 {publicEntry.revision}</h4>
          <AssetContentView value={publicEntry.content} />
          <button type="button" onClick={() => setPublicEntry(null)}>
            关闭公共内容
          </button>
        </section>
      )}
    </section>
  );
}
