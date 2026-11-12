import { useEffect, useRef, useState, type RefObject } from "react";
import { WorkflowError } from "../api";
import type { OEMWorkspaceProps } from "../OEMWorkspace";
import type { MaterialRequirement } from "./types";
import { useMaterialCommand } from "./useMaterialCommand";

function localDateTime(value: string) {
  const d = new Date(value);
  const offset = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - offset).toISOString().slice(0, 16);
}
type Event = {
  id: string;
  need_at: string | null;
  evidence: string;
  recorded_at: string;
};
export function NeedTimeEditor({
  p,
  requirement,
  active,
  begin,
  resetRef,
  intent,
}: {
  p: OEMWorkspaceProps;
  requirement: MaterialRequirement;
  active: boolean;
  begin(f: () => void): void;
  resetRef: RefObject<() => void>;
  intent?: number;
}) {
  const command = useMaterialCommand(p.api, p.project.id);
  const owner = useRef(0);
  const [version, setVersion] = useState(p.project.version),
    [mode, setMode] = useState<"manual" | "proxy">("proxy"),
    [time, setTime] = useState(""),
    [evidence, setEvidence] = useState(""),
    [events, setEvents] = useState<Event[]>([]),
    [error, setError] = useState(""),
    [conflict, setConflict] = useState(false),
    [busy, setBusy] = useState(false),
    [historyRevision, setHistoryRevision] = useState(0);
  useEffect(() => {
    resetRef.current = () => {
      owner.current++;
      command.clear();
      setMode("proxy");
      setTime("");
      setEvidence("");
      setEvents([]);
      setHistoryRevision((n) => n + 1);
      setError("");
      setConflict(false);
      setBusy(false);
      p.onDirty("material-need-time", false);
    };
    return () => {
      resetRef.current = () => {};
    };
  });
  useEffect(() => {
    if (!active) return;
    const c = new AbortController();
    setError("");
    p.api
      .object(p.project.id, "requirement", requirement.id, c.signal)
      .then((d) => {
        if (!c.signal.aborted && d.value.kind === "requirement")
          setEvents(d.value.need_time_events || []);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(String(e));
      });
    return () => c.abort();
  }, [active, p.api, p.project.id, requirement.id, historyRevision]);
  function initialize() {
    command.clear();
    setVersion(p.project.version);
    setMode(
      requirement.need_at_basis === "manual_requirement" ? "manual" : "proxy",
    );
    setTime(
      requirement.need_at && requirement.need_at_basis === "manual_requirement"
        ? localDateTime(requirement.need_at)
        : "",
    );
    setEvidence("");
    setError("");
    setConflict(false);
  }
  useEffect(() => {
    if (intent && active) initialize();
  }, [intent]);
  const allowed =
    !p.readOnly && p.project.allowed_actions.includes("material.need_time");
  const stale = version !== p.project.version || conflict;
  async function save() {
    if (
      !allowed ||
      stale ||
      busy ||
      !evidence.trim() ||
      (mode === "manual" && !time)
    )
      return;
    let need_at: string | null = null;
    try {
      if (mode === "manual") need_at = new Date(time).toISOString();
    } catch {
      setError("请填写有效的需要时间。");
      return;
    }
    setBusy(true);
    setError("");
    const generation = owner.current;
    try {
      const result = await command.execute(
        {
          action: "material.need_time",
          requirement_id: requirement.id,
          need_at,
          evidence,
        },
        version,
        (result) => {
          if (p.onMaterialChanged) p.onMaterialChanged(result);
          else if (command.isCurrent() && owner.current === generation)
            p.onChanged(result);
        },
      );
      if (!result || !command.isCurrent() || owner.current !== generation)
        return;
      p.onDirty("material-need-time", false);
      setEvidence("");
      setVersion(result.project_version);
      setHistoryRevision((n) => n + 1);
    } catch (e) {
      if (command.isCurrent() && owner.current === generation) {
        setError(
          e instanceof WorkflowError
            ? e.message + (e.reasons.length ? " " + e.reasons.join("；") : "")
            : String(e),
        );
        if (e instanceof WorkflowError && e.status === 409) setConflict(true);
      }
    } finally {
      if (command.isCurrent() && owner.current === generation) setBusy(false);
    }
  }
  const dirty = () => p.onDirty("material-need-time", true);
  return (
    <section>
      <h5>需要时间</h5>
      <p>
        当前依据：
        {requirement.need_at_basis === "manual_requirement"
          ? "需求手动设置"
          : "工单计划开始时间代理"}
        {requirement.need_at ? ` · ${requirement.need_at}` : " · 未提供"}
      </p>
      {allowed && (
        <button onClick={() => begin(initialize)}>调整需要时间</button>
      )}
      {active && (
        <div>
          <label>
            时间依据
            <select
              aria-label="时间依据"
              disabled={!allowed || busy}
              value={mode}
              onChange={(e) => {
                setMode(e.target.value as "manual" | "proxy");
                dirty();
              }}
            >
              <option value="proxy">恢复工单计划开始时间</option>
              <option value="manual">手动设置</option>
            </select>
          </label>
          {mode === "manual" && (
            <label>
              需要时间
              <input
                aria-label="需要时间"
                disabled={!allowed || busy}
                type="datetime-local"
                value={time}
                onChange={(e) => {
                  setTime(e.target.value);
                  dirty();
                }}
              />
            </label>
          )}
          <label>
            调整原因
            <input
              aria-label="调整原因"
              disabled={!allowed || busy}
              value={evidence}
              onChange={(e) => {
                setEvidence(e.target.value);
                dirty();
              }}
            />
          </label>
          {stale && <p>项目已更新，草稿已保留；请放弃草稿后重新打开操作。</p>}
          {error && <p role="alert">{error}</p>}
          <button
            data-save-time
            disabled={
              !allowed ||
              stale ||
              busy ||
              !evidence.trim() ||
              (mode === "manual" && !time)
            }
            onClick={() => void save()}
          >
            保存需要时间
          </button>
          <h6>调整历史</h6>
          {events.length ? (
            events.map((e) => (
              <p key={e.id}>
                {e.recorded_at} · {e.need_at || "恢复工单计划开始时间"} ·{" "}
                {e.evidence}
              </p>
            ))
          ) : (
            <p>暂无调整记录</p>
          )}
        </div>
      )}
    </section>
  );
}
