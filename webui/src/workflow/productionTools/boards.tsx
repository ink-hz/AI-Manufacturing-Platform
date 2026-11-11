import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import type { createWorkflowApi } from "../api";
import type { Aggregate, Analysis, OverviewItem, Scope, ViewedEvent } from "./types";
import {
  baseline,
  drill,
  localTime,
  previousDay,
  recent,
  text,
  useRead,
  type Location,
  type Read,
} from "./context";
import { Records } from "./details";
import { Metric, Panel, EmptyState, boundedPercent } from "./visuals";
import { TrendChart, RankingBar, maximum } from "./charts";
import "./boards.css";
export type Api = ReturnType<typeof createWorkflowApi>;
export interface BoardProps {
  api: Api;
  location: Location;
  go: (next: Location, intent?: "browse" | "scope") => void;
  inspect: (event: ViewedEvent) => void;
  refresh: number;
  onRecent?: (scope: Scope) => void;
  onOverviewRefresh?: () => void;
}
export function ReadBlock<T>({
  state,
  children,
  label,
}: {
  state: Read<T> & { retry: () => void };
  children: (data: T) => ReactNode;
  label: string;
}) {
  return (
    <section className="pt-read-block" aria-label={label}>
      {state.loading && <p role="status">正在读取{label}…</p>}
      {state.error && (
        <p role="alert">
          {label}：{state.error}
          <button type="button" onClick={state.retry}>
            重试{label}
          </button>
        </p>
      )}
      {state.data && (
        <>
          {(state.loading || state.error) && (
            <p className="pt-meta">
              显示上次数据，尚未更新。
            </p>
          )}
          {children(state.data)}
        </>
      )}
    </section>
  );
}
export function Coverage({
  data,
}: {
  data: { captured_at: string; complete: boolean; truncation_reason?: string | null };
}) {
  return (
    <div className="pt-read-meta">
      <UpdatedAt capturedAt={data.captured_at} />
      {!data.complete && <p className="pt-meta pt-coverage" data-complete="false">部分数据未取得；遗漏分组和时间格未知，不能视为零{data.truncation_reason ? `（${data.truncation_reason}）` : ""}</p>}
    </div>
  );
}
function UpdatedAt({ capturedAt }: { capturedAt: string }) {
  return <span className="pt-meta pt-updated">更新 <time dateTime={capturedAt} title={localTime(capturedAt)}>{new Date(capturedAt).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })}</time></span>;
}
function DeferredDetails({ children, summary, className }: { children: ReactNode; summary: string; className: string }) {
  const [open, setOpen] = useState(false);
  return <details className={className} onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>{summary}</summary>{open && <div>{children}</div>}
  </details>;
}
function StatisticsHelp({ children }: { children: ReactNode }) {
  return <DeferredDetails className="pt-statistics-help" summary="统计说明">{children}</DeferredDetails>;
}

