import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createApi } from "./api";
import type { Catalog, MountOptions } from "./types";
import { LegacyWorkflow } from "./LegacyWorkflow";
import { HandbookReader } from "./HandbookReader";
import { ProjectHome } from "./projects/ProjectHome";
import {
  ProjectList,
  defaultFilters,
  type ProjectFilters,
} from "./projects/ProjectList";
import { ProjectForm } from "./projects/ProjectForm";
import { ProjectDetail } from "./projects/ProjectDetail";
import { TaskCenter } from "./projects/TaskCenter";
import { Dialog } from "./projects/ui";
import {
  message,
  type Dashboard,
  type ProjectSummary,
  type FlatTask,
  type ProjectDetailData,
} from "./projects/types";
import type { ControlTarget } from "./collaboration/types";
const SystemCollaboration = lazy(() =>
  import("./collaboration/SystemCollaboration").then((m) => ({
    default: m.SystemCollaboration,
  })),
);
type View =
  | "home"
  | "projects"
  | "tasks"
  | "handbook"
  | "legacy"
  | "collaboration";
export function App({ options }: { options: MountOptions }) {
  const callbacks = useRef(options);
  callbacks.current = options;
  const [catalog, setCatalog] = useState<Catalog | null>(null),
    [dashboard, setDashboard] = useState<Dashboard | null>(null),
    [projects, setProjects] = useState<ProjectSummary[]>([]),
    [tasks, setTasks] = useState<FlatTask[]>([]),
    [error, setError] = useState(""),
    [denied, setDenied] = useState(false),
    [refresh, setRefresh] = useState(0);
  const [view, setView] = useState<View>("home"),
    [workView, setWorkView] = useState<View>("home"),
    [selected, setSelected] = useState<{
      id: string;
      stage?: string;
      task?: string;
      control?: ControlTarget;
      initial?: ProjectDetailData;
    } | null>(null),
    [creating, setCreating] = useState(false),
    [filters, setFilters] = useState<ProjectFilters>(defaultFilters),
    [dirtyKeys, setDirtyKeys] = useState<Record<string, boolean>>({}),
    [pending, setPending] = useState<(() => void) | null>(null),
    [epoch, setEpoch] = useState(0),
    [bookTarget, setBookTarget] = useState<{ stage?: string; serial: number }>({
      serial: 0,
    }),
    [legacyVisited, setLegacyVisited] = useState(false);
  const frame = useRef<HTMLDivElement>(null),
    scroll = useRef<{
      nodes: { element: HTMLElement; top: number; left: number }[];
      x: number;
      y: number;
    } | null>(null);
  const deny = useCallback(() => {
    setDenied(true);
    setDashboard(null);
    setProjects([]);
    setTasks([]);
    setCatalog(null);
    setSelected(null);
    setCreating(false);
    setDirtyKeys({});
    callbacks.current.onAuthError?.();
  }, []);
  const api = useMemo(
    () => createApi(options, deny),
    [options.apiBase, options.csrfToken, deny],
  );
  useEffect(() => () => api.dispose(), [api]);
  const onDirty = useCallback(
    (key: string, value: boolean) =>
      setDirtyKeys((old) =>
        !!old[key] === value ? old : { ...old, [key]: value },
      ),
    [],
  );
  const dirty = Object.values(dirtyKeys).some(Boolean);
  useEffect(() => {
    options.onDirtyChange?.(dirty);
    return () => options.onDirtyChange?.(false);
  }, [dirty, options.onDirtyChange]);
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);
  useEffect(() => {
    let active = true;
    setError("");
    Promise.all([
      api.catalog(),
      api.dashboard(),
      api.projects(),
      api.projectTasks(),
    ])
      .then(([c, d, p, t]) => {
        if (active) {
          setCatalog(c);
          setDashboard(d);
          setProjects(p.items);
          setTasks(t.items);
        }
      })
      .catch((e) => {
        if (active) setError(message(e));
      });
    return () => {
      active = false;
    };
  }, [api, refresh]);
  const changed = useCallback(() => setRefresh((n) => n + 1), []);
  const requestLeave = useCallback(
    (action: () => void) => {
      if (Object.values(dirtyKeys).some(Boolean)) setPending(() => action);
      else action();
    },
    [dirtyKeys],
  );
  function go(next: View) {
    if (next === "handbook") {
      openBook();
      return;
    }
    if (next === view && !(next === "projects" && (selected || creating)))
      return;
    if (view === "handbook" && next === workView) {
      returnToWork();
      return;
    }
    requestLeave(() => {
      changed();
      setView(next);
      setWorkView(next);
      if (next === "home" || next === "tasks" || next === "projects") {
        setSelected(null);
        setCreating(false);
      }
    });
  }
  function open(id: string, stage?: string, task?: string) {
    requestLeave(() => {
      setSelected({ id, stage, task });
      setCreating(false);
      setView("projects");
      setWorkView("projects");
    });
  }
  function openControl(id: string, control: ControlTarget) {
    requestLeave(() => {
      setSelected({ id, control });
      setCreating(false);
      setView("projects");
      setWorkView("projects");
    });
  }
  function openBook(stage?: string) {
    scroll.current = { nodes: [], x: window.scrollX, y: window.scrollY };
    let element: HTMLElement | null = frame.current;
    while (element) {
      scroll.current.nodes.push({
        element,
        top: element.scrollTop,
        left: element.scrollLeft,
      });
      element = element.parentElement;
    }
    setBookTarget((t) => ({ stage, serial: t.serial + 1 }));
    setView("handbook");
  }
  function returnToWork() {
    setView(workView);
    requestAnimationFrame(() => {
      for (const item of scroll.current?.nodes || []) {
        item.element.scrollTop = item.top;
        item.element.scrollLeft = item.left;
      }
      if (scroll.current && (scroll.current.x || scroll.current.y))
        window.scrollTo(scroll.current.x, scroll.current.y);
    });
  }
  function legacy() {
    requestLeave(() => {
      setLegacyVisited(true);
      setWorkView("legacy");
      setView("legacy");
    });
  }
  const legacyDirty = useCallback(
    (value: boolean) => onDirty("legacy", value),
    [onDirty],
  );
  const legacyOptions = useMemo(
    () => ({ ...options, onDirtyChange: legacyDirty, onAuthError: deny }),
    [options.apiBase, options.csrfToken, options.readOnly, legacyDirty, deny],
  );
  const readerOptions = useMemo(
    () => ({ ...options, onAuthError: deny }),
    [options.apiBase, options.csrfToken, options.renderMarkdown, deny],
  );
  const readOnly = options.readOnly || !catalog?.can_edit;
  const actualWork = view === "handbook" ? workView : view;
  return (
    <div className="mf-root mf-product" ref={frame}>
      {denied ? (
        <p role="alert">无权访问大制造，请重新登录或联系管理员。</p>
      ) : (
        <>
          <header className="mf-app-header">
            <div>
              <span className="mf-eyebrow">制造协同</span>
              <h1>制造工作台</h1>
              <p className="mf-intro">围绕项目交付，推进阶段与责任事项。</p>
            </div>
            <button
              className="mf-primary"
              disabled={readOnly}
              onClick={() =>
                requestLeave(() => {
                  setCreating(true);
                  setSelected(null);
                  setView("projects");
                  setWorkView("projects");
                })
              }
            >
              新建项目
            </button>
          </header>
          <nav className="mf-main-nav" aria-label="制造工作区">
            {(
              [
                ["home", "工作台"],
                ["projects", "制造项目"],
                ["tasks", "事项"],
                ["collaboration", "系统协同"],
                ["handbook", "制造手册"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                aria-current={view === key ? "page" : undefined}
                onClick={() => go(key)}
              >
                {label}
              </button>
            ))}
          </nav>
          {options.readOnly && <p className="mf-badge">当前为只读模式</p>}
          {error && (
            <p className="mf-error" role="alert">
              {error}。{dashboard ? "保留上次读取内容。" : ""}
              <button onClick={changed}>重试读取</button>
            </p>
          )}
          {!catalog && !error && <p role="status">正在读取工作台…</p>}
          <main hidden={view === "handbook" || view === "legacy"}>
            {catalog && (
              <>
                {actualWork === "home" && dashboard && (
                  <ProjectHome
                    data={dashboard}
                    onControl={openControl}
                    onOpen={open}
                    onFilter={(status) => {
                      setFilters((f) => ({ ...f, status }));
                      go("projects");
                    }}
                    onTasks={() => go("tasks")}
                  />
                )}
                {actualWork === "projects" &&
                  (creating ? (
                    <ProjectForm
                      key={`new-project-${epoch}`}
                      api={api}
                      catalog={catalog}
                      readOnly={readOnly}
                      onDirty={onDirty}
                      onSaved={(d) => {
                        setCreating(false);
                        setSelected({ id: d.project.id });
                        changed();
                      }}
                      onCancel={() => {
                        setCreating(false);
                        onDirty("project-form", false);
                      }}
                    />
                  ) : selected ? (
                    <ProjectDetail
                      key={selected.id}
                      draftEpoch={epoch}
                      api={api}
                      id={selected.id}
                      initial={selected.initial}
                      stageTarget={selected.stage}
                      taskTarget={selected.task}
                      controlTarget={selected.control}
                      catalog={catalog}
                      readOnly={readOnly}
                      onDirty={onDirty}
                      onChanged={changed}
                      onBack={() => requestLeave(() => setSelected(null))}
                      onHandbook={openBook}
                      onLegacy={legacy}
                      requestLeave={requestLeave}
                    />
                  ) : (
                    <ProjectList
                      items={projects}
                      catalog={catalog}
                      filters={filters}
                      onFilters={setFilters}
                      onOpen={open}
                    />
                  ))}
                {actualWork === "collaboration" && (
                  <Suspense fallback={<p role="status">正在读取系统协同…</p>}>
                    <SystemCollaboration
                      api={api}
                      catalog={catalog}
                      readOnly={readOnly}
                      onDirty={onDirty}
                      onChanged={changed}
                      requestLeave={requestLeave}
                      draftEpoch={epoch}
                      onOpen={open}
                      onControl={openControl}
                    />
                  </Suspense>
                )}
                {actualWork === "tasks" && (
                  <TaskCenter
                    items={tasks}
                    catalog={catalog}
                    onOpen={open}
                    onControl={openControl}
                  />
                )}
              </>
            )}
          </main>
          {legacyVisited && (
            <div hidden={view !== "legacy"} key={`legacy-${epoch}`}>
              <div className="mf-section-heading">
                <h2>流程现状参考</h2>
                <button onClick={() => go("home")}>返回工作台</button>
                <button onClick={() => openBook()}>查阅制造手册</button>
              </div>
              <LegacyWorkflow options={legacyOptions} />
            </div>
          )}
          <HandbookReader
            options={readerOptions}
            release={catalog?.release}
            visible={view === "handbook"}
            target={bookTarget}
            onBack={returnToWork}
            onLegacy={legacy}
          />
          {pending && (
            <Dialog onClose={() => setPending(null)}>
              <h2>尚有未保存的工作</h2>
              <p>
                离开会放弃当前草稿。你也可以继续编辑，或查阅制造手册后返回。
              </p>
              <div className="mf-actions">
                <button className="mf-primary" onClick={() => setPending(null)}>
                  继续编辑
                </button>
                <button
                  onClick={() => {
                    const action = pending;
                    setPending(null);
                    setDirtyKeys({});
                    setEpoch((n) => n + 1);
                    action();
                  }}
                >
                  放弃并离开
                </button>
              </div>
            </Dialog>
          )}
        </>
      )}
    </div>
  );
}
