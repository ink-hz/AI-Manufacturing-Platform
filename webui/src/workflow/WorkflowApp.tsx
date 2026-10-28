import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MountOptions } from "../types";
import { ConsoleShell, type ConsoleView } from "../console/ConsoleShell";
import { HandbookReader } from "../HandbookReader";
import { Dialog } from "../projects/ui";
import { createWorkflowApi } from "./api";
import type {
  ProjectDetail,
  Dashboard,
  WorkflowTarget,
  CommandResult,
  ObjectDetail,
} from "./types";
import { WorkflowHome } from "./WorkflowHome";
import { WorkflowProjects, ProjectForm, Members } from "./WorkflowProjects";
import { OrdersWorkspace } from "./OrdersWorkspace";
import { ExchangeWorkspace } from "./ExchangeWorkspace";
import { SupplyWorkspace } from "./SupplyWorkspace";
import { WorkflowDetail } from "./WorkflowDetail";
import { OrdersForms } from "./forms/OrdersForms";
import "./workflow.css";
export function WorkflowApp({
  options,
  onLegacy,
}: {
  options: MountOptions;
  onLegacy?: () => void;
}) {
  const b = options.bootstrap!;
  const [denied, setDenied] = useState(false),
    [projects, setProjects] = useState<ProjectDetail[]>([]),
    [dashboard, setDashboard] = useState<Dashboard | null>(null),
    [project, setProject] = useState<ProjectDetail | null>(null),
    [view, setView] = useState<ConsoleView>("home"),
    [creating, setCreating] = useState(false),
    [workspace, setWorkspace] = useState<"orders" | "engineering" | "supply" | "exchange" | "members">(
      "orders",
    ),
    [target, setTarget] = useState<WorkflowTarget | null>(null),
    [detail, setDetail] = useState<ObjectDetail | null>(null),
    [resolve, setResolve] = useState(false),
    [error, setError] = useState(""),
    [refresh, setRefresh] = useState(0),
    [epoch, setEpoch] = useState(0),
    [dirtyKeys, setDirtyKeys] = useState<Record<string, boolean>>({}),
    [pending, setPending] = useState<(() => void) | null>(null),
    [accountAction, setAccountAction] = useState<"navigate" | "logout" | null>(
      null,
    ),
    [busy, setBusy] = useState(false);
  const alive = useRef(true),
    callbacks = useRef(options),
    accountLock = useRef(false),
    frame = useRef<HTMLDivElement>(null),
    scroll = useRef<{ element: HTMLElement; top: number; left: number }[]>([]);
  const projectVersions = useRef(new Map<string, number>());
  callbacks.current = options;
  const deny = useCallback(() => {
    alive.current = false;
    setDenied(true);
    setProject(null);
    setProjects([]);
    setTarget(null);
    setCreating(false);
    setDirtyKeys({});
    setPending(null);
    setAccountAction(null);
    callbacks.current.onAuthError?.();
  }, []);
  const api = useMemo(
    () => createWorkflowApi(options, deny),
    [options.apiBase, options.csrfToken, deny],
  );
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      api.dispose();
    };
  }, [api]);
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
    const f = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", f);
    return () => window.removeEventListener("beforeunload", f);
  }, [dirty]);
  useEffect(() => {
    if (!accountAction || dirty || !alive.current) return;
    setAccountAction(null);
    void (async () => {
      try {
        if (accountAction === "logout") await callbacks.current.onLogout?.();
        else callbacks.current.onNavigatePlatform?.();
      } catch {
        if (alive.current) setError("账户操作失败，请重试。");
      } finally {
        if (alive.current) {
          accountLock.current = false;
          setBusy(false);
        }
      }
    })();
  }, [accountAction, dirty]);
  useEffect(() => {
    let active = true;
    setError("");
    Promise.all([api.projects(), api.dashboard()])
      .then(([p, d]) => {
        if (active && alive.current) {
          // A response older than an acknowledged mutation cannot lower freshness.
          const isCurrent = (value: ProjectDetail) =>
            value.version >= (projectVersions.current.get(value.id) || 0);
          setProjects((old) =>
            p.items.flatMap((value) =>
              isCurrent(value) ? [value] : old.filter((x) => x.id === value.id),
            ),
          );
          setDashboard(d);
          setProject((old) => {
            if (!old) return old;
            const incoming = p.items.find((x) => x.id === old.id);
            return incoming && !isCurrent(incoming) ? old : incoming || null;
          });
          p.items.forEach((value) =>
            projectVersions.current.set(
              value.id,
              Math.max(
                value.version,
                projectVersions.current.get(value.id) || 0,
              ),
            ),
          );
        }
      })
      .catch((e) => {
        if (active && alive.current) setError(String(e));
      });
    return () => {
      active = false;
    };
  }, [api, refresh]);
  const requestLeave = useCallback(
    (action: () => void) => {
      if (Object.values(dirtyKeys).some(Boolean)) setPending(() => action);
      else action();
    },
    [dirtyKeys],
  );
  function account(action: "navigate" | "logout") {
    if (accountLock.current || !alive.current) return;
    accountLock.current = true;
    setBusy(true);
    requestLeave(() => setAccountAction(action));
  }
  function open(t: WorkflowTarget) {
    requestLeave(() => {
      const p = projects.find((p) => p.id === t.projectId);
      if (p) {
        setProject(p);
        setCreating(false);
        setView("projects");
        setTarget(t);
        setDetail(null);
        setResolve(false);
      }
    });
  }
  function changed(result: CommandResult) {
    const version = Math.max(
      result.project_version,
      result.current_project_version || 0,
      projectVersions.current.get(result.project_id) || 0,
    );
    projectVersions.current.set(result.project_id, version);
    const advance = (value: ProjectDetail) =>
      value.id === result.project_id
        ? { ...value, version: Math.max(value.version, version) }
        : value;
    setProject((old) => (old ? advance(old) : old));
    setProjects((old) => old.map(advance));
    setRefresh((r) => r + 1);
    setDirtyKeys({});
    setEpoch((e) => e + 1);
    if (
      [
        "demand",
        "order_line",
        "commitment_change",
        "revision",
        "work_order",
        "plan", "requirement", "commitment", "material_lot", "receipt", "reservation", "exchange",
      ].includes(result.object_type)
    ) {
      setTarget({
        projectId: result.project_id,
        kind: result.object_type as WorkflowTarget["kind"],
        id: result.object_id,
      });
      setDetail(null);
      setResolve(false);
    } else {
      setTarget(null);
    }
  }
  const readOnly = options.readOnly || !b.can_edit;
  const props = project
    ? { api, project, onChanged: changed, onOpen: open, onDirty, readOnly }
    : null;
  const [workView, setWorkView] = useState<ConsoleView>("home");
  function navigate(next: ConsoleView) {
    if (next === "handbook") {
      if (view === "handbook") return;
      scroll.current = [
        ...(frame.current?.querySelectorAll<HTMLElement>("*") || []),
      ]
        .filter((e) => e.scrollTop || e.scrollLeft)
        .map((element) => ({
          element,
          top: element.scrollTop,
          left: element.scrollLeft,
        }));
      setWorkView(view);
      setView(next);
      return;
    }
    if (view === "handbook" && next === workView) {
      back();
      return;
    }
    requestLeave(() => {
      setView(next);
      setCreating(false);
      setTarget(null);
      setResolve(false);
      setProject(null);
    });
  }
  function back() {
    setView(workView);
    requestAnimationFrame(() =>
      scroll.current.forEach(({ element, top, left }) => {
        element.scrollTop = top;
        element.scrollLeft = left;
      }),
    );
  }
  if (denied || !b.allowed || !b.workflow_access)
    return <p role="alert">无权访问制造工作区，请重新登录或联系管理员。</p>;
  return (
    <div className="mf-root mf-product mf-console-root wf-root" ref={frame}>
      <ConsoleShell
        view={view}
        navigation={[
          ["home", "工作台"],
          ["projects", "制造项目"],
          ["handbook", "制造手册"],
        ]}
        creating={creating}
        projectName={project?.name}
        user={
          options.user || {
            displayName: b.user.display_name,
            roleLabel: "项目成员",
          }
        }
        readOnly={readOnly}
        busy={busy}
        canCreate={b.configuration_admin}
        onNavigate={navigate}
        onCreate={() =>
          requestLeave(() => {
            setCreating(true);
            setProject(null);
            setTarget(null);
            setView("projects");
          })
        }
        modeAction={
          onLegacy
            ? { label: "打开旧项目协同", run: () => requestLeave(onLegacy) }
            : undefined
        }
        onNavigatePlatform={
          options.onNavigatePlatform ? () => account("navigate") : undefined
        }
        onLogout={options.onLogout ? () => account("logout") : undefined}
      >
        <p className="mf-badge">
          {b.dataset?.label} ·{" "}
          {b.dataset?.mode === "production"
            ? "生产数据"
            : b.dataset?.mode === "demo"
              ? "隔离演示数据"
              : "隔离测试数据"}{" "}
          · 人工登记保留来源凭据
        </p>
        {readOnly && <p>当前只读</p>}
        {error && (
          <p role="alert">
            {error}
            <button onClick={() => setRefresh((r) => r + 1)}>重试读取</button>
          </p>
        )}
        <div hidden={view === "handbook"} key={epoch}>
          {(view === "handbook" ? workView : view) === "home" && dashboard && (
            <WorkflowHome data={dashboard} onOpen={open} />
          )}{" "}
          {(view === "handbook" ? workView : view) === "projects" &&
            (creating ? (
              <ProjectForm
                readOnly={readOnly}
                api={api}
                onDirty={onDirty}
                onSaved={(p) => {
                  setCreating(false);
                  projectVersions.current.set(p.id, p.version);
                  setProjects((old) => [
                    ...old.filter((value) => value.id !== p.id),
                    p,
                  ]);
                  setProject(p);
                  setRefresh((r) => r + 1);
                }}
              />
            ) : project && props ? (
              <section>
                <button
                  onClick={() =>
                    requestLeave(() => {
                      setProject(null);
                      setTarget(null);
                    })
                  }
                >
                  返回项目列表
                </button>
                <button
                  onClick={() =>
                    requestLeave(() => {
                      setTarget(null);
                      setResolve(false);
                      setRefresh((r) => r + 1);
                      setEpoch((e) => e + 1);
                    })
                  }
                >
                  重新读取项目
                </button>
                <h2>{project.name}</h2>
                <p>
                  {project.line_id} · {project.product} · {project.customer_id}
                </p>
                <p>
                  原始承诺 {project.summary.original_order_quantity}{" "}
                  {project.unit.code} · 当前承诺{" "}
                  {project.summary.current_order_quantity} {project.unit.code} ·
                  已分配 {project.summary.allocated} · 已发运{" "}
                  {project.summary.shipped} · 已验收 {project.summary.accepted}
                </p>
                <div className="mf-tabs">
                  {(
                    [
                      ["orders", "订单与需求"],
                      ["engineering", "工程与工单"],
                      ["supply", "供应与物料"],
                      ["exchange", "同步与回执"],
                      ...(b.configuration_admin
                        ? [["members", "成员授权"]]
                        : []),
                    ] as const
                  ).map(([key, title]) => (
                    <button
                      key={key}
                      onClick={() =>
                        requestLeave(() => {
                          setWorkspace(key as typeof workspace);
                          setTarget(null);
                          setResolve(false);
                          setEpoch((e) => e + 1);
                        })
                      }
                    >
                      {title}
                    </button>
                  ))}
                </div>
                {target ? (
                  <>
                    <button
                      onClick={() =>
                        requestLeave(() => {
                          setTarget(null);
                          setResolve(false);
                        })
                      }
                    >
                      返回业务列表
                    </button>
                    <WorkflowDetail
                      key={target.id}
                      api={api}
                      target={target}
                      onOpen={open}
                      onLoaded={setDetail}
                    />
                    {!readOnly &&
                      detail?.value.kind === "commitment_change" &&
                      detail.summary.next_actions.includes(
                        "order.resolve_change",
                      ) &&
                      project.allowed_actions.includes(
                        "order.resolve_change",
                      ) && (
                        <>
                          <button onClick={() => setResolve(true)}>
                            处理承诺影响
                          </button>
                          {resolve && (
                            <OrdersForms
                              {...props}
                              action="order.resolve_change"
                              change={detail.value}
                              changeId={target.id}
                              demands={[]}
                              orders={[]}
                              workOrders={[]}
                            />
                          )}
                        </>
                      )}
                  </>
                ) : workspace === "members" ? (
                  <Members {...props} findSubjects={options.findSubjects} />
                ) : workspace === "exchange" ? (
                  <ExchangeWorkspace key={props.project.id} {...props} requestLeave={requestLeave} mode={b.dataset?.mode||"production"} />
                ) : workspace === "supply" ? (
                  <SupplyWorkspace
                    {...props}
                    requestLeave={requestLeave}
                    onReload={() => setRefresh((r) => r + 1)}
                  />
                ) : (
                  <OrdersWorkspace
                    {...props}
                    engineering={workspace === "engineering"}
                    requestLeave={requestLeave}
                    onReload={() => setRefresh((r) => r + 1)}
                  />
                )}
              </section>
            ) : (
              <WorkflowProjects
                items={projects}
                onOpen={(p) =>
                  requestLeave(() => {
                    setProject(p);
                    setTarget(null);
                  })
                }
              />
            ))}
        </div>
        <HandbookReader
          options={{ ...options, onAuthError: deny }}
          loadHandbook={api.handbook}
          release={b.release}
          visible={view === "handbook"}
          target={{ serial: 0 }}
          onBack={back}
          onLegacy={() => {}}
        />
        {pending && (
          <Dialog
            onClose={() => {
              setPending(null);
              accountLock.current = false;
              setBusy(false);
            }}
          >
            <h2>尚有未保存的工作</h2>
            <p>离开会放弃当前草稿。</p>
            <button
              onClick={() => {
                setPending(null);
                accountLock.current = false;
                setBusy(false);
              }}
            >
              继续编辑
            </button>
            <button
              onClick={() => {
                const action = pending;
                setPending(null);
                setDirtyKeys({});
                setEpoch((e) => e + 1);
                action();
              }}
            >
              放弃并离开
            </button>
          </Dialog>
        )}
      </ConsoleShell>
    </div>
  );
}
