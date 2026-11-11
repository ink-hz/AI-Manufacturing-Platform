import "./details.css";
import { Badge, EmptyState, Panel, ResultBadge } from "./visuals";
import type { CapturedLog } from "./types";
import { WorkflowError } from "../api";
import { useState } from "react";
import type { Api, BoardProps } from "./boards";
import { Coverage, ReadBlock } from "./boards";
import {
  matchesContext,
  sourceName,
  localInput,
  localTime,
  text,
  useRead,
  type Location,
} from "./context";
import type {
  CatalogKind,
  Investigation,
  ObservationKind,
  ProductionPage,
  ProductionRow,
  Scope,
  ViewedEvent,
} from "./types";
export function result(value: unknown) {
  return String(value) === "1"
    ? "通过 PASS"
    : String(value) === "2"
      ? "失败 FAIL"
      : `结果未知（${text(value)}）`;
}
const metadata: Record<string, string> = {
  timestamp: "事件时间",
  sn: "SN",
  barcode: "条码",
  status: "结果",
  errorcode: "错误码",
  workstagesid: "阶段",
  softwareid: "工具",
  version: "软件版本",
  configlogsid: "配置",
  cversion: "配置版本",
  devicename: "上位机",
  orderid: "工具配置审核单",
  workselectid: "测试项选择",
};
export function RecordTable({
  page,
  location: l,
  go,
  inspect,
  kind = "production",
}: {
  page: ProductionPage;
  location: Location;
  go: BoardProps["go"];
  inspect: BoardProps["inspect"];
  kind?: ObservationKind;
}) {
  return (
    <section className="pt-records" aria-label={kind === "stopover" ? "过站记录" : "测试记录"}>
      <div className="pt-table-tools">
        <div><strong>{kind === "stopover" ? "过站" : "测试"}记录</strong><span className="pt-meta"> · {page.items.length} 条</span></div>
        <Coverage data={page} />
      </div>
      {page.redacted_fields.length > 0 && <p className="pt-meta">部分字段未提供</p>}
      {!page.items.length ? (
        <EmptyState title={<>当前范围暂无{kind === "stopover" ? "过站" : "测试"}记录，范围外未知。</>} />
      ) : (
        <div
          className="pt-table"
          role="region"
          tabIndex={0}
          aria-label="产测记录表"
        >
          <table>
            <thead>
              <tr>
                <th>时间 / 事件</th>
                <th>SN</th>
                <th>结果</th>
                <th>阶段 / 工具</th>
                <th>上位机</th>
                <th>版本 / 配置</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((row, i) => (
                <tr
                  key={`${page.snapshot_id}-${page.offset + i}`}
                  data-result={row.status === "2" || row.status === 2 ? "fail" : undefined}
                  className={
                    l.view === "history" &&
                      matchesContext({ ...l.scope, view: "history" }, row)
                      ? "pt-symptom"
                      : undefined
                  }
                >
                  <td>
                    <button
                      type="button"
                      onClick={() =>
                        inspect({
                          snapshot_id: page.snapshot_id,
                          offset: page.offset + i,
                          row,
                          kind,
                          captured_at: page.captured_at,
                          projectId: l.projectId,
                        })
                      }
                    >
                      查看{kind === "stopover" ? "过站" : "测试"}{" "}
                      {i + 1}
                    </button>
                    <br />
                    {localTime(row.timestamp)}
                    {page.items.filter((r) => r.timestamp === row.timestamp)
                      .length > 1 && <small>同时间多条记录，先后未确定</small>}
                  </td>
                  <td>
                    {row.sn ? (
                      <button
                        type="button"
                        onClick={() =>
                          go({
                            ...l,
                            view: "history",
                            historySN: String(row.sn),
                            historyRange: {
                              start: l.scope.start,
                              end: l.scope.end,
                            },
                            cursor: undefined,
                          })
                        }
                      >
                        查看 {String(row.sn)} 履历
                      </button>
                    ) : (
                      text(row.sn)
                    )}
                  </td>
                  <td>
                    {l.view === "history" &&
                      (l.scope.error_code ||
                        l.scope.status ||
                        l.scope.missing_fields?.length) &&
                      matchesContext({ ...l.scope, view: "history" }, row) && (
                        <small className="pt-symptom-label">原症状命中</small>
                      )}
                    <ResultBadge value={row.status} />
                    <br />
                    {text(row.errorcode)}
                  </td>
                  <td>
                    {sourceName(l, "stage_id", row.workstagesid)} /{" "}
                    {sourceName(l, "software_id", row.softwareid)}
                  </td>
                  <td>{text(row.devicename)}</td>
                  <td>
                    {text(row.version)} / {text(row.cversion)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="pt-actions pt-pagination" aria-label="记录分页">
        <button
          type="button"
          disabled={page.offset === 0}
          onClick={() =>
            go({
              ...l,
              cursor: {
                id: page.snapshot_id,
                offset: Math.max(0, page.offset - page.limit),
                limit: page.limit,
                kind,
              },
            })
          }
        >
          上一页
        </button>
        <span>第 {Math.floor(page.offset / page.limit) + 1} 页</span>
        <button
          type="button"
          disabled={!page.has_more}
          onClick={() =>
            go({
              ...l,
              cursor: {
                id: page.snapshot_id,
                offset: page.offset + page.limit,
                limit: page.limit,
                kind,
              },
            })
          }
        >
          下一页
        </button>
      </div>
    </section>
  );
}
export function Records(props: BoardProps) {
  const { api, location: l, refresh } = props;
  const state = useRead(
    async (s) => {
      const status = await api.productionStatus(l.projectId, s);
      if (!status.configured || !status.capabilities.production?.available)
        throw new WorkflowError(503, "PRODUCTION_CAPABILITY_UNAVAILABLE");
      return l.cursor
        ? api.productionSnapshot(
          l.projectId,
          l.cursor.id,
          l.cursor.offset,
          l.cursor.limit,
          s,
        )
        : api.productionObservations(
          l.projectId,
          { ...l.scope, kind: "production" },
          s,
        );
    },
    [api, l.projectId, l.scope, l.cursor, l.readGeneration, refresh],
  );
  return (
    <Panel title="测试记录">
      <ReadBlock label="测试记录" state={state}>
        {(page) => <RecordTable page={page} {...props} />}
      </ReadBlock>
    </Panel>
  );
}
export function HistoryPage(props: BoardProps) {
  const { api, location: l, refresh } = props;
  const scope = { ...(l.historyRange || l.scope), sn: l.historySN! };
  const production = useRead(
    (s) =>
      l.cursor?.kind === "production"
        ? api.productionSnapshot(
          l.projectId,
          l.cursor.id,
          l.cursor.offset,
          l.cursor.limit,
          s,
        )
        : api.productionObservations(
          l.projectId,
          {
            start: scope.start,
            end: scope.end,
            sn: scope.sn,
            kind: "production",
          },
          s,
        ),
    [
      api,
      l.projectId,
      scope.start,
      scope.end,
      scope.sn,
      l.cursor?.kind === "production" ? l.cursor : undefined,
      l.readGeneration,
      refresh,
    ],
  );
  const stopover = useRead(
    (s) =>
      l.cursor?.kind === "stopover"
        ? api.productionSnapshot(
          l.projectId,
          l.cursor.id,
          l.cursor.offset,
          l.cursor.limit,
          s,
        )
        : api.productionObservations(
          l.projectId,
          {
            start: scope.start,
            end: scope.end,
            sn: scope.sn,
            kind: "stopover",
          },
          s,
        ),
    [
      api,
      l.projectId,
      scope.start,
      scope.end,
      scope.sn,
      l.cursor?.kind === "stopover" ? l.cursor : undefined,
      l.readGeneration,
      refresh,
    ],
  );
  return (
    <Panel title={<>SN {l.historySN} · 当前范围记录</>} eyebrow="SN 履历" className="pt-history">
      <p>履历时间 {localTime(scope.start)} — {localTime(scope.end)}</p>
      <ReadBlock label="SN 测试履历" state={production}>
        {(page) => <RecordTable page={page} {...props} />}
      </ReadBlock>
      <ReadBlock label="SN 过站履历" state={stopover}>
        {(page) => <RecordTable page={page} {...props} kind="stopover" />}
      </ReadBlock>
    </Panel>
  );
}
const catalogFields = [
  ["name", "名称"], ["versions", "版本"], ["version", "版本"],
  ["details", "说明"], ["description", "版本说明"], ["versiondetails", "版本说明"],
  ["username", "作者"], ["audituser", "审核人"],
] as const;
function reviewState(kind: CatalogKind, value: unknown) {
  const common = new Map([["1", "待测试"], ["2", "待准出"], ["3", "测试失败"], ["4", "已准出"]]);
  return common.get(String(value)) || (kind === "review_orders" && String(value) === "5" ? "强制准出" : kind !== "review_orders" && String(value) === "-1" ? "测试中" : "未知");
}
// Preserve dynamic measurement names while omitting transport and storage fields.
const internalFields = new Set(["id", "projuectid", "project_id", "source_project_id", "del", "snapshot_id", "offset", "captured_at", "source_namespace", "source_kind", "fingerprint", "schema_version", "protocol_version", "expires_at", "redacted_fields"]);
const businessEntries = (row: ProductionRow) => Object.entries(row).filter(([key]) => !internalFields.has(key));
export function CatalogPage(props: BoardProps) {
  const { api, location: l, go, refresh } = props;
  const [before, setBefore] = useState<string>();
  const kind = l.catalog || "software";
  const state = useRead(
    (s) =>
      api.productionCatalog(
        l.projectId,
        kind,
        { parent_id: l.parentId, before_id: before },
        s,
      ),
    [api, l.projectId, kind, l.parentId, before, refresh],
  );
  return (
    <Panel title="工具与配置" className="pt-catalog">
      <nav className="pt-actions" aria-label="目录分类">
        {(
          [
            ["software", "工具"],
            ["configs", "配置"],
            ["review_orders", "工具配置审核单"],
          ] as [CatalogKind, string][]
        ).map(([id, label]) => (
          <button
            type="button"
            key={id}
            aria-pressed={kind === id || (id === "software" && kind === "software_versions") || (id === "configs" && kind === "config_versions")}
            onClick={() => {
              setBefore(undefined);
              go({ ...l, catalog: id, parentId: undefined });
            }}
          >
            {label}
          </button>
        ))}
      </nav>
      <ReadBlock label="目录" state={state}>
        {(page) => (
          <>
            <Coverage data={page} />
            <div className="pt-catalog-list">
              {page.items.map((row, i) => (
                <article key={i}>
                  <h4>{text(row.name || row.versions || row.version)}</h4>
                  {(kind === "software" || kind === "configs") && (
                    <button
                      type="button"
                      onClick={() => {
                        setBefore(undefined);
                        go({
                          ...l,
                          catalog:
                            kind === "software"
                              ? "software_versions"
                              : "config_versions",
                          parentId: String(row.id),
                        });
                      }}
                    >
                      查看{text(row.name)}版本
                    </button>
                  )}
                  {(kind === "software_versions" || kind === "config_versions") &&
                    Boolean(row.versions || row.version) && (
                      <button
                        type="button"
                        onClick={() =>
                          go({
                            ...l,
                            view: "records",
                            scope:
                              kind === "software_versions"
                                ? {
                                  ...l.scope,
                                  software_id: l.parentId,
                                  software_version: String(
                                    row.versions || row.version,
                                  ),
                                  missing_fields:
                                    l.scope.missing_fields?.filter(
                                      (k) =>
                                        k !== "software_id" &&
                                        k !== "software_version",
                                    ),
                                }
                                : {
                                  ...l.scope,
                                  config_log_id: String(row.id),
                                  config_version: String(
                                    row.versions || row.version,
                                  ),
                                  missing_fields:
                                    l.scope.missing_fields?.filter(
                                      (k) =>
                                        k !== "config_log_id" &&
                                        k !== "config_version",
                                    ),
                                },
                            cursor: undefined,
                          })
                        }
                      >
                        查看此版本测试
                      </button>
                    )}
                  <dl>
                    {catalogFields.flatMap(([key, label]) => row[key] !== null && row[key] !== undefined && row[key] !== "" ? [
                      <div key={key}><dt>{label}</dt><dd>{text(row[key])}</dd></div>,
                    ] : [])}
                    {(kind === "software_versions" || kind === "config_versions" || kind === "review_orders") && (
                      <div><dt>当前审核状态</dt><dd>{reviewState(kind, row.state)}</dd></div>
                    )}
                  </dl>
                </article>
              ))}
            </div>
            {page.next_before_id && (
              <button
                type="button"
                onClick={() => setBefore(page.next_before_id!)}
              >
                下一页
              </button>
            )}
            {!page.items.length && <EmptyState title="当前目录暂无记录" />}
          </>
        )}
      </ReadBlock>
    </Panel>
  );
}
export function Parameters({ row }: { row: ProductionRow }) {
  const [search, setSearch] = useState("");
  const parameters = businessEntries(row).filter(([k]) => !(k in metadata));
  const valued = parameters.filter(
    ([, v]) => v !== null && v !== undefined && v !== "",
  );
  const filtered = valued.filter(([k, v]) => `${k} ${text(v)}`.toLowerCase().includes(search.toLowerCase()));
  return (
    <section className="pt-detail-section pt-parameters" aria-label="测试项与参数">
      <header className="pt-detail-heading"><h4>测试项与参数</h4><Badge>{valued.length} 个参数</Badge></header>
      <label>
        搜索参数
        <input
          aria-label="搜索参数"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </label>
      <div
        className="pt-table"
        tabIndex={0}
        role="region"
        aria-label="测试参数表"
      >
        <table>
          <thead>
            <tr>
              <th>参数</th>
              <th>值</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(([k, v]) => (
              <tr key={k}>
                <th>{k}</th>
                <td>{text(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!valued.length && <EmptyState title="暂无测试参数" />}
      {valued.length > 0 && !filtered.length && <EmptyState title="没有匹配的参数" description="请调整搜索词" />}
      {parameters.length > valued.length && <details>
        <summary>未提供的参数（{parameters.length - valued.length}）</summary>
        {parameters
          .filter(([, v]) => v === null || v === undefined || v === "")
          .map(([k]) => (
            <p key={k}>{k}：未提供</p>
          ))}
      </details>}
      <details>
        <summary>原始记录</summary>
        <pre>{JSON.stringify(Object.fromEntries(businessEntries(row)), null, 2)}</pre>
      </details>
    </section>
  );
}
export function Compare({
  primary,
  comparison,
}: {
  primary: ViewedEvent | null;
  comparison: ViewedEvent | null;
}) {
  if (!primary || !comparison)
    return (
      <EmptyState title="参数尚未核对，请先复查证据。" />
    );
  const keys = [
    ...new Set([...businessEntries(primary.row), ...businessEntries(comparison.row)].map(([key]) => key)),
  ];
  return (
    <Panel title="记录对照" className="pt-comparison">
      <div className="pt-event-pair">
        {([primary, comparison] as const).map((event, i) => <section key={i} className="pt-event-role" data-role={i === 0 ? "primary" : "comparison"} aria-label={i === 0 ? "主要事件" : "对照事件"}>
          <h4>{i === 0 ? "主要事件" : "对照事件"}</h4><ResultBadge value={event.row.status} />
          <p>{text(event.row.sn)} · {text(event.row.devicename)}</p><p className="pt-meta">{localTime(event.row.timestamp)}</p>
        </section>)}
      </div>
      <div
        className="pt-table"
        tabIndex={0}
        role="region"
        aria-label="记录对照表"
      >
        <table>
          <thead>
            <tr>
              <th>字段</th>
              <th>比较</th>
              <th>主要事件</th>
              <th>对照事件</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => {
              const a = primary.row[k],
                b = comparison.row[k],
                absent = a == null || b == null || a === "" || b === "";
              return (
                <tr key={k} data-diff={!absent && JSON.stringify(a) !== JSON.stringify(b) ? "different" : undefined}>
                  <th scope="row">{metadata[k] || k}</th>
                  <td><Badge tone={absent || JSON.stringify(a) === JSON.stringify(b) ? "neutral" : "warning"}>
                    {absent ? "未提供" : JSON.stringify(a) === JSON.stringify(b) ? "相同" : "不同"}
                  </Badge></td>
                  <td>{k === "status" ? <ResultBadge value={a} /> : text(a)}</td>
                  <td>{k === "status" ? <ResultBadge value={b} /> : text(b)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
export function EventSidebar({
  api,
  event,
  location: l,
  go,
  close,
  investigation,
  readOnly,
  onPrimary,
  onComparison,
  onLog,
  logBusy,
  onEvidenceScope,
}: {
  api: Api;
  event: ViewedEvent;
  location: Location;
  go: BoardProps["go"];
  close: () => void;
  investigation: Investigation | null;
  readOnly: boolean;
  onPrimary: (e: ViewedEvent) => void;
  onComparison: (e: ViewedEvent) => void;
  onLog: (selection: CapturedLog) => void;
  logBusy: boolean;
  onEvidenceScope: (range: Scope, csn: string) => void;
}) {
  const [logs, setLogs] = useState(false),
    [csn, setCSN] = useState(investigation?.context.candidate_csn || ""),
    [range, setRange] = useState<Scope>(
      investigation?.context.evidence_range || {
        start: l.scope.start,
        end: l.scope.end,
      },
    ),
    [form, setForm] = useState(range),
    [appliedCSN, setAppliedCSN] = useState(csn),
    [before, setBefore] = useState<string>(),
    [error, setError] = useState("");
  const status = useRead(
    (s) => api.productionStatus(event.projectId, s),
    [api, event.projectId],
    logs,
  );
  const evidence = useRead(
    (s) =>
      api.productionEvidence(
        event.projectId,
        {
          ...range,
          ...(appliedCSN ? { sn: appliedCSN } : {}),
          ...(event.row.orderid ? { order_id: String(event.row.orderid) } : {}),
          ...(event.row.devicename
            ? { device: String(event.row.devicename) }
            : {}),
          before_id: before,
        },
        s,
      ),
    [api, event.projectId, range, appliedCSN, before],
    logs && !!status.data?.capabilities.evidence?.available,
  );
  return (
    <aside className="pt-sidebar" aria-label="测试详情">
      <header className="pt-drawer-header">
        <div><p className="pt-eyebrow">事件浏览</p><h3>{event.kind === "production" ? "生产测试" : "过站"}详情</h3><ResultBadge value={event.row.status} /></div>
        <button type="button" onClick={close}>关闭测试详情</button>
      </header>
      <section className="pt-detail-section" aria-label="调查选择">
        <h4>调查选择</h4>
        <div className="pt-selection-context">
          <p><strong>当前主要事件</strong> · {investigation?.primary ? `${text(investigation.primary.descriptor.sn)} · ${localTime(investigation.primary.descriptor.timestamp)}` : "尚未选择"}</p>
          <p><strong>当前对照事件</strong> · {investigation?.comparison ? `${text(investigation.comparison.descriptor.sn)} · ${localTime(investigation.comparison.descriptor.timestamp)}` : "尚未选择"}</p>
        </div>
        <div className="pt-actions">
          <button type="button" className="pt-button-primary" disabled={readOnly} onClick={() => onPrimary(event)}>设为调查对象</button>
          <button type="button" disabled={readOnly || !investigation?.primary} onClick={() => onComparison(event)}>选作对照</button>
        </div>
      </section>
      {logs ? (
        <section className="pt-detail-section" aria-label="候选日志">
          <button type="button" onClick={() => setLogs(false)}>
            返回测试详情
          </button>
          <h3>候选日志 · 关联待核对</h3>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (
                +new Date(form.end) <= +new Date(form.start) ||
                +new Date(form.end) - +new Date(form.start) > 31 * 86400000
              ) {
                setError("日志时间须大于 0 且不超过 31 天");
                return;
              }
              setError("");
              setRange(form);
              setAppliedCSN(csn);
              setBefore(undefined);
              onEvidenceScope(form, csn);
            }}
          >
            <label>
              候选 CSN
              <input
                aria-label="候选 CSN"
                value={csn}
                onChange={(e) => setCSN(e.target.value)}
              />
            </label>
            <label>
              日志开始时间
              <input
                aria-label="日志开始时间"
                type="datetime-local"
                step="0.001"
                value={localInput(form.start)}
                onChange={(e) =>
                  e.target.value &&
                  setForm({
                    ...form,
                    start: new Date(e.target.value).toISOString(),
                  })
                }
              />
            </label>
            <label>
              日志结束时间
              <input
                aria-label="日志结束时间"
                type="datetime-local"
                step="0.001"
                value={localInput(form.end)}
                onChange={(e) =>
                  e.target.value &&
                  setForm({
                    ...form,
                    end: new Date(e.target.value).toISOString(),
                  })
                }
              />
            </label>
            <button type="submit">查找日志</button>
          </form>
          {error && <p role="alert">{error}</p>}
          <ReadBlock label="日志能力" state={status}>
            {(s) => (
              <>
                {!s.capabilities.evidence?.available && (
                  <p>日志索引尚未配置；其他调查可继续。</p>
                )}
                {!s.capabilities.evidence_content?.available && (
                  <p>日志下载不可用</p>
                )}
              </>
            )}
          </ReadBlock>
          <ReadBlock label="候选日志" state={evidence}>
            {(page) => (
              <>
                <Coverage data={page} />
                {!page.items.length && (
                  <p>无候选日志，可扩大日志范围；不改变原问题时段。</p>
                )}
                {page.items.map((row, i) => (
                  <article key={i}>
                    <p>
                      日志 CSN {text(row.csn)} · 上位机 {text(row.devicename)} ·
                      工具 {text(row.toolsname)}
                    </p>
                    <p>
                      工具配置审核单 {text(row.orderid)} · 上传时间{" "}
                      {localTime(row.createtime)}
                    </p>
                    {typeof row.id === "string" &&
                      /^[1-9][0-9]{0,19}$/.test(row.id) && (
                        <>
                          <button
                            type="button"
                            disabled={
                              readOnly ||
                              logBusy ||
                              !investigation?.primary ||
                              investigation.logs.length >= 5 ||
                              investigation.logs.some(
                                (x) => x.source_log_id === row.id,
                              )
                            }
                            onClick={() =>
                              onLog({
                                snapshot_id: page.snapshot_id,
                                offset: page.offset + i,
                                source_log_id: String(row.id),
                              })
                            }
                          >
                            加入调查 {row.id}
                          </button>
                          {status.data?.capabilities.evidence_content
                            ?.available && (
                              <a
                                href={api.productionEvidenceUrl(
                                  event.projectId,
                                  row.id,
                                )}
                                download
                              >
                                下载日志证据
                              </a>
                            )}
                        </>
                      )}
                  </article>
                ))}
                {page.next_before_id && (
                  <button
                    type="button"
                    onClick={() => setBefore(page.next_before_id!)}
                  >
                    更多日志
                  </button>
                )}
              </>
            )}
          </ReadBlock>
        </section>
      ) : (
        <>
          <section className="pt-detail-section" aria-label="事件核心事实">
            <h4>事件核心事实</h4>
            <dl>
              {Object.entries(metadata).map(([key, label]) => (
                <div key={key}>
                  <dt>{label}</dt>
                  <dd>
                    {key === "timestamp"
                      ? localTime(event.row[key])
                      : key === "status"
                        ? <ResultBadge value={event.row[key]} />
                        : key === "workstagesid"
                          ? sourceName(l, "stage_id", event.row[key])
                          : key === "softwareid"
                            ? sourceName(l, "software_id", event.row[key])
                            : text(event.row[key])}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
          <section className="pt-detail-section" aria-label="相关记录">
            <h4>相关记录</h4>
            <div className="pt-actions">
              {typeof event.row.softwareid === "string" &&
                /^[1-9][0-9]{0,19}$/.test(event.row.softwareid) && (
                  <button
                    type="button"
                    onClick={() => {
                      close();
                      go({
                        ...l,
                        view: "catalog",
                        catalog: "software_versions",
                        parentId: String(event.row.softwareid),
                      });
                    }}
                  >
                    查看工具版本目录
                  </button>
                )}
              <button type="button" onClick={() => setLogs(true)}>
                查找候选日志
              </button>
              {event.row.sn && l.view !== "history" ? (
                <button
                  type="button"
                  onClick={() => {
                    close();
                    go({
                      ...l,
                      view: "history",
                      historySN: String(event.row.sn),
                      historyRange: { start: l.scope.start, end: l.scope.end },
                      cursor: undefined,
                    });
                  }}
                >
                  查看 {String(event.row.sn)} 履历
                </button>
              ) : null}
              <button
                type="button"
                onClick={() =>
                  void navigator.clipboard?.writeText(
                    Object.entries(metadata)
                      .map(([k, v]) => `${v}：${text(event.row[k])}`)
                      .join("\n"),
                  )
                }
              >
                复制这次测试信息
              </button>
            </div>
          </section>
          <Parameters row={event.row} />
        </>
      )}
    </aside>
  );
}
