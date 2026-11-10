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
    <>
      <Coverage data={page} />
      {!page.complete && (
        <p>
          仅显示部分记录，不能由捕获样本推算全范围影响；可缩小时间或按 SN /
          上位机查询。
        </p>
      )}
      {page.redacted_fields.length > 0 && (
        <p>源已隐藏字段：{page.redacted_fields.join("、")}</p>
      )}
      {!page.items.length ? (
        <p>
          当前范围暂无{kind === "stopover" ? "过站" : "测试"}记录，范围外未知。
        </p>
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
                      {page.offset + i + 1}
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
                        <small>原症状命中</small>
                      )}
                    {result(row.status)}
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
      <div className="pt-actions">
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
          上一页快照
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
          下一页快照
        </button>
      </div>
    </>
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
    <ReadBlock label="测试记录" state={state}>
      {(page) => <RecordTable page={page} {...props} />}
    </ReadBlock>
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
    <>
      <h3>SN {l.historySN} · 当前范围记录</h3>
      <p>
        履历检索时间 {localTime(scope.start)} — {localTime(scope.end)}
        ；原问题时段仍保留在顶部。
      </p>
      <p>
        已展开到 SN 记录：查询只继承项目、时间和
        SN。原症状保留在返回路径中，前后通过及其他工具、上位机均可见。
      </p>
      <ReadBlock label="SN 测试履历" state={production}>
        {(page) => <RecordTable page={page} {...props} />}
      </ReadBlock>
      <ReadBlock label="SN 过站履历" state={stopover}>
        {(page) => <RecordTable page={page} {...props} kind="stopover" />}
      </ReadBlock>
    </>
  );
}
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
    <>
      <h3>工具与配置</h3>
      <nav>
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
            {page.items.map((row, i) => (
              <article key={i}>
                <h4>{text(row.name || row.versions || row.id)}</h4>
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
                  {Object.entries(row)
                    .filter(
                      ([k]) =>
                        !["url", "content", "password", "secret"].includes(k),
                    )
                    .map(([k, v]) => (
                      <div key={k}>
                        <dt>
                          {(
                            {
                              name: "名称",
                              versions: "版本",
                              description: "版本说明",
                              state: "源状态",
                              orderid: "工具配置审核单",
                              id: "源记录号",
                            } as Record<string, string>
                          )[k] || k}
                        </dt>
                        <dd>{text(v)}</dd>
                      </div>
                    ))}
                </dl>
              </article>
            ))}
            {page.next_before_id && (
              <button
                type="button"
                onClick={() => setBefore(page.next_before_id!)}
              >
                继续读取源记录
              </button>
            )}
            {!page.items.length && <p>当前目录暂无记录</p>}
          </>
        )}
      </ReadBlock>
    </>
  );
}
export function Parameters({ row }: { row: ProductionRow }) {
  const [search, setSearch] = useState("");
  const parameters = Object.entries(row).filter(([k]) => !(k in metadata));
  const valued = parameters.filter(
    ([, v]) => v !== null && v !== undefined && v !== "",
  );
  return (
    <>
      <h4>测试项与参数</h4>
      <p>保留源值；未验证判定规则的字段不推断通过 / 失败，单位和规格未提供。</p>
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
              <th>字段</th>
              <th>源返回值</th>
            </tr>
          </thead>
          <tbody>
            {valued
              .filter(([k, v]) =>
                `${k} ${text(v)}`.toLowerCase().includes(search.toLowerCase()),
              )
              .map(([k, v]) => (
                <tr key={k}>
                  <th>{k}</th>
                  <td>{text(v)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      {!valued.length && <p>源未提供有值测试参数</p>}
      <details>
        <summary>源返回空值（{parameters.length - valued.length}）</summary>
        {parameters
          .filter(([, v]) => v === null || v === undefined || v === "")
          .map(([k]) => (
            <p key={k}>{k}：源返回空值</p>
          ))}
      </details>
      <details>
        <summary>辅助：原始脱敏 JSON</summary>
        <pre>{JSON.stringify(row, null, 2)}</pre>
      </details>
    </>
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
      <p>
        主要事件和对照参数尚未核对，请先恢复证据；不能将保存的定位信息当作原参数。
      </p>
    );
  const keys = [
    ...new Set([...Object.keys(primary.row), ...Object.keys(comparison.row)]),
  ];
  return (
    <>
      <h3>记录对照</h3>
      <p>
        主要事件 {localTime(primary.row.timestamp)} ·{" "}
        {result(primary.row.status)} / 对照{" "}
        {localTime(comparison.row.timestamp)} · {result(comparison.row.status)}
      </p>
      <p>跨阶段、跨工具不自动称为复测；规格未提供时不计算超限。</p>
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
                <tr key={k}>
                  <th>{metadata[k] || k}</th>
                  <td>
                    {absent
                      ? "未提供"
                      : JSON.stringify(a) === JSON.stringify(b)
                        ? "相同"
                        : "不同"}
                  </td>
                  <td>{text(a)}</td>
                  <td>{text(b)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
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
      <button type="button" onClick={close}>
        关闭测试详情
      </button>
      {logs ? (
        <>
          <button type="button" onClick={() => setLogs(false)}>
            返回测试详情
          </button>
          <h3>候选日志 · 关联待核对</h3>
          <p>
            根据项目、工具配置审核单、上传时间及上位机检索。日志 CSN 与测试 SN
            身份关系未确认，未自动互换。
          </p>
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
                    <p>
                      匹配依据：项目、日志检索时段
                      {appliedCSN ? "及显式候选 CSN" : ""}；关联仍待核对
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
                    继续读取候选日志
                  </button>
                )}
              </>
            )}
          </ReadBlock>
        </>
      ) : (
        <>
          <h3>
            {event.kind === "production" ? "生产测试" : "过站"}详情 ·{" "}
            {result(event.row.status)}
          </h3>
          <dl>
            {Object.entries(metadata).map(([key, label]) => (
              <div key={key}>
                <dt>{label}</dt>
                <dd>
                  {key === "timestamp"
                    ? localTime(event.row[key])
                    : key === "status"
                      ? result(event.row[key])
                      : key === "workstagesid"
                        ? sourceName(l, "stage_id", event.row[key])
                        : key === "softwareid"
                          ? sourceName(l, "software_id", event.row[key])
                          : text(event.row[key])}
                </dd>
              </div>
            ))}
          </dl>
          <p>
            读取 {localTime(event.captured_at)} ·
            浏览本条记录不会自动替换调查对象。
          </p>
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
            <button
              type="button"
              disabled={readOnly}
              onClick={() => onPrimary(event)}
            >
              设为调查对象
            </button>
            <button
              type="button"
              disabled={readOnly || !investigation?.primary}
              onClick={() => onComparison(event)}
            >
              选作对照
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
          <Parameters row={event.row} />
        </>
      )}
    </aside>
  );
}
