import {label} from "./labels";
import { ActionForms } from "./ActionForms";
import { TraceWorkspace } from "./TraceWorkspace";
import { DeliveryWorkspace } from "./DeliveryWorkspace";
import { QualityWorkspace } from "./QualityWorkspace";
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
  MutationAcknowledgement,
  ObjectDetail,
} from "./types";
import { WorkflowHome } from "./WorkflowHome";
import { WorkflowProjects, ProjectForm, Members } from "./WorkflowProjects";
import { OrdersWorkspace } from "./OrdersWorkspace";
import { ExchangeWorkspace } from "./ExchangeWorkspace";
import { SupplyWorkspace } from "./SupplyWorkspace";
import { ExecutionWorkspace } from "./ExecutionWorkspace";
import { WorkflowDetail } from "./WorkflowDetail";
import { OrdersForms } from "./forms/OrdersForms";
import { GlobalLedger } from "./GlobalLedger";
import { GlobalTasks } from "./GlobalTasks";
import { initialLedgerContexts, isBusinessModule, type TaskContext } from "./navigationContext";
import "./workflow.css";
export function WorkflowApp({
  options,
}: {
  options: MountOptions;
}) {
  const b = options.bootstrap!;
  const [ledgers, setLedgers] = useState(initialLedgerContexts);
  const [taskContext, setTaskContext] = useState<TaskContext>({projectId:"",offset:0});
  const [denied, setDenied] = useState(false),
    [projects, setProjects] = useState<ProjectDetail[]>([]),
    [dashboard, setDashboard] = useState<Dashboard | null>(null),
    [project, setProject] = useState<ProjectDetail | null>(null),
    [view, setView] = useState<ConsoleView>("home"),
    [creating, setCreating] = useState(false),
    [workspace, setWorkspace] = useState<"orders" | "engineering" | "supply" | "execution" | "quality" | "delivery" | "trace" | "exchange" | "members">(
      "orders",
    ),
    [target, setTarget] = useState<WorkflowTarget | null>(null),
    [detail, setDetail] = useState<ObjectDetail | null>(null),
    [resolve, setResolve] = useState(false),
    [currentTask,setCurrentTask]=useState<ObjectDetail|null>(null),
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
  const openingRead = useRef<AbortController | null>(null);
  const [opening, setOpening] = useState<{ target: WorkflowTarget; error: string } | null>(null);
  const cancelOpening = useCallback(() => {
    openingRead.current?.abort();
    openingRead.current = null;
    setOpening(null);
  }, []);
  const projectVersions = useRef(new Map<string, number>());
  callbacks.current = options;
  const apiRef = useRef<ReturnType<typeof createWorkflowApi> | null>(null);
  const deny = useCallback(() => {
    if (!alive.current) return;
    alive.current = false;
    apiRef.current?.dispose();
    cancelOpening();
    setDenied(true);
    setDashboard(null);
    setDetail(null);
    setCurrentTask(null);
    projectVersions.current.clear();
    scroll.current=[];
    setError("");
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
  apiRef.current = api;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      openingRead.current?.abort();
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
        if (accountAction === "logout") {
          await callbacks.current.onLogout?.();
          if (!alive.current) return;
          api.dispose();
          alive.current = false;
          setDenied(true); setProject(null); setProjects([]); setDashboard(null); setDetail(null); setTarget(null); setCurrentTask(null); projectVersions.current.clear(); scroll.current=[];
        }
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
    const controller = new AbortController();
    const current = () => !controller.signal.aborted && alive.current;
    const failed = (e: unknown) => { if (current()) setError(String(e)); };
    setError("");
    // Metadata and dashboard are independent producers, each commits as it arrives.
    api.dashboard(controller.signal).then(d => { if (current()) setDashboard(d); }).catch(failed);
    api.projects(controller.signal)
      .then((p) => {
        if (current()) {
          // A response older than an acknowledged mutation cannot lower freshness.
          const isCurrent = (value: ProjectDetail) =>
            value.version >= (projectVersions.current.get(value.id) || 0);
          setProjects((old) =>
            p.items.flatMap((value) =>
              isCurrent(value) ? [value] : old.filter((x) => x.id === value.id),
            ),
          );
          setProject((old) => {
            if (!old) return old;
            const incoming = p.items.find((x) => x.id === old.id);
            // Equal-version list summaries omit progress/tasks by contract.
            // A genuinely newer summary invalidates old detail and triggers its read.
            return incoming && isCurrent(incoming) && incoming.version > old.version
              ? incoming
              : old;
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
      .catch(failed);
    return () => controller.abort();
  }, [api, refresh]);
  useEffect(() => {
    if (!project) return;
    const controller = new AbortController();
    api.project(project.id, controller.signal).then(value => {
      if(!controller.signal.aborted && alive.current && value.version >= (projectVersions.current.get(value.id) || 0)) {
        projectVersions.current.set(value.id,value.version);
        setProject(value);
        // Keep the list's version/metadata coherent without treating it as detail.
        setProjects(old => old.map(item => item.id === value.id && item.version <= value.version
          ? {...value, progress:null, tasks:[], tasks_truncated:false}
          : item));
      }
    }).catch(e => { if(!controller.signal.aborted && alive.current) setError(String(e)); });
    return () => controller.abort();
  }, [api, project?.id, project?.version, refresh]);
  const requestLeave = useCallback(
    (action: () => void) => {
      const leave = () => { cancelOpening(); action(); };
      if (Object.values(dirtyKeys).some(Boolean)) setPending((existing) => existing || leave);
      else leave();
    },
    [dirtyKeys, cancelOpening],
  );
  function account(action: "navigate" | "logout") {
    if (accountLock.current || !alive.current || pending) return;
    accountLock.current = true;
    setBusy(true);
    requestLeave(() => setAccountAction(action));
  }
  function open(t: WorkflowTarget) {
    requestLeave(() => {
      const controller = new AbortController();
      openingRead.current = controller;
      const current = () => alive.current && !controller.signal.aborted && openingRead.current === controller;
      const commit = (p: ProjectDetail) => {
        if (!current()) return;
        if (p.version < (projectVersions.current.get(p.id) || 0))
          throw new Error("项目版本已更新，请重试打开记录。");
        projectVersions.current.set(p.id, p.version);
        setProject(old => old?.id === p.id && old.version >= p.version ? old : p);
        setCreating(false);
        setTarget(t);
        setCurrentTask(null);
        setDetail(null);
        setResolve(false);
        setOpening(null);
        openingRead.current = null;
      };
      const cached = projects.find(p => p.id === t.projectId && p.version >= (projectVersions.current.get(p.id) || 0));
      if (cached) commit(cached);
      else {
        setOpening({target:t,error:""});
        api.project(t.projectId, controller.signal).then(commit).catch(e => {
          if (current()) setOpening({target:t,error:String(e)});
        });
      }
    });
  }
  function changed(result: MutationAcknowledgement) {
    const version = Math.max(
      result.project_version,
      result.current_project_version || 0,
      projectVersions.current.get(result.project_id) || 0,
    );
    projectVersions.current.set(result.project_id, version);
    const advance = (value: ProjectDetail) =>
      value.id === result.project_id
        ? { ...value, version: Math.max(value.version, version), ...(version > value.version ? {progress:null, tasks:[], tasks_truncated:false} : {}) }
        : value;
    setProject((old) => (old ? advance(old) : old));
    setProjects((old) => old.map(advance));
    setRefresh((r) => r + 1);
    setDirtyKeys({});
    setCurrentTask(null);
    setEpoch((e) => e + 1);
    if (result.exchange_id) {
      // An intent can reserve an ID before its business object exists.
      setTarget({projectId:result.project_id,kind:"exchange",id:result.exchange_id});
      setDetail(null);
      setResolve(false);
    } else if (
      [
        "rma", "capa",
        "eco",
        "demand",
        "order_line",
        "commitment_change",
        "revision",
        "work_order",
        "plan", "requirement", "commitment", "material_lot", "receipt", "reservation", "exchange", "unit", "interruption",
      ].includes(result.object_type || "") && result.object_id
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
  const readOnly = options.readOnly || !b.can_edit || busy;
  const props = project
    ? { api, project, onChanged: changed, onOpen: open, onDirty, readOnly }
    : null;
  const [workView, setWorkView] = useState<ConsoleView>("home");
  function navigate(next: ConsoleView) {
    if (next === "handbook") {
      if (view === "handbook") return;
      cancelOpening();
      scroll.current = [
        ...(frame.current?.querySelectorAll<HTMLElement>("*") || []),
      ]
        .filter((e) => e.scrollTop || e.scrollLeft)
        .map((element) => ({
          element,
          top: element.scrollTop,
          left: element.scrollLeft,
        }));
      let ancestor: HTMLElement | null = frame.current;
      while (ancestor) {
        if (ancestor.scrollTop || ancestor.scrollLeft) scroll.current.push({element:ancestor,top:ancestor.scrollTop,left:ancestor.scrollLeft});
        ancestor = ancestor.parentElement;
      }
      setWorkView(view);
      setView(next);
      return;
    }
    requestLeave(() => {
      setView(next);
      setCreating(false);
      setTarget(null);
      setCurrentTask(null);
      setResolve(false);
      setProject(null);
      setDetail(null);
      const nextWorkspace = ({orders:"orders", supply:"supply", execution:"execution", quality:"quality", collaboration:"exchange"} as Record<string,string>)[next];
      if (nextWorkspace) setWorkspace(nextWorkspace as typeof workspace);
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
  const activeView = view === "handbook" ? workView : view;
  if (denied || !b.allowed || !b.workflow_access)
    return <p role="alert">无权访问制造工作区，请重新登录或联系管理员。</p>;
  return (
    <div className="mf-root mf-product mf-console-root wf-root" ref={frame}>
      <ConsoleShell
        view={view}
        navigation={[
          ["home", "工作台"],
          ["projects", "制造项目"],
          ["orders", "订单与交付"],
          ["supply", "计划与物料"],
          ["execution", "工单与执行"],
          ["quality", "质量与追溯"],
          ["tasks", "事项"],
          ["collaboration", "系统协同"],
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
        {opening && (opening.error ? <p role="alert">{opening.error}<button onClick={() => open(opening.target)}>重试打开记录</button></p> : <p role="status">正在读取记录所属项目…</p>)}
        <div hidden={view === "handbook"} key={epoch}>
          {activeView === "home" && !project && dashboard && (
            <WorkflowHome data={dashboard} onOpen={open} />
          )}{" "}
          {activeView === "tasks" && !project && <GlobalTasks api={api} context={taskContext} onContext={context=>{cancelOpening();setTaskContext(context);}} projects={projects} refresh={refresh} onRefresh={()=>setRefresh(r=>r+1)} onOpen={open}/> }
          {isBusinessModule(activeView) && !project && <GlobalLedger api={api} module={activeView} context={ledgers[activeView]} onContext={context=>{cancelOpening();setLedgers(old=>({...old,[activeView]:context}));}} projects={projects} refresh={refresh} onRefresh={()=>setRefresh(r=>r+1)} onOpen={open} onProject={(p,trace)=>requestLeave(()=>{setProject(p);setTarget(null);setDetail(null);setCurrentTask(null);if(trace)setWorkspace("trace");})}/>}
          {(activeView === "projects" || project) &&
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
                      setCurrentTask(null);
                      setDetail(null);
                    })
                  }
                >
                  {activeView === "projects" ? "返回项目列表" : activeView === "home" ? "返回工作台" : "返回台账"}
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
                <p>待发 {project.summary.remaining_to_ship} · 待验收 {project.summary.remaining_to_accept} · 已签收 {project.summary.signed}</p>
                {!project.progress&&<p>正在核验当前项目业务条件…</p>}{project.progress && <section aria-label="实际业务进展"><h3>实际业务进展</h3>{project.progress.blockers_truncated&&<p>阻断对象展示有界；未展示的工单条件未逐一核验，请进入工单详情检查。</p>}<details><summary>当前 S1—S9 业务进展</summary><table><thead><tr><th>阶段</th><th>实际状态</th><th>依据</th></tr></thead><tbody>{project.progress.stages.map(s=><tr key={s.stage}><td>{s.stage}</td><td>{label(s.status)}</td><td>{s.reason}</td></tr>)}</tbody></table></details>{(["fulfillment","quality","cost"] as const).map(k=><details key={k}><summary>{({fulfillment:"履约",quality:"质量",cost:"成本"})[k]} · {label(project.progress![k].status)} · 历史关闭 {project.progress![k].recorded_count} 次</summary>{project.progress![k].blocking_reasons.map(r=><p key={r}>{r}</p>)}</details>)}</section>}
                <ActionForms {...props}/>
                {currentTask&&!target&&<p>当前事项：{currentTask.summary.title} · <button onClick={()=>open({projectId:project.id,kind:currentTask.summary.kind,id:currentTask.summary.id})}>查看事项依据</button></p>}
                <div className="mf-tabs">
                  {(
                    [
                      ["orders", "订单与需求"],
                      ["engineering", "工程与工单"],
                      ["supply", "供应与物料"],
                      ["execution", "生产执行"],
                      ["quality", "质量与放行"],
                      ["delivery", "交付与关闭"],
                      ["trace", "追溯与反馈"],
                      ["exchange", "同步与回执"],
                      ...(b.configuration_admin
                        ? [["members", "成员授权"]]
                        : []),
                    ] as const
                  ).filter(([key]) => {
                    const active = view === "handbook" ? workView : view;
                    if(active === "projects") return true;
                    return ({orders:["orders","delivery"],supply:["supply"],execution:["engineering","execution"],quality:["quality","trace"],collaboration:["exchange"]} as Record<string,string[]>)[active]?.includes(key);
                  }).map(([key, title]) => (
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
                          setDetail(null);
                          setCurrentTask(null);
                          setResolve(false);
                          if (activeView !== "projects") setProject(null);
                        })
                      }
                    >
                      返回业务列表
                    </button>
                    <WorkflowDetail
                      key={target.projectId+target.kind+target.id}
                      api={api}
                      target={target}
                      onOpen={open}
                      onLoaded={setDetail}
                    />
                    {detail&&<ActionForms {...props} detail={detail} onChoose={action=>requestLeave(()=>{
                      setCurrentTask(detail);setTarget(null);setResolve(false);setEpoch(e=>e+1);
                      const prefix=action.split(".")[0];
                      setWorkspace(["shipment","delivery","ownership","stock_basis","closure"].includes(prefix)?"delivery":["supply","material","reservation","plan"].includes(prefix)?"supply":["production","execution","unit","first_article"].includes(prefix)?"execution":["test","nonconformance","rework","release"].includes(prefix)?"quality":["freeze","rma","capa"].includes(prefix)?"trace":["engineering","work_order","readiness","eco"].includes(prefix)?"engineering":["exchange","source"].includes(prefix)?"exchange":"orders");
                    })}/>}
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
                ) : workspace === "trace" ? (
                  <TraceWorkspace key={props.project.id} {...props} requestLeave={requestLeave} />
                ) : workspace === "delivery" ? (
                  <DeliveryWorkspace {...props} requestLeave={requestLeave} />
                ) : workspace === "quality" ? (
                  <QualityWorkspace {...props} requestLeave={requestLeave} />
                ) : workspace === "execution" ? (
                  <ExecutionWorkspace {...props} requestLeave={requestLeave} />
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
                    setCurrentTask(null);
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
                callbacks.current.onDirtyChange?.(false);
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
