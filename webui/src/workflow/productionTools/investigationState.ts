import { useCallback, useEffect, useRef, useState } from "react";
import { WorkflowError } from "../api";
import type { Api } from "./boards";
import { matchesContext, errorText, localTime, queryScope } from "./context";
import type {
  Investigation,
  InvestigationContext,
  InvestigationPatch,
  ViewedEvent,
} from "./types";
import { readProductionResume, saveProductionResume } from "./resume";
import { useInvestigationResolution } from "./resolution";
export function useInvestigation({
  api,
  projectId,
  userId,
  readOnly,
  context,
  onRestore,
  onDirty,
  onLocalRestore,
  canStart,
}: {
  api: Api;
  projectId: string;
  userId: string;
  readOnly: boolean;
  context: InvestigationContext;
  onRestore: (draft: Investigation) => void;
  onDirty?: (dirty: boolean) => void;
  onLocalRestore: (context: InvestigationContext, projectId: string) => void;
  canStart: boolean;
}) {
  const [draft, setDraft] = useState<Investigation | null>(null),
    [handoff, setHandoff] = useState<Investigation | null>(null),
    [list, setList] = useState<Investigation[]>([]),
    [note, setNote] = useState(""),
    [state, setState] = useState("尚未开始调查"),
    [error, setError] = useState(""),
    [dirty, setDirty] = useState(false),
    [conflict, setConflict] = useState<Investigation | null>(null),
    [localRecovered, setLocalRecovered] = useState(false),
    [patchRevision, setPatchRevision] = useState(0);
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
  const restoreGeneration = useRef(0);
  const resolution = useInvestigationResolution(
    api,
    userId,
    handoff || draft,
    !!handoff,
    setError,
  );
  const cache = () =>
    saveProductionResume(userId, projectRef.current, {
      id: current.current?.id,
      pending: pending.current,
    });
  const install = useCallback((d: Investigation) => {
    current.current = d;
    setDraft(d);
    setNote(d.note);
    setState(`已保存 ${localTime(d.updated_at)} · 修订 ${d.version}`);
  }, []);
  const [resolveTarget, setResolveTarget] = useState<{
    record: Investigation;
    handoff: boolean;
    nonce: number;
  } | null>(null);
  const resolve = (record: Investigation, handoff = false) => {
    resolution.invalidate();
    setResolveTarget((old) => ({
      record,
      handoff,
      nonce: (old?.nonce || 0) + 1,
    }));
  };
  useEffect(() => {
    if (resolveTarget)
      void resolution.resolve(resolveTarget.record, resolveTarget.handoff);
  }, [resolveTarget]);
  useEffect(() => {
    onDirty?.(dirty);
    return () => onDirty?.(false);
  }, [dirty, onDirty]);
  useEffect(() => {
    const c = new AbortController();
    active.current.abort();
    active.current = c;
    const token = ++epoch.current;
    const restoreToken = ++restoreGeneration.current;
    setResolveTarget(null);
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
      resolution.invalidate();
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
      const cached = readProductionResume(userId, projectId);
      const restoreLocal = () => {
        if (!cached?.pending || !Object.keys(cached.pending).length) return;
        pending.current = cached.pending;
        setNote(cached.pending.note ?? "");
        setDirty(true);
        setLocalRecovered(true);
        pause.current = true;
        setState("本机未保存修改，请核对后提交");
        if (cached.pending.context)
          onLocalRestore(cached.pending.context, projectId);
      };
      if (!cached?.id && cached?.pending?.context && !handoffRef.current) {
        api
          .productionStatus(projectId, c.signal)
          .then(() => {
            if (!c.signal.aborted && epoch.current === token) restoreLocal();
          })
          .catch((e) => {
            if (!c.signal.aborted) setError(errorText(e));
          });
      }
      if (cached?.id && !handoffRef.current) {
        api
          .investigation(projectId, cached.id, c.signal)
          .then((d) => {
            if (
              c.signal.aborted ||
              epoch.current !== token ||
              restoreToken !== restoreGeneration.current
            )
              return;
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
        resolve(d);
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
    pending.current = {
      ...(!current.current ? { context: contextRef.current } : {}),
      ...pending.current,
      ...value,
    };
    setDirty(true);
    setPatchRevision((n) => n + 1);
    setState("未保存修改");
    cache();
  };
  function changeContext(next: InvestigationContext) {
    if (!current.current || handoffRef.current || readOnly || pause.current)
      return;
    if (
      current.current.primary &&
      !matchesContext(next, current.current.primary.descriptor)
    ) {
      setState(
        "当前浏览条件与主要事件不一致；原调查范围已保留，可返回原调查或新建范围调查",
      );
      return;
    }
    patch({ context: next });
  }
  function updateView(
    fields: Partial<
      Pick<
        InvestigationContext,
        | "view"
        | "history_sn"
        | "history_range"
        | "evidence_range"
        | "candidate_csn"
        | "recent_range"
      >
    >,
  ) {
    const base = pending.current.context || current.current?.context;
    if (base && !handoffRef.current) patch({ context: { ...base, ...fields } });
  }
  useEffect(() => {
    if (!dirty || pause.current || readOnly || handoff) return;
    const timer = setTimeout(() => void flush(), 350);
    return () => clearTimeout(timer);
  }, [dirty, note, patchRevision, handoff, readOnly]);
  async function start() {
    if (readOnly || !canStart) return;
    if (current.current) return current.current;
    pending.current = { ...pending.current, context: contextRef.current };
    setDirty(true);
    return flush(true);
  }
  async function choose(which: "primary" | "comparison", event: ViewedEvent) {
    if (readOnly || handoffRef.current) return;
    if (which === "comparison" && !current.current?.primary) return;
    resolution.invalidate();
    const selection = { snapshot_id: event.snapshot_id, offset: event.offset };
    if (which === "primary") {
      delete pending.current.comparison;
      delete pending.current.logs;
    }
    patch({ [which]: selection });
    const d = await flush(true);
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
    const generation = ++restoreGeneration.current;
    resolution.invalidate();
    setResolveTarget(null);
    const signal = active.current.signal;
    try {
      const d = isHandoff
        ? await api.productionHandoff(id, signal)
        : await api.investigation(projectRef.current, id, signal);
      if (signal.aborted || generation !== restoreGeneration.current) return;
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
      resolution.invalidate();
      setHandoff(h);
      handoffRef.current = h;
      setState("固定交接版本已生成");
      resolve(h, true);
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
    canStart,
    browsingOtherScope:
      !!current.current &&
      canStart &&
      JSON.stringify(queryScope(context)) !==
        JSON.stringify(queryScope(current.current.context)),
    applyBrowsingScope: () => changeContext(contextRef.current),
    changeContext,
    updateView,
    draft,
    handoff,
    resolved: resolution.resolved,
    list,
    note,
    state,
    error,
    dirty,
    conflict,
    localRecovered,
    raw: resolution.raw,
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
      resolution.invalidate();
      patch({ comparison: null });
      const d = await flush(true);
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
      resolution.invalidate();
      pending.current = { context: contextRef.current, note: "" };
      setNote("");
      await flush(true);
    },
    detachHandoff: () => {
      setHandoff(null);
      handoffRef.current = null;
      resolution.invalidate();
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
