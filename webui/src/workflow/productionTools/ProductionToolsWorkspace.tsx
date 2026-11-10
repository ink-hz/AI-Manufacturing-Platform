import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { createWorkflowApi } from "../api";
import type {
  Investigation,
  InvestigationContext,
  Scope,
  ViewedEvent,
} from "./types";
import {
  ActivityBoard,
  AnomaliesBoard,
  OverviewBoard,
  ProjectBoard,
  ReadBlock,
} from "./boards";
import {
  CatalogPage,
  Compare,
  EventSidebar,
  HistoryPage,
  Records,
} from "./details";
import {
  drill,
  fieldNames,
  localInput,
  localTime,
  queryScope,
  recent,
  removeScope,
  text,
  today,
  useRead,
  type Location,
} from "./context";
import { InvestigationPanel, useInvestigation } from "./investigations";
import "./productionTools.css";
export function validProductionHandoff(value: string | null) {
  return value &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      value,
    )
    ? value
    : undefined;
}
export function ProductionToolsWorkspace({
  api,
  readOnly,
  userId,
  handoffId,
  onDirty,
}: {
  api: ReturnType<typeof createWorkflowApi>;
  readOnly: boolean;
  userId: string;
  handoffId?: string;
  onDirty?: (dirty: boolean) => void;
}) {
  const [loc, setLoc] = useState<Location>(() => ({
      view: "overview",
      projectId: "",
      scope: today(),
      labels: {},
      inherited: false,
    })),
    [event, setEvent] = useState<ViewedEvent | null>(null),
    [refresh, setRefresh] = useState(0),
    [directoryBefore, setDirectoryBefore] = useState<string>(),
    [projects, setProjects] = useState<{ id: string; name: string }[]>([]),
    [validation, setValidation] = useState(""),
    [filterNotice, setFilterNotice] = useState(""),
    [replacement, setReplacement] = useState<ViewedEvent | null>(null),
    [leave, setLeave] = useState<(() => void) | null>(null),
    [lookup, setLookup] = useState(""),
    [search, setSearch] = useState<Partial<Scope>>({}),
    [range, setRange] = useState(() => ({
      start: localInput(loc.scope.start),
      end: localInput(loc.scope.end),
    }));
  const historyRef = useRef<Location[]>([loc]),
    historyIndex = useRef(0),
    latestLoc = useRef(loc),
    host = useRef<HTMLElement>(null);
  latestLoc.current = loc;
  const global = useRead(
    (s) => api.productionStatus(undefined, s),
    [api, refresh],
    true,
    [api],
  );
  const directory = useRead(
    (s) => api.productionProjects({ before_id: directoryBefore }, s),
    [api, directoryBefore, refresh],
    !!global.data?.configured,
  );
  useEffect(() => {
    if (directory.data)
      setProjects((old) =>
        directoryBefore
          ? [
              ...old,
              ...directory.data!.items.filter(
                (p) => !old.some((o) => o.id === p.id),
              ),
            ]
          : directory.data!.items,
      );
  }, [directory.data, directoryBefore]);
  const names = useRead(
    (s) =>
      api.productionAnalysis(
        loc.projectId,
        { start: loc.scope.start, end: loc.scope.end, view: "stages" },
        s,
      ),
    [api, loc.projectId, loc.scope.start, loc.scope.end, refresh],
    !!loc.projectId && !!global.data?.configured,
  );
  const orders = useRead(
    (s) => api.productionCatalog(loc.projectId, "review_orders", {}, s),
    [api, loc.projectId, refresh],
    !!loc.projectId && loc.view === "records" && !!global.data?.configured,
  );
  useEffect(() => {
    if (!names.data) return;
    setLoc((old) => {
      if (old.projectId !== names.data!.source_project_id) return old;
      const labels = { ...old.labels };
      for (const item of names.data!.items) {
        if (item.stage_id && item.stage_name)
          labels[`stage_id:${item.stage_id}`] = item.stage_name;
        if (item.software_id && item.software_name)
          labels[`software_id:${item.software_id}`] = item.software_name;
      }
      return { ...old, labels };
    });
  }, [names.data]);
  const restoreLocation = useCallback((d: Investigation) => {
    setEvent(null);
    setLoc((old) => ({
      ...old,
      view: d.context.view,
      projectId: d.source_project_id,
      scope: queryScope(d.context),
      historySN:
        d.context.history_sn ||
        d.context.sn ||
        String(d.primary?.descriptor.sn || ""),
      savedSymptom: d.context.symptom,
      historyRange: d.context.history_range,
      recentRange: d.context.recent_range,
      evidenceRange: d.context.evidence_range,
      candidateCSN: d.context.candidate_csn,
      labels: {
        ...(old.projectId === d.source_project_id ? old.labels : {}),
        project:
          old.projectId === d.source_project_id
            ? old.labels.project || `源项目 ${d.source_project_id}`
            : `源项目 ${d.source_project_id}`,
      },
      selectedError: !!(
        d.context.error_code || d.context.missing_fields?.includes("error_code")
      ),
      inherited: true,
      cursor: undefined,
    }));
  }, []);
  const context: InvestigationContext = useMemo(
    () => ({
      ...loc.scope,
      view: loc.view,
      history_sn: loc.historySN || undefined,
      symptom:
        loc.savedSymptom ||
        [
          loc.labels.project || `源项目 ${loc.projectId}`,
          loc.scope.stage_id
            ? loc.labels[`stage_id:${loc.scope.stage_id}`] ||
              loc.labels.stage_id
            : undefined,
          loc.scope.software_id
            ? loc.labels[`software_id:${loc.scope.software_id}`] ||
              loc.labels.software_id
            : undefined,
          loc.scope.error_code ? `错误码 ${loc.scope.error_code}` : undefined,
        ]
          .filter(Boolean)
          .join(" · ")
          .slice(0, 1000),
      recent_range: loc.recentRange,
      evidence_range: loc.evidenceRange,
      candidate_csn: loc.candidateCSN,
      ...(loc.view === "history"
        ? {
            history_range: loc.historyRange || {
              start: loc.scope.start,
              end: loc.scope.end,
            },
          }
        : {}),
    }),
    [
      loc.scope,
      loc.labels,
      loc.view,
      loc.historyRange,
      loc.historySN,
      loc.savedSymptom,
      loc.recentRange,
      loc.evidenceRange,
      loc.candidateCSN,
    ],
  );
  const investigation = useInvestigation({
    api,
    projectId: loc.projectId,
    userId,
    readOnly,
    context,
    onRestore: restoreLocation,
    onDirty,
  });
  const controllerRef = useRef(investigation);
  controllerRef.current = investigation;
  const navigate = (next: Location, push = true) => {
    setEvent(next.inspected || null);
    setValidation("");
    setSearch({});
    const current = {
      ...latestLoc.current,
      scroll: host.current?.scrollTop || 0,
      inspected: event || undefined,
    };
    historyRef.current[historyIndex.current] = current;
    if (push) {
      historyRef.current = historyRef.current.slice(
        0,
        historyIndex.current + 1,
      );
      historyRef.current.push(next);
      historyIndex.current++;
      window.history.pushState(
        {
          ...window.history.state,
          productionWorkbench: { userId, index: historyIndex.current },
        },
        "",
        window.location.href,
      );
    }
    setLoc(next);
  };
  const go = (next: Location) => {
    if (next.scope !== latestLoc.current.scope)
      next = { ...next, savedSymptom: undefined };
    if (next.projectId !== latestLoc.current.projectId) {
      void (async () => {
        if (investigation.dirty && !(await investigation.flush())) {
          setLeave(() => () => navigate(next));
          return;
        }
        investigation.closeHandoff();
        navigate(next);
      })();
    } else navigate(next);
  };
  const back = () => {
    if (historyIndex.current > 0) window.history.back();
  };
  useEffect(() => {
    const onPop = (e: PopStateEvent) => {
      const saved = e.state?.productionWorkbench;
      if (!saved || saved.userId !== userId || !historyRef.current[saved.index])
        return;
      const next = historyRef.current[saved.index];
      const apply = () => {
        historyIndex.current = saved.index;
        setEvent(next.inspected || null);
        setLoc(next);
      };
      if (
        next.projectId !== latestLoc.current.projectId &&
        controllerRef.current.dirty
      ) {
        void controllerRef.current
          .flush()
          .then((d) => (d ? apply() : setLeave(() => apply)));
      } else apply();
    };
    window.history.replaceState(
      { ...window.history.state, productionWorkbench: { userId, index: 0 } },
      "",
      window.location.href,
    );
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [userId]);
  useEffect(() => {
    setRange({
      start: localInput(
        (loc.view === "history" ? loc.historyRange : undefined)?.start ||
          loc.scope.start,
      ),
      end: localInput(
        (loc.view === "history" ? loc.historyRange : undefined)?.end ||
          loc.scope.end,
      ),
    });
    if (host.current) host.current.scrollTop = loc.scroll || 0;
  }, [loc]);
  const restoredId = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (handoffId && restoredId.current !== handoffId) {
      restoredId.current = handoffId;
      void investigation.restore(handoffId, true);
    }
  }, [handoffId]);
  const props = {
    api,
    location: loc,
    go,
    inspect: setEvent,
    refresh,
    onRecent: (scope: Scope) =>
      setLoc((old) => ({ ...old, recentRange: scope })),
  };
  function board(view: "overview" | "anomalies" | "activity") {
    go({
      ...loc,
      view,
      scope: view === "activity" && !loc.inherited ? recent(120) : loc.scope,
      inherited: view === "activity" ? true : loc.inherited,
      cursor: undefined,
    });
  }
  function applyRange() {
    const start = new Date(range.start),
      end = new Date(range.end);
    if (
      !isFinite(+start) ||
      !isFinite(+end) ||
      +end <= +start ||
      +end - +start > 31 * 86400000
    ) {
      setValidation("请选择有效的时间，范围须大于 0 且不超过 31 天。");
      return;
    }
    const scope = {
      ...loc.scope,
      start: start.toISOString(),
      end: end.toISOString(),
    };
    go(
      loc.view === "history"
        ? {
            ...loc,
            historyRange: { start: scope.start, end: scope.end },
            cursor: undefined,
          }
        : { ...loc, scope, inherited: true, cursor: undefined },
    );
  }
  const activeDraft = investigation.handoff || investigation.draft;
  return (
    <section
      ref={host}
      className="wf-production-tools"
      aria-label="产测管理工作区"
    >
      <header>
        <h2>产测管理</h2>
        <p>
          从项目变化定位问题，再核对源事件和日志。外部产测源只读；记录与审核单不代表质量放行。
        </p>
        <nav className="pt-nav" aria-label="产测主导航">
          {(
            [
              ["overview", "运行总览"],
              ["anomalies", "测试异常"],
              ["activity", "上位机活动"],
            ] as const
          ).map(([id, label]) => (
            <button
              type="button"
              key={id}
              aria-pressed={loc.view === id}
              onClick={() => board(id)}
            >
              {label}
            </button>
          ))}
        </nav>
        <div className="pt-actions">
          <button
            type="button"
            onClick={back}
            disabled={historyIndex.current === 0}
          >
            返回
          </button>
          <button
            type="button"
            onClick={() =>
              go({
                ...loc,
                view: "history",
                historySN: lookup,
                cursor: undefined,
              })
            }
          >
            查 SN
          </button>
          <button
            type="button"
            onClick={() => go({ ...loc, view: "records", cursor: undefined })}
          >
            查记录
          </button>
          <button
            type="button"
            onClick={() =>
              host.current
                ?.querySelector<HTMLInputElement>(
                  '[aria-label="交接号或内部恢复链接"]',
                )
                ?.focus()
            }
          >
            恢复调查
          </button>
          <button
            type="button"
            disabled={!loc.projectId}
            onClick={() => go({ ...loc, view: "catalog" })}
          >
            工具与配置
          </button>
        </div>
      </header>
      <ReadBlock label="来源配置" state={global}>
        {(s) => (
          <>
            {!s.configured && (
              <p>尚未配置产测数据源，请联系管理员；不显示全零看板。</p>
            )}
          </>
        )}
      </ReadBlock>
      {directory.error && (
        <p role="alert">
          源项目目录暂不可用，已授权保存内容仍可恢复。
          <button type="button" onClick={directory.retry}>
            重试源项目目录
          </button>
        </p>
      )}
      {directory.loading && <p role="status">正在读取源项目目录…</p>}
      <div className="pt-scope">
        <label>
          源项目
          <select
            aria-label="源项目"
            value={loc.projectId}
            onChange={(e) => {
              const p = projects.find((p) => p.id === e.target.value);
              if (p)
                go({
                  view: "project",
                  projectId: p.id,
                  scope: { start: loc.scope.start, end: loc.scope.end },
                  labels: { project: p.name },
                  inherited: loc.inherited,
                });
              else if (!e.target.value)
                go({
                  ...loc,
                  view: "overview",
                  projectId: "",
                  scope: { start: loc.scope.start, end: loc.scope.end },
                  labels: {},
                });
            }}
          >
            <option value="">全部可访问源项目</option>
            {loc.projectId && !projects.some((p) => p.id === loc.projectId) && (
              <option value={loc.projectId}>
                {loc.labels.project || `已保存源项目 ${loc.projectId}`}
              </option>
            )}
            {projects.map((p) => (
              <option value={p.id} key={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          开始时间
          <input
            aria-label="开始时间"
            type="datetime-local"
            value={range.start}
            onChange={(e) => setRange({ ...range, start: e.target.value })}
          />
        </label>
        <label>
          结束时间
          <input
            aria-label="结束时间"
            type="datetime-local"
            value={range.end}
            onChange={(e) => setRange({ ...range, end: e.target.value })}
          />
        </label>
        <button type="button" onClick={applyRange}>
          应用时间范围
        </button>
        <button type="button" onClick={() => setRefresh((x) => x + 1)}>
          重新读取
        </button>
        {directory.data?.has_more && directory.data.next_before_id && (
          <button
            type="button"
            onClick={() => setDirectoryBefore(directory.data!.next_before_id!)}
          >
            读取更多源项目
          </button>
        )}
      </div>
      <p className="pt-meta">
        {loc.labels.project || "全部可访问源项目"} · 问题时间{" "}
        {localTime(loc.scope.start)} — {localTime(loc.scope.end)} ·{" "}
        {Intl.DateTimeFormat().resolvedOptions().timeZone} ·{" "}
        {loc.view === "overview" ? "范围见上" : "固定问题时间，已暂停自动更新"}{" "}
        · 查看截至 {localTime(loc.scope.end)} 的数据
      </p>
      <div className="pt-chips">
        {Object.entries(fieldNames)
          .filter(
            ([key]) =>
              (loc.scope as unknown as Record<string, unknown>)[key] !==
                undefined || loc.scope.missing_fields?.includes(key as never),
          )
          .map(([key, label]) => (
            <button
              type="button"
              key={key}
              onClick={() => {
                if (key === "software_id" || key === "config_log_id")
                  setFilterNotice("对象条件已移除，相应版本条件同时清除。");
                go({
                  ...loc,
                  scope: removeScope(loc.scope, key),
                  cursor: undefined,
                });
              }}
            >
              {label}：
              {loc.scope.missing_fields?.includes(key as never)
                ? "源未提供"
                : loc.labels[key] ||
                  text(
                    (loc.scope as unknown as Record<string, unknown>)[key],
                  )}{" "}
              ×
            </button>
          ))}
      </div>
      {filterNotice && <p role="status">{filterNotice}</p>}
      {validation && <p role="alert">{validation}</p>}
      {leave && (
        <aside role="alert">
          <p>保存失败，本机修改已保留；可留在原项目重试。</p>
          <button type="button" onClick={() => setLeave(null)}>
            留在原页
          </button>
          <button
            type="button"
            onClick={() => {
              leave();
              setLeave(null);
            }}
          >
            保留本机修改后离开
          </button>
        </aside>
      )}
      {(loc.view === "history" || loc.view === "records") && (
        <form
          className="pt-search"
          onSubmit={(e) => {
            e.preventDefault();
            if (loc.view === "history") {
              if (lookup.trim())
                go({
                  ...loc,
                  historySN: lookup.trim(),
                  historyRange: loc.historyRange || {
                    start: loc.scope.start,
                    end: loc.scope.end,
                  },
                });
            } else
              go({
                ...loc,
                scope: { ...loc.scope, ...search },
                cursor: undefined,
              });
          }}
        >
          <label>
            精确 SN
            <input
              aria-label="精确 SN"
              value={loc.view === "history" ? lookup : search.sn || ""}
              onChange={(e) =>
                loc.view === "history"
                  ? setLookup(e.target.value)
                  : setSearch({ ...search, sn: e.target.value || undefined })
              }
            />
          </label>
          {loc.view === "records" && (
            <>
              <label>
                精确设备
                <input
                  aria-label="精确设备"
                  value={search.device || ""}
                  onChange={(e) =>
                    setSearch({
                      ...search,
                      device: e.target.value || undefined,
                    })
                  }
                />
              </label>
              <label>
                结果
                <select
                  aria-label="结果"
                  value={search.status || ""}
                  onChange={(e) =>
                    setSearch({
                      ...search,
                      status: (e.target.value as Scope["status"]) || undefined,
                    })
                  }
                >
                  <option value="">全部结果</option>
                  <option value="1">通过 PASS</option>
                  <option value="2">失败 FAIL</option>
                </select>
              </label>
              <details>
                <summary>高级条件</summary>
                <label>
                  测试环节筛选
                  <select
                    aria-label="测试环节筛选"
                    value={`${search.stage_id || ""}|${search.software_id || ""}`}
                    onChange={(e) => {
                      const item = names.data?.items.find(
                        (a) =>
                          `${a.stage_id || "missing"}|${a.software_id || "missing"}` ===
                          e.target.value,
                      );
                      if (item) {
                        const scoped = drill(loc.scope, item, [
                          "stage_id",
                          "software_id",
                        ]);
                        setSearch({
                          ...search,
                          stage_id: scoped.stage_id,
                          software_id: scoped.software_id,
                          software_version: undefined,
                          missing_fields: scoped.missing_fields,
                        });
                        setFilterNotice("切换测试工具已清除旧软件版本条件");
                      }
                    }}
                  >
                    <option value="|">沿用当前范围</option>
                    {names.data?.items.map((a, i) => (
                      <option
                        key={i}
                        value={`${a.stage_id || "missing"}|${a.software_id || "missing"}`}
                      >
                        {a.stage_name || "源未提供阶段"} ·{" "}
                        {a.software_name || "源未提供工具"}
                      </option>
                    ))}
                  </select>
                </label>
                {names.error && <p>测试环节名称未取得，可继续当前范围查询。</p>}
                <label>
                  工具配置审核单
                  <select
                    aria-label="工具配置审核单"
                    value={search.order_id || ""}
                    onChange={(e) =>
                      setSearch({
                        ...search,
                        order_id: e.target.value || undefined,
                      })
                    }
                  >
                    <option value="">沿用当前范围</option>
                    {orders.data?.items.map((a, i) => (
                      <option key={i} value={String(a.id)}>
                        {text(
                          a.name ||
                            a.title ||
                            a.description ||
                            `工具配置审核单 ${a.id}`,
                        )}
                      </option>
                    ))}
                  </select>
                </label>
                {orders.data && !orders.data.complete && (
                  <p>审核目录部分读取，可在工具与配置继续浏览。</p>
                )}

                {(
                  [
                    "error_code",
                    "barcode",
                    "software_version",
                    "config_version",
                  ] as const
                ).map((key) => (
                  <label key={key}>
                    {fieldNames[key]}
                    <input
                      aria-label={fieldNames[key]}
                      value={search[key] || ""}
                      onChange={(e) =>
                        setSearch({
                          ...search,
                          [key]: e.target.value || undefined,
                        })
                      }
                    />
                  </label>
                ))}
                <p>
                  阶段、工具及配置由项目环节、分布或目录点击带入；审核单指工具配置审核流程。
                </p>
              </details>
            </>
          )}
          <button type="submit" disabled={!loc.projectId}>
            查询产测数据
          </button>
        </form>
      )}
      {global.data?.configured &&
      (loc.view === "overview" || !loc.projectId) ? (
        <>
          <OverviewBoard {...props} />
          {!loc.projectId && loc.view !== "overview" && (
            <p>先选择项目及时间范围，不逐项目扫描 SN。</p>
          )}
        </>
      ) : (
        global.data?.configured &&
        loc.projectId && (
          <main className="pt-content">
            {loc.view === "project" ? (
              <ProjectBoard {...props} />
            ) : loc.view === "anomalies" ? (
              <AnomaliesBoard {...props} />
            ) : loc.view === "activity" || loc.view === "device" ? (
              <ActivityBoard key={`${loc.projectId}-${loc.view}`} {...props} />
            ) : loc.view === "records" ? (
              <Records {...props} />
            ) : loc.view === "history" ? (
              loc.historySN ? (
                <HistoryPage {...props} />
              ) : (
                <p>请输入 SN，在当前项目与时间内查找。</p>
              )
            ) : loc.view === "catalog" ? (
              <CatalogPage {...props} />
            ) : loc.view === "compare" ? (
              <Compare {...investigation.raw} />
            ) : null}
          </main>
        )
      )}
      <InvestigationPanel
        controller={investigation}
        readOnly={readOnly}
        onCompare={() => go({ ...loc, view: "compare" })}
        onCandidate={setEvent}
      />
      {replacement && (
        <aside role="alert">
          <p>
            替换主要事件将移除当前对照和全部日志引用；已生成的固定交接版本不变。
          </p>
          <button
            type="button"
            onClick={() => {
              void investigation.choose("primary", replacement);
              setReplacement(null);
            }}
          >
            确认替换主要事件
          </button>
          <button type="button" onClick={() => setReplacement(null)}>
            取消替换
          </button>
        </aside>
      )}
      {event && event.projectId === loc.projectId && (
        <EventSidebar
          key={`${event.snapshot_id}-${event.offset}`}
          api={api}
          event={event}
          location={loc}
          go={go}
          close={() => setEvent(null)}
          investigation={activeDraft}
          readOnly={readOnly || !!investigation.handoff}
          onPrimary={(e) => {
            if (
              activeDraft?.primary &&
              (activeDraft.primary.snapshot_id !== e.snapshot_id ||
                activeDraft.primary.offset !== e.offset)
            )
              setReplacement(e);
            else void investigation.choose("primary", e);
          }}
          onComparison={(e) => void investigation.choose("comparison", e)}
          onLog={(id) => void investigation.addLog(id)}
          onEvidenceScope={(scope, csn) =>
            setLoc((old) => ({
              ...old,
              evidenceRange: scope,
              candidateCSN: csn || undefined,
            }))
          }
        />
      )}
    </section>
  );
}
