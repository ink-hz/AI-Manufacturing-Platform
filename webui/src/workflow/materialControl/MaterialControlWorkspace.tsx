import { NeedTimeEditor } from "./NeedTimeEditor";
import { MesOrderMaterials } from "./MesOrderMaterials";
import { MaterialFlowPanel } from "./MaterialFlowPanel";
import { MaterialTaskList } from "./MaterialTaskList";
import { MaterialTaskOpen } from "./MaterialTaskOpen";
import { ExpeditePanel } from "./ExpeditePanel";
import { useEffect, useRef, useState } from "react";
import type { OEMWorkspaceProps } from "../OEMWorkspace";
import {
  initialMaterialViewContext,
  executionScopeLabel,
  type MaterialProject,
  type MaterialViewContext,
  type MaterialProblem,
  type MaterialIssue,
  type MaterialRequirement,
} from "./types";
export function MaterialControlWorkspace(
  p: OEMWorkspaceProps & {
    materialContext?: MaterialViewContext;
    onMaterialContext?(change: Partial<MaterialViewContext>): void;
  },
) {
  const [localContext, setLocalContext] = useState(initialMaterialViewContext);
  const context = p.materialContext || localContext;
  const change = (patch: Partial<MaterialViewContext>) =>
    p.onMaterialContext
      ? p.onMaterialContext(patch)
      : setLocalContext((old) => ({ ...old, ...patch }));
  const { offset, selected, filter, workOrder } = context;
  const problem = context.problem || "attention";
  const [searchDraft, setSearchDraft] = useState(filter);
  const [orders, setOrders] = useState<{id:string;title:string}[]>([]);
  const [orderTotal, setOrderTotal] = useState(0);
  const [orderOffset, setOrderOffset] = useState(0);
  const [orderError, setOrderError] = useState("");
  const [orderRetry, setOrderRetry] = useState(0);
  const orderGeneration = useRef(0);
  const [ordersBusy, setOrdersBusy] = useState(false);
  const orderLoading = useRef(false);
  const [retry, setRetry] = useState(0);
  const scope = JSON.stringify([p.project.id, offset, filter, workOrder, problem]);
  const [pageScope, setPageScope] = useState("");
  const [pageApi, setPageApi] = useState<typeof p.api | null>(null);
  const setOffset = (value: number) => change({ offset: value });
  const setSelected = (value: string | null) => change({ selected: value });

  const [page, setPage] = useState<MaterialProject | null>(null),
    [error, setError] = useState(""),
    [active, setActive] = useState<"task" | "expedite" | "need-time" | null>(null),
    [loading, setLoading] = useState(false);
  const [discardEpoch, setDiscardEpoch] = useState(0);
  const [intent, setIntent] = useState<{ requirementId:string; kind:"iqc"|"trace"; reference:string; token:number } | null>(null);
  const draft = useRef<Record<string, boolean>>({});
  const resetTask = useRef<() => void>(() => {});
  const resetNeedTime = useRef<() => void>(() => {});
  const [timeIntent, setTimeIntent] = useState(0);
  const [expediteIntent, setExpediteIntent] = useState<{requirementId:string;token:number;expediteId?:string} | null>(null);
  const intentSerial = useRef(0);
  const resetExpedite = useRef<() => void>(() => {});
  useEffect(() => {
    setActive(null); setIntent(null); setExpediteIntent(null); setDiscardEpoch(n => n + 1);
    return () => {
      draft.current = {};
      resetTask.current();
      resetExpedite.current();
      resetNeedTime.current();
    };
  }, [p.api, p.project.id]);
  const selection = useRef(selected);
  selection.current = selected;
  const childProps = {
    ...p,
    onDirty: (key: string, dirty: boolean) => {
      draft.current[key] = dirty;
      p.onDirty(key, dirty);
    },
  };
  const leave = (action: () => void) =>
    (p.requestLocalLeave || p.requestLeave)(() => {
      draft.current = {};
      resetTask.current();
      resetExpedite.current();
      resetNeedTime.current();
      setActive(null);
      setIntent(null);
      setExpediteIntent(null);
      setDiscardEpoch((value) => value + 1);
      action();
    });
  useEffect(() => {
    let current = true;
    const c = new AbortController();
    setError("");
    setLoading(true);
    p.api
      .materialProject(p.project.id, 50, offset, c.signal, {search: filter, problem, work_order_id: workOrder})
      .then((v) => {
        if (current) {
          if (
            selection.current &&
            Object.values(draft.current).some(Boolean) &&
            !v.requirements.some((r) => r.id === selection.current)
          ) {
            setError("物料需求已变化，草稿已保留；请放弃草稿后重新选择物料。");
          } else { setPage(v); setPageScope(scope); setPageApi(p.api); }
          setLoading(false);
        }
      })
      .catch((e) => {
        if (current) {
          setError(String(e));
          setLoading(false);
        }
      });
    return () => {
      current = false;
      c.abort();
    };
  }, [p.api, p.project.id, p.project.version, offset, filter, workOrder, problem, retry]);
  useEffect(() => {
    const c = new AbortController(); const token = ++orderGeneration.current; orderLoading.current = false; setOrdersBusy(false); setOrders([]); setOrderTotal(0); setOrderOffset(0); setOrderError("");
    if (typeof p.api.objects === "function") p.api.objects(p.project.id, "work_order", 50, 0, c.signal).then(async v => {
      let items = v.items;
      if (workOrder && !items.some(w => w.id === workOrder) && typeof p.api.object === "function") {
        const exact = await p.api.object(p.project.id, "work_order", workOrder, c.signal);
        items = [exact.summary, ...items];
      }
      if (!c.signal.aborted && token === orderGeneration.current) { setOrders(items); setOrderTotal(v.total); setOrderOffset(v.items.length); }
    }).catch(e => {if (!c.signal.aborted && token === orderGeneration.current) setOrderError(String(e));});
    return () => { orderGeneration.current++; c.abort(); };
  }, [p.api, p.project.id, p.project.version, orderRetry, workOrder]);
  async function moreOrders() {
    if (orderLoading.current) return;
    orderLoading.current = true; setOrdersBusy(true);
    const projectId = p.project.id; const token = orderGeneration.current;
    try { const v = await p.api.objects(projectId, "work_order", 50, orderOffset); if (token === orderGeneration.current) { setOrders(old => [...old, ...v.items.filter(item => !old.some(w => w.id === item.id))]); setOrderOffset(n => n + v.items.length); setOrderTotal(v.total); } } catch (e) { if (token === orderGeneration.current) setOrderError(String(e)); } finally { if (token === orderGeneration.current) { orderLoading.current = false; setOrdersBusy(false); } }
  }
  const shownPage = pageScope === scope && pageApi === p.api ? page : null;
  const issueAction = (r: MaterialRequirement, issue: MaterialIssue) => {
    if (issue.next_action === "arrange_iqc" || issue.next_action === "trace") {
      leave(() => { setSelected(r.id); setActive("task"); setIntent({requirementId:r.id,kind:issue.next_action === "arrange_iqc" ? "iqc" : "trace",reference:issue.object_id,token:++intentSerial.current}); });
    } else if (issue.next_action === "view_task" && issue.task_id) {
      leave(() => p.onOpen({projectId:p.project.id,kind:"material_task",id:issue.task_id!}));
    } else if (issue.next_action === "view_object" || issue.next_action === "check_allocation") {
      leave(() => p.onOpen({projectId:p.project.id,kind:issue.object_kind,id:issue.object_id}));
    } else if (issue.next_action === "expedite") {
      leave(() => {setSelected(r.id);setActive("expedite");setExpediteIntent({requirementId:r.id,token:++intentSerial.current,expediteId:issue.object_id});});
    } else if (issue.next_action === "confirm_time") {
      leave(() => {setSelected(r.id);setActive("need-time");setTimeIntent(n=>n+1);});
    } else { leave(() => setSelected(r.id)); }
  };
  const issueTitle = (title: string) => ({"Material lot is frozen":"批次已冻结", "Material lot has expired":"批次已过期", "Material lot containment pending or frozen":"批次隔离待核对", "Actual return/raw loss conflicts with held authority reservations; supply owner must obtain real source release and replan":"退料或损耗与预留冲突，需核对释放和计划"} as Record<string,string>)[title] || title;
  const issueLabel = (issue: MaterialIssue) => ({view_task:"查看任务",arrange_iqc:"安排检验",trace:"安排查料",expedite:"查看急料",view_object:"查看记录",confirm_time:"核对需要时间",check_allocation:"核对分配"})[issue.next_action];
  const requirement = shownPage?.requirements.find((r) => r.id === selected);
  const quantity = (v: string | undefined, unit: string) =>
    v == null ? "未提供" : `${v} ${unit}`;
  return (
    <section aria-label="料况">
      <h3>料况</h3>
      <MesOrderMaterials p={childProps} leave={leave} discardEpoch={discardEpoch} />
      {error && <p role="alert">料况读取失败：{error}</p>}
      {error && <button onClick={() => setRetry(n => n + 1)}>重试</button>}
      {!shownPage ? (
        <p role="status">正在读取料况…</p>
      ) : (
        <>
          <label>全项目工单
            <select aria-label="全项目工单" value={workOrder} onChange={e => {const value=e.target.value; leave(() => change({workOrder:value, offset:0, selected:null}));}}>
              <option value="">全部工单</option>{orders.map(w => <option key={w.id} value={w.id}>{w.title}</option>)}
            </select>
          </label>
          {orderError && <p role="alert">工单读取失败：{orderError} <button onClick={() => setOrderRetry(n => n + 1)}>重试读取工单</button></p>}
          {orderOffset < orderTotal && <button disabled={ordersBusy} onClick={() => void moreOrders()}>读取更多工单</button>}
          <label>全项目搜索<input aria-label="全项目搜索" maxLength={200} value={searchDraft} onChange={e => setSearchDraft(e.target.value)} onKeyDown={e => {if(e.key === "Enter") leave(() => change({filter:searchDraft, offset:0, selected:null}));}} /></label>
          <button onClick={() => leave(() => change({filter:searchDraft, offset:0, selected:null}))}>搜索</button>
          <label>卡点筛选<select aria-label="卡点筛选" value={problem} onChange={e => {const value=e.target.value as MaterialProblem; leave(() => change({problem:value,offset:0,selected:null}));}}>
            {([['attention','需关注'],['all','全部'],['shortage','缺料'],['urgent','急料'],['pending_iqc','待检验'],['unreceived','待收料'],['verification','待核对']] as const).map(([value,title]) => <option key={value} value={value}>{title}{shownPage.problem_counts?.[value] != null ? ` (${shownPage.problem_counts[value]})` : ''}</option>)}
          </select></label>
          {shownPage.scope_total != null && <p>范围内 {shownPage.scope_total} 项需求，当前筛选 {shownPage.total} 项（卡点可重叠）。</p>}
          <p>数量依据：平台确认计划需求与有效预留；检验合格量单独列示。</p>
          {!shownPage.requirements.length ? (
            <p>{filter || workOrder || problem !== "all" ? "暂无符合当前筛选的物料需求。" : "暂无物料需求，请先接收供应计划。"}</p>
          ) : (
            <div className="wf-table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>物料</th>
                    <th>工单</th>
                    <th>需求</th>
                    <th>本单预留（原始）</th>
                    <th>检验合格</th>
                    <th>待补齐 / 待分配</th>
                    <th>有效预留覆盖</th><th>卡点</th><th>需要时间</th>
                  </tr>
                </thead>
                <tbody>
                  {shownPage.requirements
                    .map((r) => (
                      <tr key={r.id}>
                        <td>
                          <button
                            className="wf-text-link"
                            onClick={() =>
                              leave(() => {
                                setActive(null);
                                setSelected(r.id);
                              })
                            }
                          >
                            {r.material_id}
                          </button> · {executionScopeLabel(r.execution_scope)}
                        </td>
                        <td>
                          {shownPage.work_orders.find(
                            (w) => w.id === r.work_order_id,
                          )?.title || "工单"}
                        </td>
                        <td>{quantity(r.required, r.unit)}</td>
                        <td>{quantity(r.reserved, r.unit)}</td>
                        <td>{quantity(r.qualified, r.unit)}</td>
                        <td>{quantity(r.shortage, r.unit)}</td>
                        <td>{r.confirmed_satisfied == null ? "待核对" : quantity(r.confirmed_satisfied, r.unit)}</td>
                        <td>{r.issues?.map((issue, i) => <div key={`${issue.code}-${issue.object_id}-${i}`}>{issueTitle(issue.title)}{issue.quantity != null && ` · ${issue.quantity} ${issue.unit || r.unit}`} · 当前负责人：{issue.assignee_name || "待分派"}{issue.proposed_assignee_name && ` · 拟负责人：${issue.proposed_assignee_name}`} <button disabled={(loading || !!error || (shownPage.project_version != null && shownPage.project_version < p.project.version)) && !["view_task", "view_object", "check_allocation"].includes(issue.next_action)} onClick={() => issueAction(r, issue)}>{issueLabel(issue)}：{issueTitle(issue.title)}</button></div>)}</td>
                        <td>
                          {r.need_at
                            ? `${r.need_at}（${r.need_at_basis === "manual_requirement" ? "需求手动设置" : "按工单计划开始时间"}）`
                            : "未提供"}
                          {r.timing_risk === "need_time_passed" && " · 需要时间已过，仍有卡点"}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="mf-actions">
            {offset > 0 && (
              <button
                onClick={() => leave(() => setOffset(Math.max(0, offset - 50)))}
              >
                上一页
              </button>
            )}
            {offset + shownPage.requirements.length < shownPage.total && (
              <button onClick={() => leave(() => setOffset(offset + 50))}>
                下一页
              </button>
            )}
          </div>
          {requirement && (
            <section aria-label="物料需求详情">
              <h4>{requirement.material_id} · {executionScopeLabel(requirement.execution_scope)}</h4>
              <p>
                已到货 {quantity(requirement.received, requirement.unit)} · 在途{" "}
                {quantity(requirement.in_transit, requirement.unit)} · 拒收{" "}
                {quantity(requirement.rejected, requirement.unit)}
              </p>
              <MaterialFlowPanel p={p} page={shownPage} requirement={requirement} />
              <NeedTimeEditor key={"time-" + requirement.id} p={{...childProps, readOnly:p.readOnly || loading || !!error || (shownPage.project_version != null && shownPage.project_version < p.project.version)}} requirement={requirement} active={active === "need-time"} resetRef={resetNeedTime} intent={timeIntent} begin={f => leave(() => {setActive("need-time");f();})} />
              <MaterialTaskOpen
                key={"open-" + requirement.id}
                p={{
                  ...childProps,
                  readOnly:
                    p.readOnly ||
                    loading ||
                    !!error ||
                    (shownPage.project_version != null &&
                      shownPage.project_version < p.project.version),
                }}
                page={shownPage}
                requirement={requirement}
                resetRef={resetTask}
                intent={intent}
                active={active === "task"}
                begin={(f) =>
                  leave(() => {
                    setActive("task");
                    f();
                  })
                }
              />
              <ExpeditePanel
                key={"expedite-" + requirement.id}
                p={{
                  ...childProps,
                  readOnly:
                    p.readOnly ||
                    loading ||
                    !!error ||
                    (shownPage.project_version != null &&
                      shownPage.project_version < p.project.version),
                }}
                page={shownPage}
                requirement={requirement}
                resetRef={resetExpedite}
                intent={expediteIntent}
                active={active === "expedite"}
                begin={(f) =>
                  leave(() => {
                    setActive("expedite");
                    f();
                  })
                }
              />
              <details>
                <summary>来源信息</summary>
                <p>
                  来源类型：{shownPage.source_modes?.join("、") || "未提供"}
                  。记录范围以本页物料为准；未接入的系统数据需要另行核对。
                </p>
              </details>
            </section>
          )}
        </>
      )}
      <MaterialTaskList
        p={p}
        offset={context.taskOffset}
        onOffset={(taskOffset) => change({ taskOffset })}
      />
    </section>
  );
}
