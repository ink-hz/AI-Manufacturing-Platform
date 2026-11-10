import { useCallback, useEffect, useRef, useState } from "react";
import { WorkflowError } from "../api";
import type { Api } from "./boards";
import {
  matchesContext,
  errorText,
  fieldNames,
  localTime,
  text,
} from "./context";
import type {
  Investigation,
  InvestigationContext,
  InvestigationPatch,
  ResolvedInvestigation,
  Resolution,
  ViewedEvent,
} from "./types";

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
const prefix = "production-investigation:";
export function clearProductionResume(userId: string) {
  for (const k of Object.keys(sessionStorage))
    if (k.startsWith(prefix + userId + ":")) sessionStorage.removeItem(k);
}
const cacheKey = (userId: string, projectId: string) =>
  `${prefix}${userId}:${projectId}`;
export function useInvestigation({
  api,
  projectId,
  userId,
  readOnly,
  context,
  onRestore,
  onDirty,
}: {
  api: Api;
  projectId: string;
  userId: string;
  readOnly: boolean;
  context: InvestigationContext;
  onRestore: (draft: Investigation) => void;
  onDirty?: (dirty: boolean) => void;
}) {
  const [draft, setDraft] = useState<Investigation | null>(null),
    [handoff, setHandoff] = useState<Investigation | null>(null),
    [resolved, setResolved] = useState<ResolvedInvestigation | null>(null),
    [list, setList] = useState<Investigation[]>([]),
    [note, setNote] = useState(""),
    [state, setState] = useState("尚未开始调查"),
    [error, setError] = useState(""),
    [dirty, setDirty] = useState(false),
    [conflict, setConflict] = useState<Investigation | null>(null),
    [localRecovered, setLocalRecovered] = useState(false),
    [raw, setRaw] = useState<{
      primary: ViewedEvent | null;
      comparison: ViewedEvent | null;
    }>({ primary: null, comparison: null });
  const current = useRef<Investigation | null>(null),
    pending = useRef<InvestigationPatch>({}),
    active = useRef(new AbortController()),
    contextRef = useRef(context),
    projectRef = useRef(projectId),
    epoch = useRef(0),
    queue = useRef<Promise<unknown>>(Promise.resolve()),
    pause = useRef(false),
    handoffRef = useRef<Investigation | null>(null);
  contextRef.current = context;
  projectRef.current = projectId;
  handoffRef.current = handoff;
  const cache = () => {
    if (!projectRef.current || !userId) return;
    try {
      sessionStorage.setItem(
        cacheKey(userId, projectRef.current),
        JSON.stringify({ id: current.current?.id, pending: pending.current }),
      );
    } catch {
      /* Browser storage is optional; server remains authoritative. */
    }
  };
  const install = useCallback((d: Investigation) => {
    current.current = d;
    setDraft(d);
    setNote(d.note);
    setState(`已保存 ${localTime(d.updated_at)} · 修订 ${d.version}`);
  }, []);
  const resolve = async (d: Investigation, isHandoff = false) => {
    const signal = active.current.signal,
      token = epoch.current;
    setResolved(null);
    setRaw({ primary: null, comparison: null });
    try {
      const r = isHandoff
        ? await api.resolveProductionHandoff(d.id, signal)
        : await api.resolveInvestigation(d.source_project_id, d.id, signal);
      if (signal.aborted || token !== epoch.current) return;
      setResolved(r);
      const event = (which: "primary" | "comparison"): ViewedEvent | null => {
        const part = r[which];
        return part?.state === "verified" && part.candidates.length === 1
          ? {
              ...part.candidates[0],
              projectId: d.source_project_id,
              kind: d[which]?.source_kind || "production",
              captured_at: r.captured_at,
            }
          : null;
      };
      setRaw({ primary: event("primary"), comparison: event("comparison") });
    } catch (e) {
      if (!signal.aborted && token === epoch.current) setError(errorText(e));
    }
  };
  useEffect(() => {
    onDirty?.(dirty);
    return () => onDirty?.(false);
  }, [dirty, onDirty]);
  useEffect(() => {
    const c = new AbortController();
    active.current.abort();
    active.current = c;
    const token = ++epoch.current;
    current.current = null;
    pending.current = {};
    pause.current = false;
    setDraft(null);
    setNote("");
    setDirty(false);
    setConflict(null);
    setLocalRecovered(false);
    setList([]);
    setState("尚未开始调查");
    if (!handoffRef.current) {
      setResolved(null);
      setRaw({ primary: null, comparison: null });
    } else if (handoffRef.current.source_project_id === projectId) {
      setNote(handoffRef.current.note);
      setState("固定交接版本 · 只读");
      void resolve(handoffRef.current, true);
    }
    if (projectId) {
      api
        .investigations(projectId, c.signal)
        .then((v) => {
          if (!c.signal.aborted) setList(v.items);
        })
        .catch((e) => {
          if (!c.signal.aborted) setError(errorText(e));
        });
      let cached: { id?: string; pending?: InvestigationPatch } | null = null;
      try {
        cached = JSON.parse(
          sessionStorage.getItem(cacheKey(userId, projectId)) || "null",
        );
      } catch {}
      if (cached?.id && !handoffRef.current) {
        api
          .investigation(projectId, cached.id, c.signal)
          .then((d) => {
            if (c.signal.aborted || epoch.current !== token) return;
            install(d);
            onRestore(d);
            if (cached?.pending && Object.keys(cached.pending).length) {
              pending.current = cached.pending;
              setNote(cached.pending.note ?? d.note);
              setDirty(true);
              setLocalRecovered(true);
              pause.current = true;
              setState("本机未保存修改，请核对后提交");
            }
            void resolve(d);
          })
          .catch((e) => {
            if (!c.signal.aborted) setError(errorText(e));
          });
      }
    }
    return () => {
      c.abort();
    };
  }, [api, projectId, userId]);
  useEffect(
    () => () => {
      active.current.abort();
      epoch.current++;
    },
    [],
  );
  async function flush(force = false): Promise<Investigation | null> {
    if (readOnly || handoffRef.current) {
      setState("只读，本次修改未保存");
      return null;
    }
    if (pause.current && !force) return null;
    const token = epoch.current;
    const operation = queue.current.then(async () => {
      if (token !== epoch.current) return null;
      if (!Object.keys(pending.current).length && current.current)
        return current.current;
      const patch = pending.current;
      pending.current = {};
      setState("正在保存…");
      setError("");
      try {
        const d = current.current
          ? await api.updateInvestigation(
              projectRef.current,
              current.current.id,
              { ...patch, expected_version: current.current.version },
              active.current.signal,
            )
          : await api.createInvestigation(
              projectRef.current,
              { context: contextRef.current, note: "", ...patch },
              active.current.signal,
            );
        if (token !== epoch.current) return null;
        current.current = d;
        setDraft(d);
        if (!("note" in pending.current)) setNote(d.note);
        setDirty(Object.keys(pending.current).length > 0);
        setState(`已保存 ${localTime(d.updated_at)} · 修订 ${d.version}`);
        setLocalRecovered(false);
        setConflict(null);
        pause.current = false;
        cache();
        return d;
      } catch (e) {
        if (token !== epoch.current || active.current.signal.aborted)
          return null;
        pending.current = { ...patch, ...pending.current };
        setDirty(true);
        pause.current = true;
        cache();
        if (e instanceof WorkflowError && e.status === 409) {
          setState("修订冲突：服务端版本与本机修改均已保留");
          try {
            if (current.current) {
              const server = await api.investigation(
                projectRef.current,
                current.current.id,
                active.current.signal,
              );
              if (token === epoch.current) setConflict(server);
            }
          } catch {}
        } else setState("保存失败：本机修改尚未保存，可重试");
        return null;
      }
    });
    queue.current = operation;
    return operation;
  }
  const patch = (value: InvestigationPatch) => {
    if (readOnly || handoffRef.current) return;
    pending.current = { ...pending.current, ...value };
    setDirty(true);
    setState("未保存修改");
    cache();
  };
  useEffect(() => {
    if (!current.current || handoff || readOnly || pause.current) return;
    if (JSON.stringify(context) !== JSON.stringify(current.current.context)) {
      if (
        current.current.primary &&
        !matchesContext(context, current.current.primary.descriptor)
      ) {
        setState(
          "当前浏览条件与主要事件不一致；原调查范围已保留，可返回原调查或新建范围调查",
        );
        return;
      }
      patch({ context });
    }
  }, [JSON.stringify(context), handoff, readOnly]);
  useEffect(() => {
    if (!dirty || pause.current || readOnly || handoff) return;
    const timer = setTimeout(() => void flush(), 350);
    return () => clearTimeout(timer);
  }, [dirty, note, JSON.stringify(context), handoff, readOnly]);
  async function start() {
    if (readOnly) return;
    pending.current = { ...pending.current, context: contextRef.current };
    setDirty(true);
    return flush(true);
  }
  async function choose(which: "primary" | "comparison", event: ViewedEvent) {
    if (readOnly || handoffRef.current) return;
    if (which === "comparison" && !current.current?.primary) return;
    const selection = { snapshot_id: event.snapshot_id, offset: event.offset };
    if (which === "primary") {
      delete pending.current.comparison;
      delete pending.current.logs;
    }
    patch({ [which]: selection });
    const d = await flush(true);
    if (d)
      setRaw((old) =>
        which === "primary"
          ? { primary: event, comparison: null }
          : { ...old, comparison: event },
      );
  }
  async function addLog(id: string) {
    const d = current.current;
    if (
      !d?.primary ||
      d.logs.length >= 5 ||
      d.logs.some((x) => x.source_log_id === id)
    )
      return;
    patch({ logs: [...d.logs.map((x) => x.source_log_id), id] });
    await flush(true);
  }
  async function restore(id: string, isHandoff = false) {
    if (dirty && !(await flush())) return;
    setError("");
    const signal = active.current.signal;
    try {
      const d = isHandoff
        ? await api.productionHandoff(id, signal)
        : await api.investigation(projectRef.current, id, signal);
      if (signal.aborted) return;
      pending.current = {};
      setDirty(false);
      if (isHandoff) {
        setHandoff(d);
        handoffRef.current = d;
        setNote(d.note);
        setState("固定交接版本 · 只读");
      } else {
        setHandoff(null);
        handoffRef.current = null;
        install(d);
        cache();
      }
      onRestore(d);
      if (d.source_project_id === projectRef.current)
        void resolve(d, isHandoff);
    } catch (e) {
      if (!signal.aborted) setError(errorText(e));
    }
  }
  async function generate() {
    const d = await flush(true);
    if (!d) return;
    try {
      const h = await api.createProductionHandoff(
        d.source_project_id,
        d.id,
        d.version,
        active.current.signal,
      );
      setHandoff(h);
      handoffRef.current = h;
      setState("固定交接版本已生成");
    } catch (e) {
      setError(`交接生成失败：${errorText(e)}`);
    }
  }
  async function fork() {
    if (readOnly || !handoffRef.current) return;
    try {
      const d = await api.forkProductionHandoff(
        handoffRef.current.id,
        active.current.signal,
      );
      setHandoff(null);
      handoffRef.current = null;
      pending.current = {};
      install(d);
      cache();
      onRestore(d);
      void resolve(d);
    } catch (e) {
      setError(errorText(e));
    }
  }
  async function acceptServer() {
    if (!conflict) return;
    pending.current = {};
    setDirty(false);
    install(conflict);
    setConflict(null);
    pause.current = false;
    cache();
    onRestore(conflict);
    void resolve(conflict);
  }
  async function retainLocal() {
    if (!conflict) return;
    current.current = conflict;
    setDraft(conflict);
    setConflict(null);
    pause.current = false;
    await flush(true);
  }
  return {
    canStart: !!projectId,
    draft,
    handoff,
    resolved,
    list,
    note,
    state,
    error,
    dirty,
    conflict,
    localRecovered,
    raw,
    start,
    flush,
    choose,
    addLog,
    restore,
    generate,
    fork,
    resolve: () => {
      const d = handoff || draft;
      if (d) void resolve(d, !!handoff);
    },
    setNote: (value: string) => {
      setNote(value);
      patch({ note: value });
    },
    patch,
    acceptServer,
    retainLocal,
    removeComparison: async () => {
      patch({ comparison: null });
      const d = await flush(true);
      if (d) setRaw((r) => ({ ...r, comparison: null }));
    },
    removeLog: async (id: string) => {
      patch({
        logs:
          current.current?.logs
            .filter((x) => x.source_log_id !== id)
            .map((x) => x.source_log_id) || [],
      });
      await flush(true);
    },
    returnToSaved: () => {
      if (current.current) onRestore(current.current);
    },
    newRange: async () => {
      if (dirty && !(await flush())) return;
      current.current = null;
      setDraft(null);
      setRaw({ primary: null, comparison: null });
      setResolved(null);
      pending.current = { context: contextRef.current, note: "" };
      setNote("");
      await flush(true);
    },
    closeHandoff: () => {
      setHandoff(null);
      handoffRef.current = null;
      if (current.current) {
        install(current.current);
        onRestore(current.current);
      }
    },
  };
}
export type InvestigationController = ReturnType<typeof useInvestigation>;
const stateLabel: Record<Resolution["state"], string> = {
  verified: "内容已核对（不证明源事件唯一性）",
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
}: {
  controller: InvestigationController;
  readOnly: boolean;
  onCompare: () => void;
  onCandidate: (event: ViewedEvent) => void;
}) {
  const d = c.handoff || c.draft;
  const [restoreText, setRestoreText] = useState(""),
    [linkError, setLinkError] = useState(""),
    [copyState, setCopyState] = useState("");
  return (
    <section className="pt-investigation" aria-label="当前调查">
      <h3>当前调查</h3>
      <p role="status">
        {c.state}
        {readOnly ? " · 只读管理员，本次修改不保存" : ""}
      </p>
      {c.state.includes("当前浏览条件") && (
        <div>
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
          disabled={readOnly || !!c.handoff || !c.canStart}
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
      {d && (
        <>
          <p>
            {c.handoff ? "固定交接号" : "个人调查号"} {d.id} · 修订 {d.version}{" "}
            · 有效至 {localTime(d.expires_at)}
          </p>
          <p>
            来源 {d.source_namespace} · 源项目 {d.source_project_id} · 问题时间{" "}
            {localTime(d.context.start)} — {localTime(d.context.end)}
          </p>
          {d.context.symptom && <p>保存时范围说明：{d.context.symptom}</p>}
          <p>
            {Object.entries(fieldNames)
              .flatMap(([key, label]) =>
                d.context.missing_fields?.includes(key as never)
                  ? [`${label}：源未提供`]
                  : (d.context as unknown as Record<string, unknown>)[key] !==
                      undefined
                    ? [
                        `${label}：${text((d.context as unknown as Record<string, unknown>)[key])}`,
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
          {c.handoff && (
            <>
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
                          ? [`${label}：${text(value)}`]
                          : [];
                    })
                    .join(" · ");
                  const describe = (which: "primary" | "comparison") => {
                    const event = d[which];
                    return `${which === "primary" ? "主要事件" : "对照事件"}：${
                      event
                        ? descriptorEntries(event.descriptor)
                            .map(([k, v]) => `${descriptorNames[k]}=${text(v)}`)
                            .join(" · ")
                        : "尚未选择"
                    }（保存的定位；原参数需核对）`;
                  };
                  const impact = d.impact
                    ? `交接时影响（读取 ${localTime(d.impact.captured_at)}，覆盖 ${d.impact.state}）：失败记录 ${d.impact.failure_records.numerator ?? "未知"} / ${d.impact.failure_records.denominator ?? "未知"}；失败涉及 SN ${d.impact.failed_involved_sn.numerator ?? "未知"} / ${d.impact.failed_involved_sn.denominator ?? "未知"}`
                    : "交接时影响统计未取得";
                  const summary = [
                    `交接号 ${d.id} · 版本 ${d.version}`,
                    `生成 ${localTime(d.created_at)} · 有效至 ${localTime(d.expires_at)}`,
                    `来源 ${d.source_namespace} · 项目 ${d.source_project_id}`,
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
              {copyState && <p>{copyState}</p>}
            </>
          )}
          {d.impact && (
            <div>
              <h4>保存时影响统计</h4>
              <p>
                读取 {localTime(d.impact.captured_at)} · 覆盖 {d.impact.state}
              </p>
              <p>
                失败记录 {d.impact.failure_records.numerator ?? "未知"} /
                同范围全部测试 {d.impact.failure_records.denominator ?? "未知"}{" "}
                · 失败涉及 SN {d.impact.failed_involved_sn.numerator ?? "未知"}{" "}
                / 测试 SN {d.impact.failed_involved_sn.denominator ?? "未知"}
              </p>
              <p>这是保存时源统计，与当前读取分别呈现；不是跨源原子快照。</p>
            </div>
          )}
          {(["primary", "comparison"] as const).map((which) => (
            <div key={which}>
              <h4>
                {which === "primary"
                  ? "主要事件（最多 1 条）"
                  : "对照事件（最多 1 条）"}
              </h4>
              {d[which] ? (
                <>
                  <p>
                    保存的定位：{text(d[which]!.descriptor.sn)} ·{" "}
                    {localTime(d[which]!.descriptor.timestamp)} ·{" "}
                    {text(d[which]!.descriptor.devicename)}
                  </p>
                  <details>
                    <summary>保存的事件定位字段</summary>
                    <dl>
                      {descriptorEntries(d[which]!.descriptor).map(
                        ([key, value]) => (
                          <div key={key}>
                            <dt>
                              {(
                                {
                                  workstagesid: "阶段",
                                  softwareid: "工具",
                                  version: "软件版本",
                                  configlogsid: "配置",
                                  cversion: "配置版本",
                                  devicename: "上位机",
                                  orderid: "工具配置审核单",
                                  status: "结果",
                                  errorcode: "错误码",
                                  timestamp: "事件时间",
                                } as Record<string, string>
                              )[key] || key}
                            </dt>
                            <dd>
                              {key === "timestamp"
                                ? localTime(value)
                                : text(value)}
                            </dd>
                          </div>
                        ),
                      )}
                    </dl>
                  </details>
                  <p>
                    {c.resolved?.[which]
                      ? stateLabel[c.resolved[which]!.state]
                      : "事件待核对；尚未恢复原参数"}
                  </p>
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
              ) : (
                <p>尚未选择</p>
              )}
            </div>
          ))}
          <p>
            按精确事件时间及 SN
            的有界候选检索；问题时段保持不变。原定位与当前候选分别显示，候选不自动成为已恢复参数。
          </p>
          {c.resolved && (
            <p>本次复查读取 {localTime(c.resolved.captured_at)}</p>
          )}
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
          <h4>日志引用（{d.logs.length} / 5）· 关联待核对</h4>
          {d.logs.map((log) => (
            <p key={log.source_log_id}>
              {log.source_log_id} · CSN {text(log.descriptor.csn)} ·{" "}
              {log.match_basis === "project_time_and_explicit_csn"
                ? "项目、时间与显式 CSN"
                : "项目与时间"}{" "}
              ·{" "}
              {c.resolved?.logs.find(
                (x) => x.source_log_id === log.source_log_id,
              )?.state || "未核对"}
              <button
                type="button"
                disabled={readOnly || !!c.handoff || !c.canStart}
                onClick={() => void c.removeLog(log.source_log_id)}
              >
                移除日志 {log.source_log_id}
              </button>
            </p>
          ))}
        </>
      )}
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
      {c.conflict && (
        <aside role="alert">
          <h4>修订冲突</h4>
          <p>
            服务端修订 {c.conflict.version}：{c.conflict.note}
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
      <details>
        <summary>继续我的其他草稿</summary>
        {!c.list.length && <p>当前项目暂无其他个人草稿</p>}
        {c.list.map((d) => (
          <button type="button" key={d.id} onClick={() => void c.restore(d.id)}>
            继续调查 {d.id} · {localTime(d.updated_at)}
          </button>
        ))}
      </details>
      <details open={!!c.handoff}>
        <summary>恢复调查</summary>
        <label>
          交接号或内部恢复链接
          <input
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
      </details>
    </section>
  );
}
