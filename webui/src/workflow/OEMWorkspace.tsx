import { useEffect, useRef, useState } from "react";
import type {
  ObjectKind,
  ObjectSummary,
  ObjectDetail,
  OEMCommands,
  PublicAssetEntry,
  WorkspaceProps,
} from "./types";
import { ObjectTable } from "./OrdersWorkspace";
import { IntroductionForms } from "./forms/IntroductionForms";
import { AssetForms } from "./forms/AssetForms";
import { LaboratoryForms } from "./forms/LaboratoryForms";
import { CalibrationForms } from "./forms/CalibrationForms";
import { GenealogyForms } from "./forms/GenealogyForms";
import { ArrivalForms } from "./forms/ArrivalForms";
import { AuthorityForms } from "./forms/AuthorityForms";
import { AssistancePanel } from "./AssistancePanel";
import { AssetContentView } from "./details/IntroductionDetails";
import { label } from "./labels";
import { OperationHelp } from "./OperationHelp";
export const domainActions = {
  introduction: [
    "npi.open",
    "npi.review",
    "npi.trial",
    "npi.issue",
    "npi.resolve",
    "npi.approve",
    "asset.publish",
    "asset.apply",
    "asset.verify",
  ],
  laboratory: [
    "test_plan.publish",
    "test_run.start",
    "test_run.finish",
    "calibration.record",
    "calibration.confirm",
    "unit.alias",
    "component.install",
    "component.remove",
  ],
  arrival: ["arrival.record", "arrival.match"],
  authority: ["authority.register", "authority.verify"],
} satisfies Record<string, OEMCommands["action"][]>;
const kinds: Record<keyof typeof domainActions, ObjectKind[]> = {
  introduction: ["npi", "npi_issue", "reusable_asset", "asset_use"],
  laboratory: ["test_plan", "test_run", "calibration", "component_link"],
  arrival: ["arrival"],
  authority: ["authority_rule"],
};
const lookups: Record<keyof typeof domainActions, ObjectKind[]> = {
  introduction: ["revision", "work_order", "test"],
  laboratory: ["revision", "unit", "rework", "material_lot"],
  arrival: ["receipt"],
  authority: [],
};
const title = {
  introduction: "工程导入与资产",
  laboratory: "测试与标定实验室",
  arrival: "到件观察与匹配",
  authority: "系统责任与契约",
};
const guidance = {
  introduction:
    "基于固定修订核对导入证据，明确当前批量资格，采用经验证的资产修订。",
  laboratory:
    "选择实际 SN，登记测试计划、运行、原始证据及独立标定读回。所有设备证据为人工登记或隔离模拟。",
  arrival: "先记录实际看见的包裹，再核对到货凭据；采购和物料身份可暂时未知。",
  authority: "维护责任范围与契约核验。责任登记、契约核验、系统连接分别展示。",
};
export interface OEMWorkspaceProps extends WorkspaceProps {
  requestLeave(action: () => void): void;
  configurationAdmin?: boolean;
  initialAction?: string | null;
  onSelectAction?(action: string | null): void;
  initialObject?: ObjectDetail | null;
}
export function OEMWorkspace(
  p: OEMWorkspaceProps & { domain: keyof typeof domainActions },
) {
  const [items, setItems] = useState<
      Partial<Record<ObjectKind, ObjectSummary[]>>
    >({}),
    [totals, setTotals] = useState<Partial<Record<ObjectKind, number>>>({}),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [moreBusy, setMoreBusy] = useState(false),
    [retry, setRetry] = useState(0),
    [action, setAction] = useState<OEMCommands["action"] | null>(() =>
      domainActions[p.domain].some((a) => a === p.initialAction)
        ? (p.initialAction as OEMCommands["action"])
        : null,
    ),
    [epoch, setEpoch] = useState(0),
    [catalog, setCatalog] = useState<PublicAssetEntry[]>([]),
    [catalogTotal, setCatalogTotal] = useState(0);
  const generation = useRef(0);
  const catalogRequest = useRef<AbortController | null>(null);
  useEffect(() => {
    if (p.onSelectAction)
      setAction(
        domainActions[p.domain].some((a) => a === p.initialAction)
          ? (p.initialAction as OEMCommands["action"])
          : null,
      );
  }, [p.initialAction, p.domain, p.onSelectAction]);
  useEffect(() => {
    const c = new AbortController(),
      current = ++generation.current;
    setLoading(true);
    setMoreBusy(false);
    setError("");
    setItems({});
    setTotals({});
    setCatalog([]);
    setCatalogTotal(0);
    Promise.all(
      [...kinds[p.domain], ...lookups[p.domain]].map(
        async (kind) =>
          [
            kind,
            await p.api.objects(p.project.id, kind, 50, 0, c.signal),
          ] as const,
      ),
    )
      .then((pages) => {
        if (c.signal.aborted || current !== generation.current) return;
        setItems(Object.fromEntries(pages.map(([k, v]) => [k, v.items])));
        setTotals(Object.fromEntries(pages.map(([k, v]) => [k, v.total])));
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(String(e));
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    if (p.domain === "introduction")
      p.api
        .publicAssets(50, 0, c.signal)
        .then((page) => {
          if (!c.signal.aborted) {
            setCatalog(page.items);
            setCatalogTotal(page.total);
          }
        })
        .catch((e) => {
          if (!c.signal.aborted) setError(String(e));
        });
    return () => {
      generation.current++;
      c.abort();
      catalogRequest.current?.abort();
    };
  }, [p.api, p.project.id, p.project.version, p.domain, retry]);
  async function more(kind: ObjectKind) {
    if (moreBusy) return;
    const current = generation.current;
    setMoreBusy(true);
    try {
      const page = await p.api.objects(
        p.project.id,
        kind,
        50,
        (items[kind] || []).length,
      );
      if (current !== generation.current) return;
      setItems((old) => ({
        ...old,
        [kind]: [...(old[kind] || []), ...page.items],
      }));
      setTotals((old) => ({ ...old, [kind]: page.total }));
    } catch (e) {
      if (current === generation.current) setError(String(e));
    } finally {
      if (current === generation.current) setMoreBusy(false);
    }
  }
  const available = domainActions[p.domain].filter((a) =>
    p.project.allowed_actions.includes(a),
  );
  // A record opened directly can be outside the first lookup page. Include its
  // already-authorized summary only in choices, preserving ledger page offsets.
  const formItems = { ...items };
  if (p.initialObject?.summary.project_id === p.project.id) {
    const summary = p.initialObject.summary;
    formItems[summary.kind] = [
      summary,
      ...(items[summary.kind] || []).filter((item) => item.id !== summary.id),
    ];
  }
  const formProps = {
    ...p,
    items: formItems,
    publicAssets: catalog,
    action: action!,
    onChanged: (result: Parameters<WorkspaceProps["onChanged"]>[0]) => {
      setAction(null);
      p.onChanged(result);
    },
  };
  const form = action?.startsWith("npi.") ? (
    <IntroductionForms {...formProps} />
  ) : action?.startsWith("asset.") ? (
    <AssetForms {...formProps} />
  ) : action?.startsWith("test_") ? (
    <LaboratoryForms {...formProps} />
  ) : action?.startsWith("calibration.") ? (
    <CalibrationForms {...formProps} />
  ) : action?.startsWith("component.") || action === "unit.alias" ? (
    <GenealogyForms {...formProps} />
  ) : action?.startsWith("arrival.") ? (
    <ArrivalForms {...formProps} />
  ) : action?.startsWith("authority.") ? (
    <AuthorityForms {...formProps} />
  ) : null;
  return (
    <section className="wf-oem-workspace" aria-label={title[p.domain]}>
      <h3>{title[p.domain]}</h3>
      <OperationHelp><p>{guidance[p.domain]}</p></OperationHelp>
      {error && (
        <p role="alert">
          {error}
          <button onClick={() => setRetry((n) => n + 1)}>重试读取工作区</button>
        </p>
      )}
      {loading && <p role="status">正在读取业务对象…</p>}
      <div className="mf-actions">
        {!p.readOnly &&
          available.map((a) => (
            <button
              key={a}
              onClick={() =>
                p.requestLeave(() => {
                  p.onSelectAction?.(a);
                  setAction(a);
                  setEpoch((n) => n + 1);
                })
              }
            >
              {label(a)}
            </button>
          ))}
      </div>
      {action && (
        <section key={p.project.id + action + epoch}>
          <button
            onClick={() =>
              p.requestLeave(() => {
                p.onSelectAction?.(null);
                setAction(null);
                setEpoch((n) => n + 1);
                setRetry((n) => n + 1);
              })
            }
          >
            放弃草稿并重新读取
          </button>
          {form}
        </section>
      )}
      {lookups[p.domain].map(
        (k) =>
          (items[k] || []).length < (totals[k] || 0) && (
            <button key={k} disabled={moreBusy} onClick={() => void more(k)}>
              读取更多{label(k)}（{(items[k] || []).length}/{totals[k]}）
            </button>
          ),
      )}
      {kinds[p.domain].map((k) => (
        <section key={k}>
          <h4>{label(k)}</h4>
          {items[k]?.length ? (
            <ObjectTable items={items[k]!} onOpen={p.onOpen} />
          ) : (
            !loading && <p>尚无{label(k)}记录</p>
          )}
          {(items[k] || []).length < (totals[k] || 0) && (
            <button disabled={moreBusy} onClick={() => void more(k)}>
              读取更多{label(k)}（{(items[k] || []).length}/{totals[k]}）
            </button>
          )}
        </section>
      ))}
      {p.domain === "introduction" && (
        <section aria-label="公共资产目录">
          <h4>已批准公共资产目录</h4>
          <p>这里只展示单独批准的通用内容，源项目资料保持原访问范围。</p>
          {catalog.map((a) => (
            <details key={a.asset_revision_id}>
              <summary>
                {a.content.title} · 固定修订 {a.revision}
              </summary>
              <AssetContentView value={a.content} />
            </details>
          ))}
          {catalog.length < catalogTotal && (
            <button
              disabled={moreBusy}
              onClick={() => {
                const current = generation.current;
                const c = new AbortController();
                catalogRequest.current = c;
                setMoreBusy(true);
                void p.api
                  .publicAssets(50, catalog.length, c.signal)
                  .then((page) => {
                    if (current === generation.current && !c.signal.aborted) {
                      setCatalog((old) => [...old, ...page.items]);
                      setCatalogTotal(page.total);
                    }
                  })
                  .catch((e) => {
                    if (current === generation.current && !c.signal.aborted)
                      setError(String(e));
                  })
                  .finally(() => {
                    if (current === generation.current && !c.signal.aborted)
                      setMoreBusy(false);
                  });
              }}
            >
              读取更多公共资产（{catalog.length}/{catalogTotal}）
            </button>
          )}
        </section>
      )}
      {(p.domain === "introduction" || p.domain === "laboratory") && (
        <AssistancePanel
          api={p.api}
          projectId={p.project.id}
          version={p.project.version}
          onOpen={p.onOpen}
          initialKind={p.domain === "laboratory" ? "testing" : "introduction"}
        />
      )}
    </section>
  );
}
