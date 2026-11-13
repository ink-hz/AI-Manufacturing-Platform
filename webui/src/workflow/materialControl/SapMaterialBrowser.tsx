import { useEffect, useRef, useState } from "react";
import type { WorkflowApi } from "../api";
import type {
  SapStatus,
  SapSource,
  SapObservation,
  SapOrder,
  SapMrp,
  SapComponent,
} from "./sapTypes";
const known = (s?: string) => s || "未知";
const date = (s?: string) =>
  !s || s === "00000000" || s === "0000-00-00" ? "未提供" : s;
function Source({ source, time }: { source: SapSource; time?: string }) {
  return (
    <p>
      {source.environment === "test"
        ? "SAP测试环境"
        : source.environment === "development"
          ? "SAP开发环境"
          : source.environment === "production"
            ? "SAP生产环境"
            : "SAP环境待核对"}{" "}
      · 系统 {source.system_id} · 客户端 {source.client}
      {time && <> · 读取时间 {time}</>}
    </p>
  );
}
function errorText(
  error: { code: string; message: string } | null,
  limit: number,
) {
  if (!error) return null;
  return error.code === "SAP_RESULT_LIMIT_EXCEEDED"
    ? `SAP明细超过当前完整读取上限 ${limit} 条，请联系管理员扩展读取能力；未展示部分结果。`
    : "读取失败，请核对连接和权限后重试。";
}
function ObservationHeader<T>({
  value,
  limit,
}: {
  value: SapObservation<T>;
  limit: number;
}) {
  return (
    <>
      {value.refresh_error && (
        <p role="alert">
          刷新失败：{errorText(value.refresh_error, limit)}
          {value.snapshot && " 保留上次成功结果及原读取时间。"}
        </p>
      )}
      {value.snapshot ? (
        <Source
          source={value.snapshot.source}
          time={value.snapshot.collected_at}
        />
      ) : (
        !value.refresh_error && <p>尚无已保存结果。</p>
      )}
    </>
  );
}
function sameSource(a: SapSource, b: SapSource) {
  return (
    a.namespace === b.namespace &&
    a.environment === b.environment &&
    a.system_id === b.system_id &&
    a.client === b.client
  );
}
export function SapMaterialBrowser({
  api,
  readOnly,
}: {
  api: WorkflowApi;
  readOnly: boolean;
}) {
  const [statusAttempt, setStatusAttempt] = useState(0);
  const [statusError, setStatusError] = useState<WorkflowApi | null>(null);
  const [status, setStatus] = useState<{
    api: WorkflowApi;
    value: SapStatus;
  } | null>(null);
  const [number, setNumber] = useState(""),
    [plant, setPlant] = useState("");
  const [order, setOrder] = useState<{
    api: WorkflowApi;
    key: string;
    value: SapObservation<SapOrder>;
  } | null>(null);
  const [mrp, setMrp] = useState<{
    api: WorkflowApi;
    parent: string;
    key: string;
    value: SapObservation<SapMrp>;
  } | null>(null);
  const [busy, setBusy] = useState(false),
    [mrpBusy, setMrpBusy] = useState(false),
    [failure, setFailure] = useState("");
  const generation = useRef(0),
    mrpGeneration = useRef(0),
    orderAbort = useRef<AbortController | null>(null),
    mrpAbort = useRef<AbortController | null>(null);
  const identity = useRef({
    api,
    key: JSON.stringify([number, plant]),
    readOnly,
  });
  identity.current = { api, key: JSON.stringify([number, plant]), readOnly };
  const key = identity.current.key;
  useEffect(() => {
    const controller = new AbortController();
    let live = true;
    setStatus(null);
    setStatusError(null);
    setOrder(null);
    setMrp(null);
    setFailure("");
    setBusy(false);
    setMrpBusy(false);
    generation.current++;
    mrpGeneration.current++;
    api.sapMaterialStatus(controller.signal).then(
      (value) => {
        if (live) {
          if (value.refresh_error) setStatusError(api);
          else setStatus({ api, value });
        }
      },
      () => {
        if (live) setStatusError(api);
      },
    );
    return () => {
      live = false;
      controller.abort();
      orderAbort.current?.abort();
      mrpAbort.current?.abort();
      generation.current++;
      mrpGeneration.current++;
    };
  }, [api, readOnly, statusAttempt]);
  const current = status?.api === api ? status.value : null;
  const shown = order?.api === api && order.key === key ? order.value : null;
  const nested =
    shown && mrp?.api === api && mrp.parent === key ? mrp.value : null;
  function change(field: "number" | "plant", value: string) {
    generation.current++;
    mrpGeneration.current++;
    orderAbort.current?.abort();
    mrpAbort.current?.abort();
    setBusy(false);
    setMrpBusy(false);
    setOrder(null);
    setMrp(null);
    setFailure("");
    field === "number" ? setNumber(value) : setPlant(value);
  }
  async function queryOrder() {
    if (!current?.source) return;
    const expected = current.source;
    const captured = key;
    const version = ++generation.current;
    mrpGeneration.current++;
    mrpAbort.current?.abort();
    setMrp(null);
    setMrpBusy(false);
    orderAbort.current?.abort();
    const controller = new AbortController();
    orderAbort.current = controller;
    setBusy(true);
    setFailure("");
    const valid = () =>
      generation.current === version &&
      identity.current.api === api &&
      identity.current.key === captured &&
      identity.current.readOnly === readOnly;
    try {
      const value = await api.sapProductionOrder(
        number,
        plant,
        !readOnly && current.can_refresh,
        controller.signal,
      );
      if (!valid()) return;
      const s = value.snapshot;
      if (
        s &&
        (!sameSource(s.source, expected) ||
          s.kind !== "production-order" ||
          s.scope.number !== number.padStart(12, "0") ||
          s.scope.plant !== plant ||
          s.data.number !== number.padStart(12, "0") ||
          s.data.plant !== plant)
      )
        throw Error("identity");
      setOrder({ api, key: captured, value });
    } catch {
      if (valid()) {
        setOrder(null);
        setFailure("工单读取失败或响应来源、范围不匹配，请重新读取。");
      }
    } finally {
      if (valid()) setBusy(false);
    }
  }
  async function queryMrp(component: SapComponent) {
    if (!current?.source || !shown?.snapshot) return;
    const expected = current.source;
    const captured = key;
    const version = ++mrpGeneration.current;
    const scope = JSON.stringify([component.material, component.plant]);
    mrpAbort.current?.abort();
    const controller = new AbortController();
    mrpAbort.current = controller;
    setMrp(null);
    setMrpBusy(true);
    setFailure("");
    const valid = () =>
      mrpGeneration.current === version &&
      identity.current.api === api &&
      identity.current.key === captured &&
      identity.current.readOnly === readOnly;
    try {
      const value = await api.sapStockRequirements(
        component.material,
        component.plant,
        !readOnly && current.can_refresh,
        controller.signal,
      );
      if (!valid()) return;
      const s = value.snapshot;
      if (
        s &&
        (!sameSource(s.source, expected) ||
          s.kind !== "stock-requirements" ||
          s.scope.material !== component.material ||
          s.scope.plant !== component.plant)
      )
        throw Error("identity");
      setMrp({ api, parent: captured, key: scope, value });
    } catch {
      if (valid())
        setFailure("MRP读取失败或响应来源、范围不匹配，请重新读取。");
    } finally {
      if (valid()) setMrpBusy(false);
    }
  }
  return (
    <section aria-label="SAP工单与物料供需">
      <h2>SAP工单与物料供需</h2>
      {failure && <p role="alert">{failure}</p>}
      {!current ? (
        statusError === api ? (
          <div>
            <p role="alert">SAP连接状态读取失败，请检查配置或稍后重试。</p>
            <button onClick={() => setStatusAttempt((v) => v + 1)}>
              重试连接状态
            </button>
          </div>
        ) : (
          <p>正在读取SAP连接状态…</p>
        )
      ) : !current.configured || !current.source ? (
        <p>SAP连接未配置，暂不可查询。</p>
      ) : (
        <>
          <Source source={current.source} />
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void queryOrder();
            }}
          >
            <label>
              工单号
              <input
                value={number}
                onChange={(e) => change("number", e.target.value)}
                required
              />
            </label>
            <label>
              工厂
              <input
                value={plant}
                onChange={(e) => change("plant", e.target.value)}
                required
              />
            </label>
            <button disabled={busy || !number || !plant}>
              {readOnly || !current.can_refresh
                ? "查看已保存结果"
                : shown
                  ? "刷新工单"
                  : "查询工单"}
            </button>
          </form>
        </>
      )}
      {shown && (
        <>
          <ObservationHeader value={shown} limit={500} />
          {shown.snapshot && (
            <>
              <h3>
                工单 {shown.snapshot.data.number} · 工厂{" "}
                {shown.snapshot.data.plant}
              </h3>
              <p>
                {known(shown.snapshot.data.description)} · 物料{" "}
                {known(shown.snapshot.data.material)} · 工单数量{" "}
                {known(shown.snapshot.data.quantity)}{" "}
                {known(shown.snapshot.data.unit)}
              </p>
              <p>
                组件 {shown.snapshot.data.total} 条 · 源总需求与已提量分别呈现
              </p>
              {shown.snapshot.data.components.length === 0 ? (
                <p>无组件明细。</p>
              ) : (
                <div style={{ overflow: "auto", maxHeight: 480 }}>
                  <table>
                    <thead>
                      <tr>
                        {[
                          "物料",
                          "工厂",
                          "源总需求",
                          "已提量",
                          "基本单位",
                          "需求日期",
                          "库存地点",
                          "供需查询",
                        ].map((x) => (
                          <th key={x}>{x}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {shown.snapshot.data.components.map((c, i) => {
                        const reason =
                          !c.material || !c.plant
                            ? "缺少物料或工厂"
                            : c.material.length > 18
                              ? "物料超过MRP查询18字符限制，不能截断查询"
                              : "";
                        return (
                          <tr key={c.component_key || i}>
                            <td>{known(c.material)}</td>
                            <td>{known(c.plant)}</td>
                            <td>{known(c.required_quantity)}</td>
                            <td>{known(c.withdrawn_quantity)}</td>
                            <td>{known(c.unit)}</td>
                            <td>{date(c.required_at)}</td>
                            <td>{known(c.storage_location)}</td>
                            <td>
                              <button
                                type="button"
                                disabled={!!reason || mrpBusy || busy}
                                onClick={() => void queryMrp(c)}
                              >
                                查MRP供需
                              </button>
                              {reason && <span>{reason}</span>}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </>
      )}
      {mrpBusy && <p>正在读取MRP供需…</p>}
      {nested && (
        <>
          <h3>MRP物料供需</h3>
          <ObservationHeader value={nested} limit={50} />
          {nested.snapshot && (
            <>
              <p>
                物料 {nested.snapshot.scope.material} · 工厂{" "}
                {nested.snapshot.scope.plant} · 基本单位{" "}
                {known(nested.snapshot.data.mrp_list.BASE_UOM)}
              </p>
              <p>物料/工厂范围，未分配到本工单，测试数据不合并生产MES。</p>
              {nested.snapshot.data.items.length === 0 ? (
                <p>无供需明细（0条）。</p>
              ) : (
                <div style={{ overflow: "auto" }}>
                  <table>
                    <thead>
                      <tr>
                        {[
                          "可用日期",
                          "MRP要素代码",
                          "收支方向代码",
                          "供需数量（基本单位）",
                          "参考单据",
                          "项目",
                          "库存地点",
                          "录入数量",
                          "录入单位",
                        ].map((x) => (
                          <th key={x}>{x}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {nested.snapshot.data.items.map((row, i) => (
                        <tr key={i}>
                          {[
                            date(row.AVAIL_DATE),
                            known(row.MRP_ELEMENT_IND),
                            known(row.PLUS_MINUS),
                            known(row.REC_REQD_QTY),
                            known(row.MRP_NO12 || row.MRP_NO),
                            known(row.MRP_POS),
                            known(row.STORAGE_LOC),
                            known(row.ENTRY_QNT),
                            known(row.ENTRY_UOM),
                          ].map((v, j) => (
                            <td key={j}>{v}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
