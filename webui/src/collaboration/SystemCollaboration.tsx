import { SystemForm, AuthorityForm } from "./SystemForms";
import { useEffect, useState } from "react";
import type { Api } from "../api";
import type { Catalog } from "../types";
import { type DirtyChange } from "../projects/ui";
import type { SystemRecord, Authority } from "./types";
import { ReadState, useCollection } from "./ui";
import { methods, objects, usages } from "./labels";
export function SystemCollaboration({
  api,
  catalog,
  readOnly,
  onDirty,
  onChanged,
  requestLeave,
  draftEpoch,
  onOpen,
  onControl,
}: {
  api: Api;
  catalog: Catalog;
  readOnly: boolean;
  onDirty: DirtyChange;
  onChanged: () => void;
  requestLeave: (f: () => void) => void;
  draftEpoch: number;
  onOpen: (id: string) => void;
  onControl?: (id: string, target: import("./types").ControlTarget) => void;
}) {
  const c = useCollection(() => api.collaboration());
  const [tab, setTab] = useState<"systems" | "authorities" | "handoffs">(
      "systems",
    ),
    [selected, setSelected] = useState<SystemRecord | Authority | "new" | null>(
      null,
    );
  useEffect(() => {
    void c.refresh().catch(() => {});
  }, [api]);
  const change = (f: () => void) => requestLeave(f);
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
  return (
    <section className="mf-surface">
      <div className="mf-section-heading">
        <div>
          <h2>系统协同</h2>
          <p className="mf-muted">
            登记业务系统与责任入口；方式为人工记录，不代表已接通或已同步。
          </p>
        </div>
        <button
          onClick={() =>
            change(() => {
              setSelected(null);
              void c.refresh().catch(() => {});
            })
          }
        >
          刷新协同记录
        </button>
      </div>
      <nav className="mf-subnav" aria-label="协同视图">
        {[
          ["systems", "业务系统"],
          ["authorities", "主数据责任"],
          ["handoffs", "跨项目交接"],
        ].map(([id, label]) => (
          <button
            key={id}
            aria-current={tab === id ? "page" : undefined}
            onClick={() =>
              change(() => {
                setTab(id as typeof tab);
                setSelected(null);
              })
            }
          >
            {label}
          </button>
        ))}
      </nav>
      <ReadState error={c.error} retry={host.onReload} />
      {!c.data ? (
        <p role="status">正在读取协同记录…</p>
      ) : selected ? (
        tab === "systems" ? (
          <SystemForm
            key={`${selected === "new" ? "new" : selected.id}-${draftEpoch}`}
            api={api}
            catalog={catalog}
            system={selected === "new" ? undefined : (selected as SystemRecord)}
            {...host}
          />
        ) : (
          <AuthorityForm
            key={`${selected === "new" ? "new" : selected.id}-${draftEpoch}`}
            api={api}
            catalog={catalog}
            systems={c.data.systems}
            authority={selected === "new" ? undefined : (selected as Authority)}
            {...host}
          />
        )
      ) : (
        <>
          {tab === "systems" ? (
            <>
              <div className="mf-section-heading">
                <h3>系统使用现状</h3>
                <button disabled={readOnly} onClick={() => setSelected("new")}>
                  登记系统
                </button>
              </div>
              {c.data.systems.map((s) => (
                <article key={s.id} className="mf-control-row">
                  <div>
                    <button className="mf-link" onClick={() => setSelected(s)}>
                      {s.name}
                    </button>
                    <p>
                      {s.kind} · {usages[s.usage]} · {methods[s.method]} ·{" "}
                      {s.active ? "在用记录" : "已停用"}
                    </p>
                    <small>
                      {s.line_ids
                        .map(
                          (id) =>
                            catalog.lines.find((l) => l.id === id)?.name || id,
                        )
                        .join("、")}{" "}
                      · 业务 {s.business_owner || "待确认"} / IT{" "}
                      {s.it_owner || "待确认"}
                    </small>
                  </div>
                </article>
              ))}
              {!c.data.systems.length && (
                <p className="mf-empty">
                  尚未登记系统。按真实业务线登记当前使用情况。
                </p>
              )}
            </>
          ) : tab === "authorities" ? (
            <>
              <div className="mf-section-heading">
                <h3>主数据责任约定</h3>
                <button
                  disabled={readOnly || !c.data.systems.some((s) => s.active)}
                  onClick={() => setSelected("new")}
                >
                  新增责任约定
                </button>
              </div>
              <p className="mf-muted">
                每条业务线、每类对象只保留一个有效责任入口；先停用旧约定，再新增。
              </p>
              {c.data.authorities.map((a) => (
                <article key={a.id} className="mf-control-row">
                  <button className="mf-link" onClick={() => setSelected(a)}>
                    {objects[a.object_type]} · {a.entry_point}
                  </button>
                  <p>
                    {catalog.lines.find((l) => l.id === a.line_id)?.name ||
                      a.line_id}{" "}
                    ·{" "}
                    {c.data!.systems.find((s) => s.id === a.system_id)?.name ||
                      a.system_id}{" "}
                    · {a.owner} · {a.active ? "有效" : "已停用 / 历史"}
                  </p>
                </article>
              ))}
              {!c.data.authorities.length && (
                <p className="mf-empty">
                  暂无责任约定。选择业务线与系统后登记责任入口。
                </p>
              )}
            </>
          ) : (
            <>
              {c.data.handoffs.map((h) => (
                <article key={h.id} className="mf-control-row">
                  <button
                    className="mf-link"
                    onClick={() =>
                      onControl
                        ? onControl(h.project_id, {
                            object_type: "handoff",
                            object_id: h.id,
                          })
                        : onOpen(h.project_id)
                    }
                  >
                    {h.project_name || "制造项目"} · {h.to_party}
                  </button>
                  <p>固定资料修订 {h.package_revision} · 人工交接记录</p>
                </article>
              ))}
              {!c.data.handoffs.length && (
                <p className="mf-empty">
                  暂无跨项目交接。进入项目的交接记录建立独立接收方。
                </p>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