export function Counts({ item }: { item: Aggregate | null }) {
  return item ? <div className="pt-counts-summary">
    <div className="pt-counts">
      <Metric label="测试次数" value={item.records} tone="info" />
      <Metric label="测试 SN" value={item.distinct_sn} />
      <Metric label="失败 SN" value={item.failed_sn} tone="danger" />
      <Metric label="其中失败" value={item.fail_records} tone="danger" detail={item.denominator_records ? `适用样本 ${item.denominator_records}` : undefined} />
    </div>
    <p className="pt-meta">通过 {item.pass_records} · 未知 {item.unknown_records}</p>
  </div> : <EmptyState title="统计未取得，不能计作零" />;
}
export function OverviewBoard({
  api,
  location,
  go,
  refresh,
  onOverviewRefresh,
}: BoardProps) {
  const [before, setBefore] = useState<string>(),
    [sort, setSort] = useState("failed"),
    [auto, setAuto] = useState(true);
  const task = location.view === "catalog" ? "catalog" : location.view === "activity" ? "activity" : "anomalies";
  const chooser = location.view === "anomalies" || location.view === "activity" || location.view === "catalog";
  const taskLabel = task === "catalog" ? "版本使用" : task === "activity" ? "现场上位机" : "失败分析";
  const taskAction = task === "catalog" ? "查看版本" : task === "activity" ? "查看上位机" : "查看失败";
  const title = chooser ? `${taskLabel} · 选择项目` : "项目测试概况";
  const state = useRead(
    (s) =>
      api
        .productionOverview(
          {
            start: location.scope.start,
            end: location.scope.end,
            before_id: before,
          },
          s,
        )
        .then((data) => ({
          ...data,
          requested_scope: {
            start: location.scope.start,
            end: location.scope.end,
          },
        })),
    [api, location.scope.start, location.scope.end, before, refresh],
    true,
    [
      api,
      location.scope.start,
      location.inherited ? location.scope.end : "live",
      before,
    ],
  );
  useEffect(() => {
    if (!auto) return;
    const timer = setInterval(() => onOverviewRefresh?.(), 60000);
    return () => clearInterval(timer);
  }, [auto, onOverviewRefresh]);
  return (
    <>
      <header className="pt-board-heading"><h3>{title}</h3></header><div className="pt-board-tools">
      <label>
        <input
          type="checkbox"
          checked={auto}
          onChange={(e) => setAuto(e.target.checked)}
        />
        每 60 秒更新
      </label>
      <label>
        项目排序
        <select value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="failed">失败 SN</option>
          <option value="latest">最近测试时间</option>
        </select>
      </label>
      </div><ReadBlock label={chooser ? title : "运行总览"} state={state}>
        {(data) => {
          const rows = [...data.items].sort((a, b) =>
            sort === "latest"
              ? (b.latest_at || "").localeCompare(a.latest_at || "")
              : BigInt(a.statistics?.failed_sn || "0") >
                  BigInt(b.statistics?.failed_sn || "0")
                ? -1
                : 1,
          );
          const valid = data.items.filter(
            (p) => p.statistics && p.blocks.statistics.complete && p.blocks.statistics.state === "ready",
          );
          const sum = (key: "records" | "distinct_sn" | "failed_sn") =>
            valid
              .reduce((n, p) => n + BigInt(p.statistics![key]), 0n)
              .toString();
          const knownZero = (p: OverviewItem) => !!p.statistics && p.blocks.statistics.complete && p.blocks.statistics.state === "ready" && BigInt(p.statistics.records) === 0n;
          const zero = rows.filter(knownZero), visible = rows.filter((p) => !knownZero(p));
          const openProject = (p: OverviewItem, view: Location["view"]) => go({
            ...location,
            catalog: view === "catalog" ? location.catalog : undefined,
            parentId: undefined,
            scope: data.requested_scope,
            selectedError: false,
            selectedStage: false,
            cursor: undefined,
            view,
            projectId: p.id,
            labels: { project: p.name },
            parentRead: p.statistics ? {
              captured_at: p.blocks.statistics.captured_at,
              records: p.statistics.records,
              distinct_sn: p.statistics.distinct_sn,
              scope: data.requested_scope,
            } : undefined,
            inherited: true,
          });
          const latest = (p: OverviewItem) => p.blocks.latest.state === "unavailable" ? "未取得" : localTime(p.latest_at);
          return (
            <>
              <Coverage data={data} />
              {(valid.length !== data.items.length || data.has_more || before) && <p className="pt-meta pt-overview-limit">仅汇总本页完整统计（{valid.length}/{data.items.length} 项目）{data.has_more ? "；还有后续项目" : ""}{before ? "；当前为后续页" : ""}</p>}
              <div className="pt-metrics" aria-label="本页完整项目统计">
                <Metric label="有测试项目" value={valid.length || (!data.items.length && data.complete) ? String(valid.filter((p) => BigInt(p.statistics!.records) > 0n).length) : null} />
                <Metric label="测试次数" value={valid.length || (!data.items.length && data.complete) ? sum("records") : null} tone="info" />
                <Metric label="测试 SN" value={valid.length || (!data.items.length && data.complete) ? sum("distinct_sn") : null} />
                <Metric label="失败 SN" value={valid.length || (!data.items.length && data.complete) ? sum("failed_sn") : null} tone="danger" />
              </div>
              {!data.items.length && data.complete && <p>源项目目录暂无项目</p>}
              {!!visible.length && <div className="pt-table pt-project-table" role="region" aria-label="项目测试统计" tabIndex={0}><table>
                <thead><tr>{["项目", "测试次数", "测试 SN", "失败 SN", "失败次数", "最近测试", "操作"].map((label) => <th scope="col" key={label}>{label}</th>)}</tr></thead>
                <tbody>{visible.map((p) => {
                  const unavailable = !p.statistics || p.blocks.statistics.state === "unavailable";
                  const partial = !unavailable && (!p.blocks.statistics.complete || p.blocks.statistics.state === "partial");
                  return <tr key={p.id}>
                    <th scope="row"><button type="button" className="pt-project-name" onClick={() => openProject(p, chooser ? task : "project")}>{p.name}</button>
                      {(unavailable || partial) && <span className="pt-project-warning">{unavailable ? "统计未取得" : "统计未完整"}{p.blocks.statistics.error || p.blocks.statistics.truncation_reason ? `：${p.blocks.statistics.error || p.blocks.statistics.truncation_reason}` : ""}</span>}
                    </th>
                    {(["records", "distinct_sn", "failed_sn", "fail_records"] as const).map((key) => <td key={key} data-failed={(key === "failed_sn" || key === "fail_records") && !unavailable && BigInt(p.statistics![key]) > 0n}>{unavailable ? "—" : p.statistics![key]}</td>)}
                    <td>{latest(p)}{p.blocks.latest.state === "partial" && <span className="pt-project-warning">时间未完整</span>}</td>
                    <td><button type="button" className="pt-button-primary" onClick={() => openProject(p, task)}>{taskAction}</button></td>
                  </tr>;
                })}</tbody>
              </table></div>}
              {!!zero.length && <DeferredDetails className="pt-zero-projects" summary={`本时段无测试的项目（${zero.length}）`}>
                <ul>{zero.map((p) => <li key={p.id}>
                  <button type="button" className="pt-project-name" onClick={() => openProject(p, chooser ? task : "project")}>{p.name}</button>
                  <span>最近测试 {latest(p)}</span>
                  <button type="button" onClick={() => openProject(p, task)}>{taskAction}</button>
                  {p.latest_at && p.blocks.latest.state !== "unavailable" && <button type="button" onClick={() => {
                    const end = +new Date(p.latest_at!) + 1;
                    go({ ...location, view: chooser ? task : "project", projectId: p.id, scope: { start: new Date(end - 7200000).toISOString(), end: new Date(end).toISOString() }, labels: { project: p.name }, inherited: true, selectedError: false, selectedStage: false, cursor: undefined, parentRead: undefined });
                  }}>查看最近测试时段</button>}
                </li>)}</ul>
              </DeferredDetails>}
              <StatisticsHelp>
                <p>测试记录不是成品数量；测试 SN 按来源、项目及 SN 区分，失败 SN 不是最终不良。仅汇总本页完整统计。</p>
                <p>统计范围 {localTime(data.requested_scope.start)} — {localTime(data.requested_scope.end)}；来源 {data.source_namespace}。最近测试独立于所选时段。</p>
              </StatisticsHelp>
              {data.has_more && data.next_before_id && (
                <button
                  type="button"
                  onClick={() => setBefore(data.next_before_id!)}
                >
                  读取更多项目概览
                </button>
              )}
            </>
          );
        }}
      </ReadBlock>
    </>
  );
}
function Trend({ data, scope, onRange }: { data: Analysis; scope: Scope; onRange: (scope: Scope) => void }) {
  return <><UpdatedAt capturedAt={data.captured_at} /><TrendChart data={data} scope={scope} onRange={onRange} /></>;
}
export function ProjectBoard(props: BoardProps) {
  const { api, location: l, refresh } = props;
  const go = (next: Location) => props.go(next, "scope");
  const summary = useRead(
    (s) =>
      api.productionAnalysis(l.projectId, { ...l.scope, view: "summary" }, s),
    [api, l.projectId, l.scope, refresh],
  );
  const stages = useRead(
    (s) =>
      api.productionAnalysis(l.projectId, { ...l.scope, view: "stages" }, s),
    [api, l.projectId, l.scope, refresh],
  );
  const trend = useRead(
    (s) =>
      api.productionAnalysis(l.projectId, { ...l.scope, view: "trend" }, s),
    [api, l.projectId, l.scope, refresh],
  );
  const yesterday = useRead(
    (s) =>
      api.productionAnalysis(
        l.projectId,
        { ...previousDay(l.scope), view: "summary" },
        s,
      ),
    [api, l.projectId, l.scope, refresh],
  );
  const availability = useRead(
    (s) => api.productionAvailability(l.projectId, s),
    [api, l.projectId, refresh],
    summary.data?.items[0]?.records === "0",
  );
  return (
    <>
      <h3>{l.labels.project || "源项目"} · 项目运行详情</h3>
      <Panel title="范围内测试规模"><ReadBlock label="项目规模" state={summary}>
        {(d) => (
          <>
            <Counts item={d.items[0] || null} />
            <ReadingDifference location={l} data={d} />
            <Coverage data={d} />
          </>
        )}
      </ReadBlock>
      </Panel>{summary.data?.items[0]?.records === "0" && (
        <aside>
          <p>当前范围无测试；可调整时间，或显式查看最近实际有数据的窗口。</p>
          <ReadBlock label="最近实际测试" state={availability}>
            {(a) => (
              <>
                {a.latest_at ? (
                  <>
                    <p>
                      独立最近事件 {localTime(a.latest_at)} · 读取{" "}
                      {localTime(a.captured_at)}
                    </p>
                    <button
                      type="button"
                      onClick={() => {
                        const end = +new Date(a.latest_at!) + 1;
                        go({
                          ...l,
                          scope: {
                            start: new Date(end - 7200000).toISOString(),
                            end: new Date(end).toISOString(),
                          },
                        });
                      }}
                    >
                      查看最近实际数据时段
                    </button>
                  </>
                ) : (
                  <p>源未返回实际测试时间。</p>
                )}
              </>
            )}
          </ReadBlock>
        </aside>
      )}
      <Panel title="测试环节">
      <ReadBlock label="测试环节" state={stages}>
        {(d) => (
          <>
            <Coverage data={d} />
            {d.items.map((a, i) => (
              <article key={a.key || i}>
                <button
                  type="button"
                  onClick={() =>
                    go({
                      ...l,
                      scope: drill(l.scope, a, ["stage_id", "software_id"]),
                      labels: {
                        ...l.labels,
                        stage_id: a.stage_name || "源未提供",
                        software_id: a.software_name || "源未提供",
                      },
                      selectedStage: true,
                    })
                  }
                >
                  选择{a.stage_name || "源未提供阶段"} ·{" "}
                  {a.software_name || "源未提供工具"}
                </button>
                <Counts item={a} />
              </article>
            ))}
          </>
        )}
      </ReadBlock>
      </Panel><Panel title={`${l.selectedStage ? "所选环节" : "项目"}测试与失败变化`}>
      <ReadBlock label="测试趋势" state={trend}>
        {(d) => (
          <Trend
            data={d}
            scope={l.scope}
            onRange={(scope) => go({ ...l, scope })}
          />
        )}
      </ReadBlock>
      </Panel><Panel title="历史时段对照"><ReadBlock label="昨天相同已过时段" state={yesterday}>
        {(d) => (
          <>
            <h4>昨天相同已过时段</h4>
            <p>
              {localTime(previousDay(l.scope).start)} —{" "}
              {localTime(previousDay(l.scope).end)}
            </p>
            <Counts item={d.items[0] || null} />
            <Coverage data={d} />

          </>
        )}
      </ReadBlock>
      </Panel><button className="pt-button-primary" type="button" onClick={() => go({ ...l, view: "anomalies" })}>
        查看该范围失败
      </button>
      <button type="button" onClick={() => go({ ...l, view: "records" })}>
        查看全部测试
      </button>
    </>
  );
}
export function AnomaliesBoard(props: BoardProps) {
  const { api, location: l, refresh } = props;
  const go = (next: Location) => props.go(next, "scope");
  const [distribution, setDistribution] = useState<"devices" | "versions">(
    "devices",
  );
  const errors = useRead(
    (s) =>
      api.productionAnalysis(
        l.projectId,
        { ...baseline(l.scope), view: "errors" },
        s,
      ),
    [api, l.projectId, l.scope, refresh],
  );
  const groups = useRead(
    (s) =>
      api.productionAnalysis(
        l.projectId,
        { ...l.scope, view: distribution },
        s,
      ),
    [api, l.projectId, l.scope, distribution, refresh],
    !!l.selectedError,
  );
  const summary = useRead(
    (s) =>
      api.productionAnalysis(l.projectId, { ...l.scope, view: "summary" }, s),
    [api, l.projectId, l.scope, refresh],
    !!l.selectedError,
  );
  const trend = useRead(
    (s) =>
      api.productionAnalysis(l.projectId, { ...l.scope, view: "trend" }, s),
    [api, l.projectId, l.scope, refresh],
    !!l.selectedError,
  );
  const failedSnMax = errors.data ? maximum(errors.data.items, "failed_sn") : "0";
  return (
    <>
      <h3>失败分析</h3>
      <div className="pt-master-detail">
        <Panel title="异常排行" className="pt-error-rankings"><ReadBlock label="异常列表" state={errors}>
          {(d) => (
            <>
              <Coverage data={d} />
              {!d.items.length && (
                <p>当前范围未观测到失败。</p>
              )}
              {[...d.items]
                .sort((a, b) =>
                  BigInt(a.failed_sn) > BigInt(b.failed_sn) ? -1 : 1,
                )
                .map((a, i) => (
                  <article className="pt-error-card" key={a.key || i} data-selected={!!l.selectedError && (a.error_code ?? null) === (l.scope.error_code ?? null) && (a.stage_id ?? null) === (l.scope.stage_id ?? null) && (a.software_id ?? null) === (l.scope.software_id ?? null)}>
                    <RankingBar value={a.failed_sn} max={failedSnMax} label="失败 SN" />
                    <button
                      type="button"
                      onClick={() =>
                        go({
                          ...l,
                          scope: {
                            ...drill(l.scope, a, [
                              "stage_id",
                              "software_id",
                              "error_code",
                            ]),
                            status: "2",
                          },
                          selectedError: true,
                          parentRead: {
                            captured_at: d.captured_at,
                            records: a.records,
                            distinct_sn: a.distinct_sn,
                            scope: {
                              ...drill(l.scope, a, [
                                "stage_id",
                                "software_id",
                                "error_code",
                              ]),
                              status: "2",
                            },
                          },
                          labels: {
                            ...l.labels,
                            stage_id: a.stage_name || "源未提供",
                            software_id: a.software_name || "源未提供",
                          },
                        })
                      }
                    >
                      选择异常 {a.error_code || "源未提供错误码"}
                    </button>
                    <p>
                      {a.stage_name || "源未提供阶段"} ·{" "}
                      {a.software_name || "源未提供工具"}
                    </p>
                    <Counts item={a} />
                    <p>
                      范围内首次 {localTime(a.first_time)} · 最近{" "}
                      {localTime(a.last_time)}
                    </p>
                  </article>
                ))}
            </>
          )}
        </ReadBlock>
        </Panel>{l.selectedError && (
          <div>
            <Panel title="所选症状影响" eyebrow={`错误码 ${l.scope.error_code ?? "源未提供"}`}><ReadBlock label="所选症状影响" state={summary}>
              {(d) => (
                <>
                  <Counts item={d.items[0] || null} />
                  <ReadingDifference location={l} data={d} />
                  <Coverage data={d} />
                  <StatisticsHelp><p>分母保留项目、时段、环节及其他条件，移除错误码与结果；不同错误的失败 SN 不相加。</p></StatisticsHelp>
                </>
              )}
            </ReadBlock>
            </Panel><Panel title="影响分布"><label>
              影响分布
              <select
                value={distribution}
                onChange={(e) =>
                  setDistribution(e.target.value as typeof distribution)
                }
              >
                <option value="devices">上位机</option>
                <option value="versions">工具及配置版本</option>
              </select>
            </label>
            <ReadBlock label="影响分布" state={groups}>
              {(d) => (
                <>
                  <Coverage data={d} />
                  {d.items.map((a, i) => (
                    <article key={a.key || i}>
                      <button
                        type="button"
                        onClick={() =>
                          go({
                            ...l,
                            scope: drill(
                              l.scope,
                              a,
                              distribution === "devices"
                                ? ["device"]
                                : [
                                    "software_id",
                                    "software_version",
                                    "config_log_id",
                                    "config_version",
                                  ],
                            ),
                          })
                        }
                      >
                        限定
                        {distribution === "devices"
                          ? `上位机 ${text(a.device)}`
                          : `版本 ${text(a.software_version)} / ${text(a.config_version)}`}
                      </button>
                      {distribution === "devices" && (
                        <button
                          type="button"
                          onClick={() =>
                            go({
                              ...l,
                              view: "device",
                              scope: drill(l.scope, a, ["device"]),
                              inherited: true,
                            })
                          }
                        >
                          查看上位机 {text(a.device)}
                        </button>
                      )}
                      <Counts item={a} />
                    </article>
                  ))}
                </>
              )}
            </ReadBlock>
            </Panel><button
              type="button"
              onClick={() =>
                go({ ...l, view: "records", scope: baseline(l.scope) })
              }
            >
              查看全部测试
            </button>
          </div>
        )}
      </div>
      {l.selectedError && (
        <Panel title="所选异常趋势"><ReadBlock label="所选异常趋势" state={trend}>
          {(d) => (
            <Trend
              data={d}
              scope={l.scope}
              onRange={(scope) => go({ ...l, scope })}
            />
          )}
        </ReadBlock></Panel>
      )}
      {l.selectedError && <Records {...props} />}
    </>
  );
}
export function ActivityBoard(props: BoardProps) {
  const { api, location: l, refresh } = props;
  const go = (next: Location) => props.go(next, "scope");
  const [recentRange, setRecentRange] = useState<Scope | null>(
    l.recentRange || null,
  );
  const devices = useRead(
    (s) =>
      api.productionAnalysis(l.projectId, { ...l.scope, view: "devices" }, s),
    [api, l.projectId, l.scope, refresh],
  );
  const activity = useRead(
    (s) =>
      api.productionAnalysis(l.projectId, { ...l.scope, view: "activity" }, s),
    [api, l.projectId, l.scope, refresh],
  );
  const latest = useRead(
    (s) =>
      api.productionAnalysis(
        l.projectId,
        { ...l.scope, ...recentRange!, view: "activity" },
        s,
      ),
    [api, l.projectId, l.scope, recentRange, refresh],
    !!recentRange,
  );
  const errors = useRead(
    (s) =>
      api.productionAnalysis(l.projectId, { ...l.scope, view: "errors" }, s),
    [api, l.projectId, l.scope, refresh],
    l.view === "device",
  );
  const versions = useRead(
    (s) =>
      api.productionAnalysis(l.projectId, { ...l.scope, view: "versions" }, s),
    [api, l.projectId, l.scope, refresh],
    l.view === "device",
  );
  return (
    <>
      <h3>
        {l.view === "device"
          ? `上位机 ${l.scope.device || "源未提供"} · 问题当时`
          : "上位机活动"}
      </h3>

      <Panel title="上位机规模"><ReadBlock label="上位机规模" state={devices}>
        {(d) => (
          <>
            <Coverage data={d} />
            <div className="pt-device-summaries">{d.items.map((a, i) => (
              <article key={a.key || i}>
                <button
                  type="button"
                  onClick={() =>
                    go({
                      ...l,
                      view: "device",
                      scope: drill(l.scope, a, ["device"]),
                    })
                  }
                >
                  查看上位机 {text(a.device)}
                </button>
                <Counts item={a} />
                <p>范围内最后测试 {localTime(a.last_time)}</p>
              </article>
            ))}</div>
          </>
        )}
      </ReadBlock>
      </Panel><Panel title="问题时段活动"><ReadBlock label="问题时段活动" state={activity}>
        {(d) => (
          <>
            <Coverage data={d} />
            <ActivityGrid data={d} location={l} go={go} />
            {!d.items.length && (
              <p>{d.complete ? "该时段未观测到测试事件" : "时间格未知"}</p>
            )}
          </>
        )}
      </ReadBlock>
      </Panel>{l.view === "device" && (
        <>
          <ReadBlock label="问题时段异常" state={errors}>
            {(d) => (
              <>
                {d.items.map((a, i) => (
                  <p key={i}>
                    {text(a.error_code)} · 失败涉及 SN {a.failed_sn} · 失败记录{" "}
                    {a.fail_records}
                  </p>
                ))}
                <Coverage data={d} />
              </>
            )}
          </ReadBlock>
          <ReadBlock label="问题时段版本" state={versions}>
            {(d) => (
              <>
                {d.items.map((a, i) => (
                  <p key={i}>
                    {text(a.software_version)} / {text(a.config_version)} · 测试{" "}
                    {a.records}
                  </p>
                ))}
                <Coverage data={d} />
                <StatisticsHelp><p>版本为源记录上报，不代表安装切换；无事件不能推断设备离线。</p></StatisticsHelp>
              </>
            )}
          </ReadBlock>
          <button
            type="button"
            onClick={() => {
              const scope = recent(30);
              setRecentRange(scope);
              props.onRecent?.(scope);
            }}
          >
            查看近况
          </button>
          <button type="button" onClick={() => go({ ...l, view: "records" })}>
            查看该时段测试
          </button>
          {recentRange && (
            <aside>
              <h4>最近 30 分钟 · 独立对照</h4>
              <p>
                {localTime(recentRange.start)} — {localTime(recentRange.end)}
              </p>
              <ReadBlock label="近况活动" state={latest}>
                {(d) => (
                  <Trend
                    data={d}
                    scope={{ ...l.scope, ...recentRange }}
                    onRange={(scope) =>
                      props.go({ ...l, view: "records", scope }, "browse")
                    }
                  />
                )}
              </ReadBlock>
            </aside>
          )}
        </>
      )}
    </>
  );
}

