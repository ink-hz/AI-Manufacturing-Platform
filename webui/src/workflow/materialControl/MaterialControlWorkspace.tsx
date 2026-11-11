import { MesOrderMaterials } from "./MesOrderMaterials";
import { MaterialFlowPanel } from "./MaterialFlowPanel";
import { MaterialTaskList } from "./MaterialTaskList";
import { MaterialTaskOpen } from "./MaterialTaskOpen";
import { ExpeditePanel } from "./ExpeditePanel";
import { useEffect, useRef, useState } from "react";
import type { OEMWorkspaceProps } from "../OEMWorkspace";
import {
  initialMaterialViewContext,
  type MaterialProject,
  type MaterialViewContext,
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
  const setOffset = (value: number) => change({ offset: value });
  const setSelected = (value: string | null) => change({ selected: value });
  const setFilter = (value: string) => change({ filter: value });
  const setWorkOrder = (value: string) => change({ workOrder: value });
  const [page, setPage] = useState<MaterialProject | null>(null),
    [error, setError] = useState(""),
    [active, setActive] = useState<"task" | "expedite" | null>(null),
    [loading, setLoading] = useState(false);
  const [discardEpoch, setDiscardEpoch] = useState(0);
  const draft = useRef<Record<string, boolean>>({});
  const resetTask = useRef<() => void>(() => {});
  const resetExpedite = useRef<() => void>(() => {});
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
      setActive(null);
      setDiscardEpoch((value) => value + 1);
      action();
    });
  useEffect(() => {
    let current = true;
    const c = new AbortController();
    setError("");
    setLoading(true);
    p.api
      .materialProject(p.project.id, 50, offset, c.signal)
      .then((v) => {
        if (current) {
          if (
            selection.current &&
            Object.values(draft.current).some(Boolean) &&
            !v.requirements.some((r) => r.id === selection.current)
          ) {
            setError("物料需求已变化，草稿已保留；请放弃草稿后重新选择物料。");
          } else setPage(v);
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
  }, [p.api, p.project.id, p.project.version, offset]);
  const requirement = page?.requirements.find((r) => r.id === selected);
  const quantity = (v: string | undefined, unit: string) =>
    v == null ? "未提供" : `${v} ${unit}`;
  return (
    <section aria-label="料况">
      <h3>料况</h3>
      <MesOrderMaterials p={childProps} leave={leave} discardEpoch={discardEpoch} />
      {error && <p role="alert">料况读取失败：{error}</p>}
      {!page ? (
        <p role="status">正在读取料况…</p>
      ) : (
        <>
          <label>
            筛选本页工单
            <select
              aria-label="筛选本页工单"
              value={workOrder}
              onChange={(e) => setWorkOrder(e.target.value)}
            >
              <option value="">全部工单</option>
              {page.work_orders.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            筛选本页物料
            <input
              aria-label="筛选本页物料"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          </label>
          {!page.requirements.length ? (
            <p>暂无物料需求，请先接收供应计划。</p>
          ) : (
            <div className="wf-table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>物料</th>
                    <th>工单</th>
                    <th>需求</th>
                    <th>本单已预留</th>
                    <th>检验合格</th>
                    <th>待补齐 / 待分配</th>
                    <th>需要时间</th>
                  </tr>
                </thead>
                <tbody>
                  {page.requirements
                    .filter(
                      (r) =>
                        r.material_id
                          .toLowerCase()
                          .includes(filter.toLowerCase()) &&
                        (!workOrder || r.work_order_id === workOrder),
                    )
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
                          </button>
                        </td>
                        <td>
                          {page.work_orders.find(
                            (w) => w.id === r.work_order_id,
                          )?.title || "工单"}
                        </td>
                        <td>{quantity(r.required, r.unit)}</td>
                        <td>{quantity(r.reserved, r.unit)}</td>
                        <td>{quantity(r.qualified, r.unit)}</td>
                        <td>{quantity(r.shortage, r.unit)}</td>
                        <td>
                          {r.need_at
                            ? `${r.need_at}（按工单计划开始时间）`
                            : "未提供"}
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
            {offset + page.requirements.length < page.total && (
              <button onClick={() => leave(() => setOffset(offset + 50))}>
                下一页
              </button>
            )}
          </div>
          {requirement && (
            <section aria-label="物料需求详情">
              <h4>{requirement.material_id}</h4>
              <p>
                已到货 {quantity(requirement.received, requirement.unit)} · 在途{" "}
                {quantity(requirement.in_transit, requirement.unit)} · 拒收{" "}
                {quantity(requirement.rejected, requirement.unit)}
              </p>
              <MaterialFlowPanel p={p} page={page} requirement={requirement} />
              <MaterialTaskOpen
                key={"open-" + requirement.id}
                p={{
                  ...childProps,
                  readOnly:
                    p.readOnly ||
                    loading ||
                    !!error ||
                    (page.project_version != null &&
                      page.project_version < p.project.version),
                }}
                page={page}
                requirement={requirement}
                resetRef={resetTask}
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
                    (page.project_version != null &&
                      page.project_version < p.project.version),
                }}
                page={page}
                requirement={requirement}
                resetRef={resetExpedite}
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
                  来源类型：{page.source_modes?.join("、") || "未提供"}
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
