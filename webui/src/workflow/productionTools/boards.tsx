import { useEffect, useState, type ReactNode } from "react";
import type { createWorkflowApi } from "../api";
import type { Aggregate, Analysis, Scope, ViewedEvent } from "./types";
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
export type Api = ReturnType<typeof createWorkflowApi>;
export interface BoardProps {
  api: Api;
  location: Location;
  go: (next: Location) => void;
  inspect: (event: ViewedEvent) => void;
  refresh: number;
  onRecent?: (scope: Scope) => void;
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
    <section aria-label={label}>
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
              以下保留上次成功读取内容及其时间，尚未更新。
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
  data: { captured_at: string; complete: boolean };
}) {
  return (
    <p className="pt-meta">
      读取 {localTime(data.captured_at)} ·{" "}
      {data.complete
        ? "本次范围读取完整"
        : "仅取得部分数据；遗漏分组和时间格未知，不能视为零"}
    </p>
  );
}
export function Counts({ item }: { item: Aggregate | null }) {
  return item ? (
    <div className="pt-counts">
      <span>测试记录 {item.records}</span>
      <span>测试 SN {item.distinct_sn}</span>
      <strong>失败涉及 SN {item.failed_sn}</strong>
      <span>
        失败记录 {item.fail_records}
        {item.denominator_records
          ? ` / 适用样本 ${item.denominator_records}`
          : ""}
      </span>
      <span>
        通过 {item.pass_records} · 未知 {item.unknown_records}
      </span>
    </div>
  ) : (
    <p>统计未取得，不能计作零</p>
  );
}
export function OverviewBoard({ api, location, go, refresh }: BoardProps) {
  const [before, setBefore] = useState<string>(),
    [sort, setSort] = useState("failed"),
    [auto, setAuto] = useState(true),
    [tick, setTick] = useState(0);
  const state = useRead(
    (s) =>
      api.productionOverview(
        {
          start: location.scope.start,
          end: location.scope.end,
          before_id: before,
        },
        s,
      ),
    [api, location.scope.start, location.scope.end, before, refresh, tick],
    true,
    [api, location.scope.start, location.scope.end, before],
  );
  useEffect(() => {
    if (!auto) return;
    const timer = setInterval(() => setTick((x) => x + 1), 60000);
    return () => clearInterval(timer);
  }, [auto]);
  return (
    <>
      <h3>今天哪里需要关注</h3>
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
          <option value="failed">失败涉及 SN</option>
          <option value="latest">最近测试时间</option>
        </select>
      </label>
      <ReadBlock label="运行总览" state={state}>
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
            (p) => p.statistics && p.blocks.statistics.complete,
          );
          const sum = (key: "distinct_sn" | "failed_sn") =>
            valid
              .reduce((n, p) => n + BigInt(p.statistics![key]), 0n)
              .toString();
          return (
            <>
              <Coverage data={data} />
              <p>
                本页已读取 {valid.length} / {data.items.length} 项目 ·
                有测试的项目{" "}
                {valid.filter((p) => p.statistics!.records !== "0").length} ·
                测试 SN {sum("distinct_sn")} · 失败涉及 SN {sum("failed_sn")}
              </p>
              <p className="pt-meta">
                按来源、项目及 SN
                区分；仅汇总本页完整统计。测试记录不是成品数量，失败涉及 SN
                不是最终不良。
              </p>
              {!data.items.length && <p>源项目目录暂无项目</p>}
              <div className="pt-projects">
                {rows.map((p) => (
                  <article key={p.id}>
                    <h4>{p.name}</h4>
                    <Counts item={p.statistics} />
                    <p>范围内最后测试：{localTime(p.statistics?.last_time)}</p>
                    <p>
                      独立最近实际测试：
                      {p.blocks.latest.state === "unavailable"
                        ? "未取得"
                        : localTime(p.latest_at)}
                    </p>
                    <p>
                      {p.blocks.trend.state === "unavailable"
                        ? "趋势未取得"
                        : !p.blocks.trend.complete
                          ? "趋势部分读取；空白时段未知"
                          : p.trend.length
                            ? `近期时间格 ${p.trend.length}；失败记录 ${p.trend.map((x) => x.fail_records).join(" → ")}`
                            : "当前范围未观测到测试事件"}
                    </p>
                    <button
                      type="button"
                      onClick={() =>
                        go({
                          ...location,
                          view: "project",
                          projectId: p.id,
                          labels: { project: p.name },
                          parentRead: p.statistics
                            ? {
                                captured_at: p.blocks.statistics.captured_at,
                                records: p.statistics.records,
                                distinct_sn: p.statistics.distinct_sn,
                                scope: location.scope,
                              }
                            : undefined,
                          inherited: true,
                        })
                      }
                    >
                      查看{p.name}
                    </button>
                    {p.statistics?.records === "0" && p.latest_at && (
                      <button
                        type="button"
                        onClick={() => {
                          const end = new Date(+new Date(p.latest_at!) + 1);
                          go({
                            ...location,
                            view: "project",
                            projectId: p.id,
                            scope: {
                              start: new Date(+end - 7200000).toISOString(),
                              end: end.toISOString(),
                            },
                            labels: { project: p.name },
                            inherited: true,
                          });
                        }}
                      >
                        查看{p.name}最近实际数据时段
                      </button>
                    )}
                  </article>
                ))}
              </div>
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
function Trend({
  data,
  scope,
  onRange,
}: {
  data: Analysis;
  scope: Scope;
  onRange: (scope: Scope) => void;
}) {
  return (
    <>
      <Coverage data={data} />
      {data.items.length ? (
        <div className="pt-trend">
          {data.items.map((item, i) => (
            <button
              type="button"
              key={item.key || i}
              onClick={() => {
                const start = Math.max(
                    +new Date(scope.start),
                    +new Date(item.timestamp!),
                  ),
                  end = Math.min(
                    +new Date(scope.end),
                    +new Date(item.timestamp!) +
                      (data.bucket_minutes || 5) * 60000,
                  );
                if (end > start)
                  onRange({
                    ...scope,
                    start: new Date(start).toISOString(),
                    end: new Date(end).toISOString(),
                  });
              }}
            >
              {localTime(item.timestamp)}
              <br />
              测试 {item.records} · 失败 {item.fail_records} · 未知{" "}
              {item.unknown_records}
            </button>
          ))}
        </div>
      ) : (
        <p>{data.complete ? "当前范围未观测到测试事件" : "时间格未知"}</p>
      )}
    </>
  );
}
export function ProjectBoard(props: BoardProps) {
  const { api, location: l, go, refresh } = props;
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
      <ReadBlock label="项目规模" state={summary}>
        {(d) => (
          <>
            <Counts item={d.items[0] || null} />
            <ReadingDifference location={l} data={d} />
            <Coverage data={d} />
          </>
        )}
      </ReadBlock>
      {summary.data?.items[0]?.records === "0" && (
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
      <h4>测试环节</h4>
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
      <h4>{l.selectedStage ? "所选环节" : "项目"}测试与失败变化</h4>
      <ReadBlock label="测试趋势" state={trend}>
        {(d) => (
          <Trend
            data={d}
            scope={l.scope}
            onRange={(scope) => go({ ...l, scope })}
          />
        )}
      </ReadBlock>
      <ReadBlock label="昨天相同已过时段" state={yesterday}>
        {(d) => (
          <>
            <h4>昨天相同已过时段</h4>
            <p>
              {localTime(previousDay(l.scope).start)} —{" "}
              {localTime(previousDay(l.scope).end)}
            </p>
            <Counts item={d.items[0] || null} />
            <Coverage data={d} />
            <p>
              同时核对测试构成和样本量；混合阶段或工具变化不能直接归因为质量变化。
            </p>
          </>
        )}
      </ReadBlock>
      <button type="button" onClick={() => go({ ...l, view: "anomalies" })}>
        查看该范围异常
      </button>
      <button type="button" onClick={() => go({ ...l, view: "records" })}>
        查看全部测试
      </button>
    </>
  );
}
export function AnomaliesBoard(props: BoardProps) {
  const { api, location: l, go, refresh } = props;
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
  return (
    <>
      <h3>测试异常 · 先选症状，再看影响</h3>
      <p>
        错误码按 FAIL 记录统计；不同错误的影响 SN
        不相加。未确认判定规则的动态字段不参与排行。
      </p>
      <div className="pt-master-detail">
        <ReadBlock label="异常列表" state={errors}>
          {(d) => (
            <>
              <Coverage data={d} />
              {!d.items.length && (
                <p>当前范围没有 FAIL；未知结果及读取覆盖仍需核对。</p>
              )}
              {[...d.items]
                .sort((a, b) =>
                  BigInt(a.failed_sn) > BigInt(b.failed_sn) ? -1 : 1,
                )
                .map((a, i) => (
                  <article key={a.key || i}>
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
        {l.selectedError && (
          <div>
            <ReadBlock label="所选症状影响" state={summary}>
              {(d) => (
                <>
                  <Counts item={d.items[0] || null} />
                  <ReadingDifference location={l} data={d} />
                  <Coverage data={d} />
                  <p>
                    分母移除错误码与结果，保留当前项目、时段、环节及其他条件。
                  </p>
                </>
              )}
            </ReadBlock>
            <label>
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
            <button
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
        <ReadBlock label="所选异常趋势" state={trend}>
          {(d) => (
            <Trend
              data={d}
              scope={l.scope}
              onRange={(scope) => go({ ...l, scope })}
            />
          )}
        </ReadBlock>
      )}
      {l.selectedError && <Records {...props} />}
    </>
  );
}
export function ActivityBoard(props: BoardProps) {
  const { api, location: l, go, refresh } = props;
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
          : "上位机与时间"}
      </h3>
      <p>
        深浅表示测试记录量，●
        标记失败；灰色仅表示该时段未观测到事件。读取失败和未完整格为未知，不表示在线或离线。
      </p>
      <ReadBlock label="上位机规模" state={devices}>
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
            ))}
          </>
        )}
      </ReadBlock>
      <ReadBlock label="问题时段活动" state={activity}>
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
      {l.view === "device" && (
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
                <p>版本交错只说明源记录上报，不推断实际安装切换。</p>
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
                    scope={recentRange}
                    onRange={(scope) => go({ ...l, view: "records", scope })}
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

function ActivityGrid({
  data,
  location: l,
  go,
}: {
  data: Analysis;
  location: Location;
  go: BoardProps["go"];
}) {
  const width = (data.bucket_minutes || 5) * 60000,
    start = +new Date(l.scope.start),
    end = +new Date(l.scope.end),
    first = Math.floor(start / width) * width;
  const times = Array.from(
    { length: Math.min(96, Math.ceil((end - first) / width)) },
    (_, i) => first + i * width,
  );
  const devices = [...new Set(data.items.map((a) => a.device ?? null))];
  return (
    <div
      className="pt-table"
      role="region"
      tabIndex={0}
      aria-label="上位机活动时间格"
    >
      <table>
        <thead>
          <tr>
            <th>上位机</th>
            {times.map((t) => (
              <th key={t}>
                {localTime(new Date(Math.max(start, t)).toISOString())}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {devices.map((device) => (
            <tr key={device || "missing"}>
              <th>{text(device)}</th>
              {times.map((time) => {
                const item = data.items.find(
                  (a) =>
                    (a.device ?? null) === device &&
                    +new Date(a.timestamp!) === time,
                );
                return (
                  <td
                    key={time}
                    className={
                      item
                        ? item.fail_records !== "0"
                          ? "has-failure"
                          : "observed"
                        : data.complete
                          ? "empty"
                          : "unknown"
                    }
                  >
                    <button
                      type="button"
                      onClick={() =>
                        go({
                          ...l,
                          view: "device",
                          scope: {
                            ...drill(l.scope, { device } as Aggregate, [
                              "device",
                            ]),
                            start: new Date(
                              Math.max(start, time),
                            ).toISOString(),
                            end: new Date(
                              Math.min(end, time + width),
                            ).toISOString(),
                          },
                        })
                      }
                    >
                      {item
                        ? `测试 ${item.records}${item.fail_records !== "0" ? ` ● 失败 ${item.fail_records}` : ""}`
                        : data.complete
                          ? "该格未观测到测试事件"
                          : "该时间格未知"}
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
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
  return (
    <p className="pt-meta">
      父视图读取 {localTime(previous.captured_at)}：测试记录 {previous.records}
      、测试 SN {previous.distinct_sn}；本次读取 {localTime(data.captured_at)}
      ：测试记录 {current?.records ?? "未知"}、测试 SN{" "}
      {current?.distinct_sn ?? "未知"}。
      {sameScope
        ? "相同范围可能因源回填发生变化。"
        : "深入后的范围不同，数量不能直接比较。"}
      各次读取不是跨源原子快照。
    </p>
  );
}
