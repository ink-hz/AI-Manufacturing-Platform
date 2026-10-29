import { useEffect, useRef, useState } from "react";
import type { ObjectDetail, WorkflowTarget } from "./types";
import type { WorkflowApi } from "./api";
import { label } from "./labels";
export function UnitPassport({
  api,
  data,
  onOpen,
}: {
  api?: WorkflowApi;
  data: ObjectDetail;
  onOpen(t: WorkflowTarget): void;
}) {
  const [records, setRecords] = useState<ObjectDetail[]>([]),
    [coverage, setCoverage] = useState({ test_run: 0, calibration: 0 }),
    [totals, setTotals] = useState({ test_run: 0, calibration: 0 }),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(""),
    [page, setPage] = useState(0),
    [retry, setRetry] = useState(0);
  const generation = useRef(0);
  useEffect(() => {
    setRecords([]);
    setCoverage({ test_run: 0, calibration: 0 });
    setTotals({ test_run: 0, calibration: 0 });
    setPage(0);
  }, [data.summary.id, data.summary.project_id]);
  useEffect(() => {
    if (!api || data.value.kind !== "unit") return;
    const c = new AbortController(),
      current = ++generation.current;
    setLoading(true);
    setError("");
    void (async () => {
      try {
        for (const kind of ["test_run", "calibration"] as const) {
          const results = await api.objects(
            data.summary.project_id,
            kind,
            25,
            page * 25,
            c.signal,
          );
          const selected: ObjectDetail[] = [];
          for (const row of results.items) {
            const d = await api.object(
              data.summary.project_id,
              kind,
              row.id,
              c.signal,
            );
            if ("unit_id" in d.value && d.value.unit_id === data.summary.id)
              selected.push(d);
          }
          if (c.signal.aborted || generation.current !== current) return;
          setRecords((old) => [
            ...old.filter(
              (d) => !selected.some((x) => x.summary.id === d.summary.id),
            ),
            ...selected,
          ]);
          setCoverage((old) => ({
            ...old,
            [kind]: Math.min(page * 25 + results.items.length, results.total),
          }));
          setTotals((old) => ({ ...old, [kind]: results.total }));
        }
      } catch (e) {
        if (!c.signal.aborted) setError(String(e));
      } finally {
        if (!c.signal.aborted) setLoading(false);
      }
    })();
    return () => {
      generation.current++;
      c.abort();
    };
  }, [api, data.summary.project_id, data.summary.id, page, retry]);
  if (data.value.kind !== "unit") return null;
  const v = data.value;
  return (
    <section aria-label="单台履历">
      <h4>单台履历 · {v.sn}</h4>
      <h5>客户序列号对应</h5>
      {v.aliases?.length ? (
        v.aliases.map((a) => (
          <p key={a.id}>
            {a.customer_id} · {a.customer_serial} · {a.evidence} · {a.actor_id}{" "}
            · {a.recorded_at}
          </p>
        ))
      ) : (
        <p>尚无客户序列号对应记录</p>
      )}
      <h5>部件安装与拆除历史</h5>
      {v.components?.length ? (
        v.components.map((c) => (
          <section key={c.id}>
            <button
              onClick={() =>
                onOpen({
                  projectId: data.summary.project_id,
                  kind: "component_link",
                  id: c.id,
                })
              }
            >
              {c.material_id} · {c.component_serial} · {label(c.state)}
            </button>
            <p>
              {label(c.origin)} · {c.evidence} · {c.actor_id} · {c.recorded_at}
            </p>
            {c.removal && (
              <p>
                拆除 {c.removal.evidence} · {c.removal.actor_id} ·{" "}
                {c.removal.recorded_at}
              </p>
            )}
          </section>
        ))
      ) : (
        <p>尚无部件登记</p>
      )}
      <h5>实验室运行与标定</h5>
      {!api ? (
        <p>请在记录详情中读取实验室关联履历。</p>
      ) : (
        <>
          <p>
            已核对本项目运行 {coverage.test_run}/{totals.test_run}，标定{" "}
            {coverage.calibration}/{totals.calibration}；仅展示明确关联此 SN
            的记录。
          </p>
          {records.map((r) => (
            <p key={r.summary.id}>
              <button
                onClick={() =>
                  onOpen({
                    projectId: data.summary.project_id,
                    kind: r.summary.kind,
                    id: r.summary.id,
                  })
                }
              >
                {r.summary.title}
              </button>{" "}
              · {label(r.summary.state)}
            </p>
          ))}
          {loading && <p role="status">正在核对单台关联记录…</p>}
          {error && (
            <p role="alert">
              {error}
              <button onClick={() => setRetry((n) => n + 1)}>
                重试读取履历
              </button>
            </p>
          )}
          {!loading &&
            (coverage.test_run < totals.test_run ||
              coverage.calibration < totals.calibration) && (
              <button onClick={() => setPage((n) => n + 1)}>
                继续核对实验室履历
              </button>
            )}
          {!loading && !records.length && (
            <p>已核对范围暂无此 SN 的实验室记录；未读范围不作推断。</p>
          )}
        </>
      )}
    </section>
  );
}