function ActivityGrid({ data, location: l, go }: { data: Analysis; location: Location; go: BoardProps["go"] }) {
  const width = (data.bucket_minutes || 5) * 60000, start = +new Date(l.scope.start), end = +new Date(l.scope.end), first = Math.floor(start / width) * width;
  const requestedBuckets = Math.max(0, Math.ceil((end - first) / width));
  const times = Array.from({ length: Math.min(96, requestedBuckets) }, (_, i) => first + i * width);
  const devices = [...new Set(data.items.map((a) => a.device ?? null))];
  // Preserve first source row, indexing once instead of scanning for every cell.
  const index = new Map<string | null, Map<number, Aggregate>>();
  for (const item of data.items) {
    const device = item.device ?? null;
    if (!index.has(device)) index.set(device, new Map());
    const byTime = index.get(device)!, time = +new Date(item.timestamp!);
    if (!byTime.has(time)) byTime.set(time, item);
  }
  const max = maximum(data.items, "records");
  return <>
    <div className="pt-chart-legend pt-activity-legend" aria-label="活动图例"><span><i data-activity="observed" />观测活动</span><span><i data-activity="failure" />● 观测失败</span><span><i data-activity="empty" />完整范围无事件</span><span><i data-activity="unknown" />? 部分范围未知</span></div>
    {requestedBuckets > 96 && <p className="pt-chart-partial">仅展示前 96 个时间格：{localTime(new Date(start).toISOString())} — {localTime(new Date(Math.min(end, first + 96 * width)).toISOString())}；其余请求时段未在此图展示，请缩小时间范围查看。</p>}
    {!devices.length && <EmptyState title={data.complete ? "该时段未观测到测试事件" : "时间格未知"} />}
    <div className="pt-table pt-activity-map" role="region" tabIndex={0} aria-label="上位机活动时间格"><table>
      <thead><tr><th scope="col">上位机</th>{times.map((t) => <th scope="col" key={t} aria-label={localTime(new Date(Math.max(start, t)).toISOString())} title={localTime(new Date(Math.max(start, t)).toISOString())}><time dateTime={new Date(Math.max(start, t)).toISOString()}>{new Date(Math.max(start, t)).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false })}</time></th>)}</tr></thead>
      <tbody>{devices.map((device) => <tr key={JSON.stringify(device)}><th scope="row">{text(device)}</th>{times.map((time) => {
        const item = index.get(device)?.get(time), state = item ? item.fail_records !== "0" ? "failure" : "observed" : data.complete ? "empty" : "unknown";
        const label = item ? `测试 ${item.records}${item.fail_records !== "0" ? ` ● 失败 ${item.fail_records}` : ""}` : data.complete ? "该格未观测到测试事件" : "该时间格未知";
        const accessible = `${text(device)} · ${localTime(new Date(Math.max(start, time)).toISOString())} — ${localTime(new Date(Math.min(end, time + width)).toISOString())} · ${label}`;
        return <td key={time} data-activity={state} style={{ "--pt-activity-level": item ? boundedPercent(item.records, max) : 0 } as CSSProperties}>
          <button type="button" aria-label={accessible} title={accessible} onClick={() => go({ ...l, view: "device", scope: { ...drill(l.scope, { device } as Aggregate, ["device"]), start: new Date(Math.max(start, time)).toISOString(), end: new Date(Math.min(end, time + width)).toISOString() } })}><span className="pt-cell-text">{label}</span></button>
        </td>;
      })}</tr>)}</tbody>
    </table></div>
  </>;
}

function ReadingDifference({
  location: l,
  data,
}: {
  location: Location;
  data: Analysis;
}) {
  const previous = l.parentRead;
  if (!previous) return null;
  const current = data.items[0];
  const sameScope = JSON.stringify(previous.scope) === JSON.stringify(l.scope);
  if (!sameScope) return <StatisticsHelp><p>上次范围测试次数 {previous.records}、测试 SN {previous.distinct_sn}，与当前范围不同。上次数据时间 {localTime(previous.captured_at)}。</p></StatisticsHelp>;
  if (current?.records === previous.records && current?.distinct_sn === previous.distinct_sn) return null;
  return <p className="pt-meta">数据已变化：测试次数 {previous.records} → {current?.records ?? "未知"}；测试 SN {previous.distinct_sn} → {current?.distinct_sn ?? "未知"}。</p>;
}
