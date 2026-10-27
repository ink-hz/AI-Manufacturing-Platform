import { LineScope } from "./SystemPicker";
import { useEffect, useState } from "react";
import type { Api } from "../api";
import type { DirtyChange } from "../projects/ui";
import type { ControlTarget, PackageAction } from "./types";
import { useCollection, ReadState } from "./ui";
import { PackageEditor } from "./PackageEditor";
import { HandoffEditor } from "./HandoffEditor";
import { ReadinessEditor } from "./ReadinessEditor";
import {
  packageStates,
  handoffStates,
  readinessStates,
  eventLabel,
  reasonLabel,
} from "./labels";
export type ControlTab = "package" | "readiness" | "handoff";
export function ControlsWorkspace({
  api,
  projectId,
  lineId,
  tab,
  target,
  readOnly,
  onDirty,
  onChanged,
  requestLeave,
  draftEpoch,
}: {
  api: Api;
  projectId: string;
  lineId: string;
  tab: ControlTab;
  target?: ControlTarget;
  readOnly: boolean;
  onDirty: DirtyChange;
  onChanged: () => void;
  requestLeave: (f: () => void) => void;
  draftEpoch: number;
}) {
  const c = useCollection(() => api.controls(projectId));
  const [selected, setSelected] = useState<string | null>(
    target?.object_id || null,
  );
  useEffect(() => {
    void c.refresh().catch(() => {});
  }, [api, projectId]);
  useEffect(
    () => setSelected(target?.object_type === tab ? target.object_id : null),
    [tab, target?.object_id],
  );
  async function saved() {
    onChanged();
    await c.refresh();
  }
  const host = {
    readOnly,
    onDirty,
    onSaved: saved,
    onCancel: () => setSelected(null),
    onReload: () =>
      requestLeave(() => {
        setSelected(null);
        void c.refresh().catch(() => {});
      }),
    requestLeave,
  };
  const d = c.data;
  const rows =
    tab === "package"
      ? d?.packages
      : tab === "handoff"
        ? d?.handoffs
        : d?.readiness;
  return (
    <LineScope.Provider value={lineId}>
      <section className="mf-surface mf-controls">
        <ReadState
          error={c.error}
          retry={() => requestLeave(() => void c.refresh().catch(() => {}))}
        />
        {!d ? (
          <p role="status">正在读取项目协同…</p>
        ) : selected ? (
          tab === "package" ? (
            <PackageEditor
              key={`${selected}-${draftEpoch}`}
              {...host}
              api={api}
              projectId={projectId}
              record={d.packages.find(
                (p) =>
                  p.id ===
                  (selected.startsWith("action:")
                    ? selected.split(":")[1]
                    : selected),
              )}
              actionTarget={
                selected.startsWith("action:")
                  ? (selected.split(":")[2] as PackageAction)
                  : undefined
              }
              onAction={(action) =>
                requestLeave(() => setSelected(`action:${selected}:${action}`))
              }
            />
          ) : tab === "handoff" ? (
            <HandoffEditor
              key={`${selected}-${draftEpoch}`}
              {...host}
              api={api}
              projectId={projectId}
              packages={d.packages}
              record={d.handoffs.find((p) => p.id === selected)}
            />
          ) : (
            <ReadinessEditor
              key={`${selected}-${draftEpoch}`}
              {...host}
              api={api}
              projectId={projectId}
              packages={d.packages}
              record={d.readiness.find(
                (p) =>
                  p.id ===
                  (selected.startsWith("replace:")
                    ? selected.slice(8)
                    : selected),
              )}
              replacement={selected.startsWith("replace:")}
              onReplace={() =>
                requestLeave(() => setSelected(`replace:${selected}`))
              }
              targetItem={target?.item_id}
            />
          )
        ) : (
          <>
            <div className="mf-section-heading">
              <div>
                <h3>
                  {tab === "package"
                    ? "工程资料包"
                    : tab === "handoff"
                      ? "独立交接记录"
                      : "生产准备核对"}
                </h3>
                <p className="mf-muted">
                  {tab === "package"
                    ? "以产品、适用范围和固定修订管理生产依据。"
                    : tab === "handoff"
                      ? "每个接收方独立登记，引用已冻结的资料修订。"
                      : "以工单和执行范围固定核对，凭据与关联问题独立处理。"}
                </p>
              </div>
              <button disabled={readOnly} onClick={() => setSelected("new")}>
                {tab === "package"
                  ? "新建资料包"
                  : tab === "handoff"
                    ? "新建交接"
                    : "新建准备核对"}
              </button>
            </div>
            {rows?.map((row) => (
              <article key={row.id} className="mf-control-row">
                <div>
                  <button
                    className="mf-link"
                    onClick={() => setSelected(row.id)}
                  >
                    {"title" in row ? row.title : row.to_party}
                  </button>
                  <p>
                    {"family_id" in row
                      ? `修订 ${row.revision} · ${packageStates[row.status]}`
                      : "code" in row
                        ? `${row.from_party} → ${row.to_party} · 资料修订 ${row.package_revision} · ${handoffStates[row.status]}`
                        : `${row.work_order_ref} / ${row.scope} · ${row.superseded_by ? "已被替代 / 历史" : readinessStates[row.status]}`}
                  </p>
                  <small>负责人 {row.owner || "未分派"}</small>
                </div>
              </article>
            ))}
            {!rows?.length && (
              <div className="mf-empty">
                暂无真实记录。使用上方操作登记本项目的
                {tab === "package"
                  ? "工程资料"
                  : tab === "handoff"
                    ? "交接事实"
                    : "生产准备范围"}
                。
              </div>
            )}
            <details className="mf-control-history">
              <summary>人工登记历史 · 最近 {d.events.length} 条</summary>
              {d.events.map((e) => (
                <p key={e.id}>
                  <time>{e.created_at}</time> · {e.actor} ·{" "}
                  {eventLabel(e.action)}
                  {e.reason && <> · {reasonLabel(e.reason)}</>}
                </p>
              ))}
            </details>
          </>
        )}
      </section>
    </LineScope.Provider>
  );
}
