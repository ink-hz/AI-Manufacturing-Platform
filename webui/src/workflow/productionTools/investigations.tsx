import "./details.css";
import { Badge, ResultBadge } from "./visuals";
import { useEffect, useRef, useState } from "react";
import { fieldNames, localTime, text } from "./context";
import { useInvestigation } from "./investigationState";
import type { Resolution, ViewedEvent } from "./types";

const descriptorNames: Record<string, string> = {
  timestamp: "事件时间",
  time: "事件时间",
  sn: "SN",
  barcode: "条码",
  status: "结果",
  workstagesid: "阶段",
  softwareid: "工具",
  version: "软件版本",
  configlogsid: "配置",
  cversion: "配置版本",
  devicename: "上位机",
  errorcode: "错误码",
  orderid: "工具配置审核单",
  workselectid: "测试项选择",
  softwarename: "工具名称",
};
const descriptorEntries = (row: Record<string, unknown>) =>
  Object.entries(row).filter(([key]) => key in descriptorNames);
export { useInvestigation } from "./investigationState";
export { clearProductionResume } from "./resume";
export type InvestigationController = ReturnType<typeof useInvestigation>;
const logStateLabel = new Map([["verified", "已核对"], ["ambiguous", "多条候选，待核对"], ["changed", "内容变化，待核对"], ["not_found", "未找到"], ["partial", "未查全"], ["unavailable", "暂不可用"], ["unverified", "未核对"]]);
const stateLabel: Record<Resolution["state"], string> = {
  verified: "内容已核对",
  ambiguous: "事件待核对：多条候选",
  changed: "事件待核对：源内容可能变化",
  not_found: "事件待核对：未找到",
  partial: "事件待核对：尚未查全",
  unavailable: "事件待核对：源暂不可用",
};
export function InvestigationPanel({
  controller: c,
  readOnly,
  onCompare,
  onCandidate,
  restoreFocusRequest = 0,
  projectName,
  scopeLabels = {},
}: {
  controller: InvestigationController;
  readOnly: boolean;
  onCompare: () => void;
  onCandidate: (event: ViewedEvent) => void;
  restoreFocusRequest?: number;
  projectName?: string;
  scopeLabels?: Record<string, string>;
}) {
  const d = c.handoff || c.draft;
  const [restoreText, setRestoreText] = useState(""),
    [linkError, setLinkError] = useState(""),
    [copyState, setCopyState] = useState("");
  const restoreInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (restoreFocusRequest) restoreInput.current?.focus();
  }, [restoreFocusRequest]);
  return (
    <section className="pt-investigation" aria-label="当前调查">
      <header className="pt-section-heading">
        <div><h3>当前调查</h3>
          <p role="status"><Badge tone={c.conflict || c.error || c.dirty || c.browsingOtherScope ? "warning" : "info"}>{c.state.startsWith("已保存") ? "已保存" : c.state.startsWith("当前浏览条件") ? "当前浏览条件与调查不同" : c.state.startsWith("修订冲突") ? "修订冲突" : c.state}</Badge>{readOnly ? " · 只读管理员" : ""}</p>
        </div>
        <div className="pt-actions">
          <button
            type="button"
            disabled={readOnly || !!c.handoff || !c.canStart}
            onClick={() => void c.start()}
          >
            开始调查
          </button>
          <button
            type="button"
            className="pt-button-primary"
            disabled={readOnly || !!c.handoff || (!c.draft && !c.canStart)}
            onClick={() => void c.generate()}
          >
            生成交接摘要
          </button>
          {c.dirty && (
            <button
              type="button"
              disabled={readOnly || !!c.conflict}
              onClick={() => void c.flush(true)}
            >
              {c.localRecovered ? "提交本机修改" : "重试保存"}
            </button>
          )}
        </div>
      </header>
      {(c.browsingOtherScope || c.state.includes("当前浏览条件")) && (
        <div className="pt-callout" data-tone="warning">
          <p>当前浏览范围与已保存调查不同。</p>
          <button
            type="button"
            disabled={readOnly}
            onClick={c.applyBrowsingScope}
          >
            将浏览条件应用到当前调查
          </button>
          <button type="button" onClick={c.returnToSaved}>
            返回原调查范围
          </button>
          <button
            type="button"
            disabled={readOnly}
            onClick={() => void c.newRange()}
          >
            按浏览条件新建调查
          </button>
        </div>
      )}
      {c.error && <p role="alert">{c.error}</p>}
      {d && (
        <>
          <section className="pt-investigation-meta" aria-label="调查范围">
            <h4>调查范围</h4>
            <p>
              {c.handoff ? "固定交接号" : "个人调查号"} {d.id}{c.handoff ? ` · 版本 ${d.version}` : ""}{" "}
              · 有效至 {localTime(d.expires_at)}
            </p>
            <p>
              {projectName || "已保存项目"} · 问题时间{" "}
              {localTime(d.context.start)} — {localTime(d.context.end)}
            </p>
            {d.context.symptom && <p>{d.context.symptom}</p>}
            <p>
              {Object.entries(fieldNames)
                .flatMap(([key, label]) =>
                  d.context.missing_fields?.includes(key as never)
                    ? [`${label}：源未提供`]
                    : (d.context as unknown as Record<string, unknown>)[key] !==
                      undefined
                      ? [
                        `${label}：${scopeLabels[key] || text((d.context as unknown as Record<string, unknown>)[key])}`,
                      ]
                      : [],
                )
                .join(" · ")}
            </p>
            {d.origin_handoff_id && (
              <p>
                接续自交接 {d.origin_handoff_id} · 版本 {d.origin_handoff_version}
              </p>
            )}
          </section>
          {c.handoff && (
            <section className="pt-detail-section pt-handoff-snapshot" aria-label="固定交接内容">
              <h4>交接时内容 · 不随源更新</h4>
              <p>{d.note}</p>
              <button
                type="button"
                disabled={readOnly}
                onClick={() => void c.fork()}
              >
                另存为我的调查
              </button>
              <button type="button" onClick={() => c.closeHandoff()}>
                返回我的调查
              </button>
              <button
                type="button"
                onClick={async () => {
                  const url = new URL(location.href);
                  url.search = "";
                  url.hash = "";
                  url.searchParams.set("production_handoff", d.id);
                  const scopeText = Object.entries(fieldNames)
                    .flatMap(([key, label]) => {
                      const value = (
                        d.context as unknown as Record<string, unknown>
                      )[key];
                      return d.context.missing_fields?.includes(key as never)
                        ? [`${label}：源未提供`]
                        : value !== undefined
                          ? [`${label}：${scopeLabels[key] || text(value)}`]
                          : [];
                    })
                    .join(" · ");
                  const describe = (which: "primary" | "comparison") => {
                    const event = d[which];
                    return `${which === "primary" ? "主要事件" : "对照事件"}：${event
                        ? descriptorEntries(event.descriptor)
                          .map(([k, v]) => `${descriptorNames[k]}=${text(v)}`)
                          .join(" · ")
                        : "尚未选择"
                      }`;
                  };
                  const impact = d.impact
                    ? `交接时影响：失败记录 ${d.impact.failure_records.numerator ?? "未知"} / ${d.impact.failure_records.denominator ?? "未知"}；失败涉及 SN ${d.impact.failed_involved_sn.numerator ?? "未知"} / ${d.impact.failed_involved_sn.denominator ?? "未知"}${d.impact.state !== "available" ? "；部分统计未取得" : ""}`
                    : "交接时影响统计未取得";
                  const summary = [
                    `交接号 ${d.id} · 版本 ${d.version}`,
                    `生成 ${localTime(d.created_at)} · 有效至 ${localTime(d.expires_at)}`,
                    projectName || "已保存项目",
                    d.context.symptom || "",
                    `问题时间 ${localTime(d.context.start)} — ${localTime(d.context.end)}`,
                    scopeText,
                    describe("primary"),
                    describe("comparison"),
                    `日志引用：${d.logs.map((log) => `${log.source_log_id}（CSN ${text(log.descriptor.csn)}，关联待核对）`).join("、") || "尚未选择，证据缺口待确认"}`,
                    impact,
                    `观察事实和待确认事项：${d.note}`,
                    url.href,
                  ].join("\n");
                  try {
                    await navigator.clipboard.writeText(summary);
                    setCopyState("已复制交接摘要与恢复链接");
                  } catch {
                    setCopyState(summary);
                  }
                }}
              >
                复制交接摘要与恢复链接
              </button>
              {copyState && <p role="status">{copyState}</p>}
            </section>
          )}
          {d.impact && (
            <section className="pt-detail-section" aria-label="保存时影响统计">
              <h4>保存时影响统计</h4>
              {d.impact.state !== "available" && <p>部分统计未取得，请复查证据。</p>}
              <p>
                失败记录 {d.impact.failure_records.numerator ?? "未知"} /
                同范围全部测试 {d.impact.failure_records.denominator ?? "未知"}{" "}
                · 失败涉及 SN {d.impact.failed_involved_sn.numerator ?? "未知"}{" "}
                / 测试 SN {d.impact.failed_involved_sn.denominator ?? "未知"}
              </p>
            </section>
          )}
          <div className="pt-event-pair">
            {(["primary", "comparison"] as const).filter(which => d[which]).map((which) => (
              <section key={which} className="pt-event-role" data-role={which} aria-label={which === "primary" ? "主要事件" : "对照事件"}>
                <h4>
                  {which === "primary"
                    ? "主要事件"
                    : "对照事件"}
                </h4>
                {d[which] ? (
                  <>
                    <p className="pt-meta">保存时结果 <ResultBadge value={d[which]!.descriptor.status} /></p>
                    <p>
                      {text(d[which]!.descriptor.sn)} ·{" "}
                      {localTime(d[which]!.descriptor.timestamp)} ·{" "}
                      {text(d[which]!.descriptor.devicename)}
                    </p>
                    <details>
                      <summary>事件信息</summary>
                      <dl>
                        {descriptorEntries(d[which]!.descriptor).map(
                          ([key, value]) => (
                            <div key={key}>
                              <dt>{descriptorNames[key]}</dt>
                              <dd>
                                {key === "timestamp" ? localTime(value) : key === "status" ? <ResultBadge value={value} /> : text(value)}
                              </dd>
                            </div>
                          ),
                        )}
                      </dl>
                    </details>
                    <p><Badge tone={c.resolved?.[which]?.state === "verified" ? "info" : "warning"}>
                      {c.resolved?.[which] ? stateLabel[c.resolved[which]!.state] : "事件待核对；尚未恢复原参数"}
                    </Badge></p>
                    {c.resolved?.[which]?.candidates.map((candidate, i) => (
                      <button
                        type="button"
                        key={`${candidate.snapshot_id}-${candidate.offset}`}
                        onClick={() =>
                          onCandidate({
                            ...candidate,
                            projectId: d.source_project_id,
                            kind: d[which]!.source_kind,
                            captured_at: c.resolved!.captured_at,
                          })
                        }
                      >
                        核对{which === "primary" ? "主要" : "对照"}候选 {i + 1}
                      </button>
                    ))}
                    {which === "comparison" && (
                      <button
                        type="button"
                        disabled={readOnly || !!c.handoff || !c.canStart}
                        onClick={() => void c.removeComparison()}
                      >
                        移除对照
                      </button>
                    )}
                  </>
                ) : null}
              </section>
            ))}
          </div>
          <section className="pt-detail-section" aria-label="证据复查与比较">
            <h4>证据复查与比较</h4>
            <button type="button" onClick={c.resolve}>
              按原条件复查证据
            </button>
            <button
              type="button"
              disabled={!d.primary || !d.comparison}
              onClick={onCompare}
            >
              比较已选记录
            </button>
          </section>
          {!!d.logs.length && <section className="pt-detail-section pt-investigation-logs" aria-label="日志引用">
            <header className="pt-detail-heading"><h4>日志引用（{d.logs.length} / 5）· 关联待核对</h4></header>
            {d.logs.map((log) => (
              <div className="pt-log-reference" key={log.source_log_id}>
                {log.source_log_id} · CSN {text(log.descriptor.csn)} ·{" "}
                {log.match_basis === "project_time_and_explicit_csn"
                  ? "项目、时间与显式 CSN"
                  : "项目与时间"}{" "}
                ·{" "}
                {logStateLabel.get(c.resolved?.logs.find(
                  (x) => x.source_log_id === log.source_log_id,
                )?.state || "unverified") || "待核对"}
                <button
                  type="button"
                  disabled={readOnly || !!c.handoff || !c.canStart || c.logBusy}
                  onClick={() => void c.removeLog(log.source_log_id)}
                >
                  移除日志 {log.source_log_id}
                </button>
              </div>
            ))}
          </section>}
        </>
      )}
      <section className="pt-detail-section" aria-label="调查备注">
        <h4>调查备注</h4>
        <label>
          观察事实和待确认事项
          <textarea
            aria-label="观察事实和待确认事项"
            maxLength={4000}
            disabled={readOnly || !!c.handoff || !c.canStart}
            value={c.note}
            onChange={(e) => c.setNote(e.target.value)}
          />
        </label>
      </section>
      {c.conflict && (
        <aside role="alert">
          <h4>修订冲突</h4>
          <p>
            服务端内容：{c.conflict.note}
          </p>
          <p>本机修改：{c.note}</p>
          <button type="button" onClick={() => void c.acceptServer()}>
            采用服务端版本
          </button>
          <button type="button" onClick={() => void c.retainLocal()}>
            核对后提交本机修改
          </button>
        </aside>
      )}
      {!!c.list.length && <section className="pt-detail-section" aria-label="继续我的其他草稿">
        <h4>继续我的其他草稿</h4>
        {c.list.map((d) => (
          <button type="button" key={d.id} onClick={() => void c.restore(d.id)}>
            继续调查 {d.context.symptom || d.note || d.id}
          </button>
        ))}
      </section>}
      <section className="pt-detail-section pt-handoff-recovery" aria-label="交接与恢复">
        <h4>恢复调查</h4>
        <label>
          交接号或内部恢复链接
          <input
            ref={restoreInput}
            aria-label="交接号或内部恢复链接"
            value={restoreText}
            onChange={(e) => setRestoreText(e.target.value)}
          />
        </label>
        <button
          type="button"
          onClick={() => {
            let id = restoreText.trim();
            try {
              if (id.includes("://")) {
                const u = new URL(id);
                if (u.origin !== location.origin) throw Error();
                id = u.searchParams.get("production_handoff") || "";
              }
              if (
                !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
                  id,
                )
              )
                throw Error();
              setLinkError("");
              void c.restore(id, true);
            } catch {
              setLinkError("请输入有效交接号或本站内部恢复链接");
            }
          }}
        >
          读取交接
        </button>
        {linkError && <p role="alert">{linkError}</p>}
      </section>
    </section>
  );
}
