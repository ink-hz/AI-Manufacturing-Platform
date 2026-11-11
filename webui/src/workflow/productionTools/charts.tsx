import { localTime, text } from "./context";
import type { Aggregate, Analysis, Scope } from "./types";
import { boundedPercent, EmptyState } from "./visuals";

export function maximum(items: Aggregate[], field: "records" | "fail_records" | "failed_sn") {
  return items.reduce((max, item) => BigInt(item[field]) > BigInt(max) ? item[field] : max, "0");
}

/** Source counts remain decimal strings; only bounded drawing coordinates are numeric. */
export function TrendChart({ data, scope, onRange }: { data: Analysis; scope: Scope; onRange: (scope: Scope) => void }) {
  if (!data.items.length) return <EmptyState title={data.complete ? "当前范围未观测到测试事件" : "时间格未知"} />;
  if (data.view === "activity") {
    const devices = new Map<string | null, Aggregate[]>();
    for (const item of data.items) {
      const device = item.device ?? null;
      if (!devices.has(device)) devices.set(device, []);
      devices.get(device)!.push(item);
    }
    return <div className="pt-device-trends">{[...devices].map(([device, items]) =>
      <section key={JSON.stringify(device)} aria-label={`上位机 ${text(device)} 的活动趋势`}>
        <h4>上位机 {text(device)}</h4>
        <TrendChart data={{ ...data, view: "trend", items }} scope={scope} onRange={onRange} />
      </section>
    )}</div>;
  }
  const totalMax = maximum(data.items, "records"), failMax = maximum(data.items, "fail_records");
  const bucket = (data.bucket_minutes || 5) * 60000;
  const timestamps = data.items.map((item) => +new Date(item.timestamp!));
  const first = Math.min(...timestamps), slots = Math.round((Math.max(...timestamps) - first) / bucket) + 1;
  const column = (i: number) => Math.round((timestamps[i] - first) / bucket);
  const width = slots * 128;
  return <div className="pt-time-chart">
    <div className="pt-chart-legend"><span><i data-series="tests" />测试记录量（含所有结果）</span><span><i data-series="failures" />失败记录量</span><span>上下图带分别按各自最大值缩放；空白位置仅表示未返回时间格</span></div>
    {!data.complete && <p className="pt-chart-partial">趋势部分读取；未取得时间格未知</p>}
    <div className="pt-chart-scales"><span>测试记录量 · 最大 {totalMax}</span><span>失败记录量 · 最大 {failMax}</span></div>
    <div className="pt-chart-scroll" role="region" aria-label="时间趋势图及时间格操作" tabIndex={0}>
      <div style={{ minWidth: Math.max(480, width) }}>
        <svg role="img" aria-label="测试与失败时间趋势" viewBox={`0 0 ${width} 260`} preserveAspectRatio="none">
          <line x1="0" x2={width} y1="120" y2="120" className="pt-chart-axis" />
          <line x1="0" x2={width} y1="250" y2="250" className="pt-chart-axis" />
          {data.items.map((item, i) => {
            const total = boundedPercent(item.records, totalMax), failed = boundedPercent(item.fail_records, failMax);
            return <g key={item.key || i}><title>{localTime(item.timestamp)} · 测试 {item.records} · 失败 {item.fail_records} · 未知 {item.unknown_records}</title>
              <rect className="pt-chart-tests" x={column(i) * 128 + 30} y={120 - total} width="68" height={total} rx="3" />
              <rect className="pt-chart-failures" x={column(i) * 128 + 30} y={250 - failed} width="68" height={failed} rx="3" />
            </g>;
          })}
        </svg>
        <div className="pt-chart-buckets" style={{ gridTemplateColumns: `repeat(${slots}, minmax(0, 1fr))` }}>
          {data.items.map((item, i) => {
            const start = Math.max(+new Date(scope.start), +new Date(item.timestamp!));
            const end = Math.min(+new Date(scope.end), +new Date(item.timestamp!) + (data.bucket_minutes || 5) * 60000);
            return <button type="button" key={item.key || i} style={{ gridColumn: column(i) + 1 }} disabled={!(end > start)} onClick={() => onRange({ ...scope, start: new Date(start).toISOString(), end: new Date(end).toISOString() })}>
              {localTime(item.timestamp)}<br />测试 {item.records} · 失败 {item.fail_records} · 未知 {item.unknown_records}
            </button>;
          })}
        </div>
      </div>
    </div>
  </div>;
}

export function MiniTrend({ items, complete }: { items: Aggregate[]; complete: boolean }) {
  if (!items.length) return <p className="pt-meta">{complete ? "当前范围未观测到测试事件" : "趋势部分读取；空白时段未知"}</p>;
  const total = maximum(items, "records"), failures = maximum(items, "fail_records");
  const timestamps = items.map((item) => +new Date(item.timestamp!));
  const first = Math.min(...timestamps), span = Math.max(...timestamps) - first;
  const x = (i: number) => span > 0 ? (timestamps[i] - first) / span * (items.length * 12 - 10) + 1 : i * 12 + 1;
  return <figure className="pt-mini-trend">
    <figcaption>近期已返回时间格 · 测试量 / 失败量各自缩放{!complete && " · 部分读取；空白时段未知"}</figcaption>
    <svg role="img" aria-label="项目近期测试与失败趋势" viewBox={`0 0 ${items.length * 12} 56`} preserveAspectRatio="none">
      {items.map((item, i) => <g key={item.key || i}><title>{localTime(item.timestamp)} · 测试 {item.records} · 失败 {item.fail_records} · 未知 {item.unknown_records}</title><rect className="pt-chart-tests" x={x(i)} y={26 - boundedPercent(item.records, total) * .24} width="9" height={boundedPercent(item.records, total) * .24} /><rect className="pt-chart-failures" x={x(i)} y={54 - boundedPercent(item.fail_records, failures) * .24} width="9" height={boundedPercent(item.fail_records, failures) * .24} /></g>)}
    </svg>
  </figure>;
}

export function RankingBar({ value, max, label }: { value: string; max: string; label: string }) {
  return <div className="pt-ranking" role="img" aria-label={`${label} ${value}；本组最大 ${max}`}><span className="pt-ranking-track"><span style={{ width: `${boundedPercent(value, max)}%` }} /></span><strong>{value}</strong><span>{label}</span></div>;
}
