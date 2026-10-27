import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createApi } from "./api";
import { StageWorkspace } from "./components/StageWorkspace";
import type { Catalog, Group, LineOverview, MountOptions } from "./types";
export function LegacyWorkflow({ options }: { options: MountOptions }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null),
    [group, setGroup] = useState("internal"),
    [line, setLine] = useState("cameras"),
    [stage, setStage] = useState<string | null>(null);
  const [overview, setOverview] = useState<LineOverview | null>(null),
    [error, setError] = useState(false),
    [loading, setLoading] = useState(true),
    [denied, setDenied] = useState(false),
    [dirty, setDirty] = useState(false),
    [refresh, setRefresh] = useState(0);
  const frame = useRef<HTMLDivElement>(null),
    scroll = useRef<{ element: HTMLElement; top: number; left: number }[]>([]),
    windowScroll = useRef({ x: 0, y: 0 });
  const deny = useCallback(() => {
    setDenied(true);
    setCatalog(null);
    setOverview(null);
    setStage(null);
    setDirty(false);
    options.onAuthError?.();
  }, [options.onAuthError]);
  const api = useMemo(
    () => createApi(options, deny),
    [options.apiBase, options.csrfToken, deny],
  );
  useEffect(() => () => api.dispose(), [api]);
  useEffect(() => {
    options.onDirtyChange?.(dirty);
    return () => options.onDirtyChange?.(false);
  }, [dirty, options.onDirtyChange]);
  useEffect(() => {
    if (!dirty) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    api
      .catalog()
      .then((value) => {
        if (!active) return;
        setCatalog(value);
        const groups = value.groups
          .filter((g) => g.enabled)
          .sort((a, b) => a.order - b.order);
        const first = groups.find((g) => g.id === "internal") || groups[0];
        if (!first) throw new Error("No enabled groups");
        setGroup(first.id);
        const lines = value.lines
          .filter((l) => l.enabled && l.group_id === first.id)
          .sort((a, b) => a.order - b.order);
        const selected = lines.find((l) => l.id === "cameras") || lines[0];
        setLine(selected?.id || "");
      })
      .catch(() => {
        if (active) setError(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [api, refresh]);
  useEffect(() => {
    if (!catalog || !line || stage) return;
    let active = true;
    setLoading(true);
    setError(false);
    setOverview((current) => (current?.line.id === line ? current : null));
    api
      .line(line)
      .then((value) => {
        if (active) setOverview(value);
      })
      .catch(() => {
        if (active) setError(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [api, catalog, line, stage]);
  useLayoutEffect(() => {
    if (stage) return;
    for (const item of scroll.current) {
      item.element.scrollTop = item.top;
      item.element.scrollLeft = item.left;
    }
    if (windowScroll.current.x || windowScroll.current.y)
      window.scrollTo(windowScroll.current.x, windowScroll.current.y);
  }, [stage, overview]);
  const groups = (catalog?.groups || [])
    .filter((g) => g.enabled)
    .sort((a, b) => a.order - b.order);
  const lines = (catalog?.lines || [])
    .filter((l) => l.enabled && l.group_id === group)
    .sort((a, b) => a.order - b.order);
  function chooseGroup(next: Group) {
    setGroup(next.id);
    const lines = catalog!.lines
      .filter((l) => l.enabled && l.group_id === next.id)
      .sort((a, b) => a.order - b.order);
    setLine(lines[0]?.id || "");
  }
  function enter(id: string) {
    scroll.current = [];
    let element: HTMLElement | null = frame.current;
    while (element) {
      scroll.current.push({
        element,
        top: element.scrollTop,
        left: element.scrollLeft,
      });
      element = element.parentElement;
    }
    windowScroll.current = { x: window.scrollX, y: window.scrollY };
    setStage(id);
  }
  return (
    <div className="mf-root" ref={frame}>
      {denied ? (
        <p role="alert">无权访问大制造，请重新登录或联系管理员。</p>
      ) : stage ? (
        <StageWorkspace
          key={`${line}/${stage}`}
          api={api}
          lineId={line}
          stageId={stage}
          groupName={groups.find((g) => g.id === group)?.name || ""}
          readOnly={options.readOnly || !catalog?.can_edit}
          onDirtyChange={setDirty}
          onBack={() => setStage(null)}
        />
      ) : (
        <>
          <h1>大制造</h1>
          <p className="mf-intro">沿制造流程记录现状，跟进待办。</p>
          {catalog && (
            <>
              <div className="mf-tabs" role="tablist" aria-label="业务归属">
                {groups.map((g) => (
                  <button
                    role="tab"
                    aria-selected={g.id === group}
                    key={g.id}
                    onClick={() => chooseGroup(g)}
                  >
                    {g.name}
                  </button>
                ))}
              </div>
              <div className="mf-lines" aria-label="业务线">
                {lines.length === 1 ? (
                  <p>
                    {lines[0].name}
                    {lines[0].description && `（${lines[0].description}）`}
                  </p>
                ) : (
                  lines.map((l) => (
                    <button
                      aria-pressed={l.id === line}
                      key={l.id}
                      onClick={() => setLine(l.id)}
                    >
                      {l.name}
                    </button>
                  ))
                )}
              </div>
              {lines.find((l) => l.id === line)?.description && (
                <p className="mf-muted">
                  {lines.find((l) => l.id === line)?.description}
                </p>
              )}
            </>
          )}
          {loading && <p role="status">正在读取…</p>}
          {error && (
            <p className="mf-error" role="alert">
              读取失败。{overview ? "保留上次读取的内容。" : ""}{" "}
              <button
                onClick={() =>
                  catalog
                    ? setLine((current) => {
                        setCatalog({ ...catalog });
                        return current;
                      })
                    : setRefresh((x) => x + 1)
                }
              >
                重试读取
              </button>
            </p>
          )}
          {catalog && !line && <p>此业务分组暂无已启用业务线。</p>}
          {overview?.line.id === line && (
            <>
              <ol className="mf-stages">
                {overview.stages.map((s, index) => (
                  <li key={s.id}>
                    <button onClick={() => enter(s.id)}>
                      <span className="mf-stage-number">
                        {String(index + 1).padStart(2, "0")}
                      </span>{" "}
                      <span className="mf-stage-name">{s.name}</span>{" "}
                      <span className="mf-stage-state">
                        {s.recorded ? "已记录" : "未记录"}
                      </span>
                      {s.open_tasks > 0 && (
                        <span className="mf-task-count">
                          {" "}
                          · {s.open_tasks} 项待办
                        </span>
                      )}{" "}
                      <span aria-hidden="true">→</span>
                    </button>
                  </li>
                ))}
              </ol>
              <p className="mf-muted">
                记录状态仅表示已保存现状；待办完成不代表生产完成或流程确认。
              </p>
            </>
          )}
        </>
      )}
    </div>
  );
}
