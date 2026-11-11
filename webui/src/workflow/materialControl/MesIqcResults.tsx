import { useEffect, useState } from "react";
import type { WorkflowApi } from "../api";
import type { MutationAcknowledgement, ProjectDetail } from "../types";
import type {
  FactDetail,
  IntegrationFact,
  SourceKey,
} from "../integrations/types";
import { useMaterialCommand } from "./useMaterialCommand";

const key = (v: SourceKey) =>
  [v.system, v.object_type, v.external_id, v.version].join("\u0000");
export function MesIqcResults({
  api,
  project,
  receiptId,
  unit,
  readOnly,
  onChanged,
}: {
  api: WorkflowApi;
  project: ProjectDetail;
  receiptId: string;
  unit: string;
  readOnly: boolean;
  onChanged(result: MutationAcknowledgement): void;
}) {
  const [links, setLinks] = useState<SourceKey[]>([]),
    [facts, setFacts] = useState<FactDetail[]>([]);
  const [cursor, setCursor] = useState<number | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const command = useMaterialCommand(api, project.id);
  useEffect(() => {
    let active = true;
    const c = new AbortController();
    setLinks([]);
    setFacts([]);
    setError("");
    async function load() {
      let next: number | null = 0;
      const keys: SourceKey[] = [];
      while (next !== null) {
        const page = await api.integrationLinks(
          project.id,
          "receipt",
          receiptId,
          next,
          c.signal,
        );
        keys.push(...page.records.map((x) => x.source_key));
        next = page.continuation;
      }
      if (active) setLinks(keys);
    }
    if (
      typeof api.integrationLinks === "function" &&
      typeof api.systemFacts === "function" &&
      typeof api.systemFact === "function"
    )
      void load().catch((e) => {
        if (active) setError(String(e));
      });
    return () => {
      active = false;
      c.abort();
    };
  }, [api, project.id, project.version, receiptId]);
  async function loadFacts(offset = 0, signal?: AbortSignal) {
    const page = await api.systemFacts(
      project.id,
      "mes",
      { object_type: "iqc", cursor: offset, limit: 50 },
      signal,
    );
    const matches = page.records.filter(
      (fact: IntegrationFact) =>
        fact.project_id === project.id &&
        fact.payload.fact_type === "mes.iqc" &&
        links.some(
          (link) =>
            key(link) ===
            key(
              fact.payload.fact_type === "mes.iqc"
                ? fact.payload.receipt
                : link,
            ),
        ) &&
        fact.payload.accepted.unit === unit &&
        fact.payload.rejected.unit === unit,
    );
    const details = await Promise.all(
      matches.map((f) => api.systemFact(project.id, f.source, signal)),
    );
    return {
      items: details.filter(
        (d) => d.source_accepted === true || d.workflow_projected === true,
      ),
      next: page.continuation,
    };
  }
  useEffect(() => {
    if (!links.length) return;
    let active = true;
    const c = new AbortController();
    loadFacts(0, c.signal)
      .then((v) => {
        if (active) {
          setFacts(v.items);
          setCursor(v.next);
        }
      })
      .catch((e) => {
        if (active) setError(String(e));
      });
    return () => {
      active = false;
      c.abort();
    };
  }, [api, project.id, project.version, receiptId, unit, links]);
  async function more() {
    if (cursor === null) return;
    setBusy(true);
    try {
      const page = await loadFacts(cursor);
      setFacts((v) => [...v, ...page.items]);
      setCursor(page.next);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function admit(source: SourceKey) {
    setBusy(true);
    setError("");
    try {
      const result = await command.execute(
        {
          action: "integration.pull",
          source_key: {
            system: source.system,
            object_type: source.object_type,
            external_id: source.external_id,
            version: source.version,
          },
        },
        project.version,
      );
      if (result) onChanged(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <details>
      <summary>关联已有 MES 检验结果</summary>
      {error && <p role="alert">检验结果读取失败：{error}</p>}
      {!links.length ? (
        <p>该到货没有可关联的来源记录。</p>
      ) : !facts.length ? (
        <p>本页没有匹配的检验结果。</p>
      ) : (
        facts.map((d, i) => {
          const v = d.fact.payload;
          if (v.fact_type !== "mes.iqc") return null;
          return (
            <p key={key(d.fact.source)}>
              结果 {i + 1} · 合格 {String(v.accepted.quantity)}{" "}
              {v.accepted.unit} · 拒收 {String(v.rejected.quantity)}{" "}
              {v.rejected.unit} · {v.evidence}
              {d.workflow_projected
                ? " · 已关联"
                : !readOnly &&
                  project.allowed_actions.includes("integration.pull") && (
                    <button
                      disabled={busy}
                      onClick={() => void admit(d.fact.source)}
                    >
                      关联检验结果
                    </button>
                  )}
            </p>
          );
        })
      )}
      {cursor !== null && (
        <button disabled={busy} onClick={() => void more()}>
          读取更多结果
        </button>
      )}
    </details>
  );
}
