import { useEffect, useRef, useState } from "react";
import { WorkflowError } from "../api";
import type { OEMWorkspaceProps } from "../OEMWorkspace";
import type { ObjectSummary } from "../types";
import type { MesOrderMaterialsData } from "./types";
import { useMaterialCommand } from "./useMaterialCommand";

const messages: Record<string, string> = {
  MES_UNAVAILABLE: "MES暂不可用，请稍后重试。",
  MES_ORDER_EMPTY: "未找到工单组件，请核对MES工单号。",
  MES_ORDER_MISMATCH: "工单信息不一致，请核对MES工单号。",
  MES_INVALID_ORDER_MATERIALS: "组件资料不完整，请联系MES管理员核对。",
  MES_COLLECTION_LIMIT: "组件数量超过读取范围，请联系MES管理员。",
  MES_COLLECTION_INCOMPLETE: "组件未完整读取，请稍后重试。",
  MES_SOURCE_CHANGED: "MES来源已变化，请核对来源后更换关联。",
  MES_CONFIGURATION_CHANGED: "MES配置已变化，请重新读取后重试。",
  MES_BINDING_CONFLICT: "关联已变化或工单已被关联，请重新读取核对。",
  MES_REPLACEMENT_REQUIRED: "关联已变化，请重新读取并填写更换原因。",
  VERSION_CONFLICT: "项目资料已变化，请重新读取后重试。",
};
function message(e: unknown) {
  if (e instanceof WorkflowError)
    return (
      messages[e.code] ||
      (e.status === 401 || e.status === 403
        ? "权限已变化，请重新登录或联系项目管理员。"
        : "操作失败，请核对资料后重试。 ")
    );
  return "读取或保存失败，请稍后重试。";
}
export function MesOrderMaterials({
  p,
  leave,
}: {
  p: OEMWorkspaceProps;
  leave(action: () => void): void;
}) {
  const [items, setItems] = useState<ObjectSummary[]>([]),
    [total, setTotal] = useState(0),
    [selected, setSelected] = useState("");
  const [data, setData] = useState<MesOrderMaterialsData | null>(null),
    [shop, setShop] = useState(""),
    [reason, setReason] = useState("");
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(false),
    [revision, setRevision] = useState(0);
  const generation = useRef(0),
    requestEpoch = useRef(0),
    draftVersion = useRef<number | null>(null),
    command = useMaterialCommand(p.api, p.project.id);
  const dirty = !!(shop || reason),
    stale =
      dirty &&
      draftVersion.current !== null &&
      draftVersion.current !== p.project.version;
  function edit(set: (value: string) => void, value: string) {
    if (draftVersion.current === null) draftVersion.current = p.project.version;
    set(value);
  }
  useEffect(() => {
    if (!dirty) draftVersion.current = null;
    p.onDirty("MES工单关联", dirty);
  }, [dirty, p.onDirty]);
  useEffect(() => () => p.onDirty("MES工单关联", false), [p.project.id]);
  useEffect(() => {
    const token = ++generation.current,
      c = new AbortController();
    setItems([]);
    setTotal(0);
    setSelected("");
    setData(null);
    setShop("");
    setReason("");
    setError("");
    setBusy(false);
    setLoading(false);
    if (typeof p.api.objects === "function")
      p.api
        .objects(p.project.id, "work_order", 50, 0, c.signal)
        .then((v) => {
          if (token === generation.current) {
            setItems(v.items);
            setTotal(v.total);
          }
        })
        .catch((e) => {
          if (token === generation.current) setError(message(e));
        });
    return () => {
      generation.current++;
      c.abort();
    };
  }, [p.api, p.project.id]);
  useEffect(() => {
    requestEpoch.current++;
    setBusy(false);
    if (!selected || typeof p.api.mesOrderMaterials !== "function") {
      setLoading(false);
      return;
    }
    let active = true;
    const c = new AbortController();
    setLoading(true);
    setError("");
    p.api
      .mesOrderMaterials(p.project.id, selected, c.signal)
      .then((v) => {
        if (active) {
          setData(v);
          if (!v.can_manage) {
            setShop("");
            setReason("");
          }
          setLoading(false);
        }
      })
      .catch((e) => {
        if (active) {
          if (
            e instanceof WorkflowError &&
            (e.status === 401 || e.status === 403)
          ) {
            setData(null);
            setShop("");
            setReason("");
          }
          setError(message(e));
          setLoading(false);
        }
      });
    return () => {
      active = false;
      requestEpoch.current++;
      c.abort();
    };
  }, [p.api, p.project.id, p.project.version, selected, revision]);
  useEffect(() => {
    if (p.readOnly) {
      requestEpoch.current++;
      setBusy(false);
      setShop("");
      setReason("");
      command.clear();
    }
  }, [p.readOnly]);
  async function more() {
    const token = generation.current,
      epoch = requestEpoch.current;
    setBusy(true);
    try {
      const v = await p.api.objects(
        p.project.id,
        "work_order",
        50,
        items.length,
      );
      if (token === generation.current && epoch === requestEpoch.current) {
        setItems((x) => [...x, ...v.items]);
        setTotal(v.total);
      }
    } catch (e) {
      if (token === generation.current && epoch === requestEpoch.current)
        setError(message(e));
    } finally {
      if (token === generation.current && epoch === requestEpoch.current)
        setBusy(false);
    }
  }
  async function send(refresh: boolean) {
    if (!data || busy || loading || !data.can_manage || p.readOnly || stale)
      return;
    const token = generation.current,
      epoch = requestEpoch.current;
    setBusy(true);
    setError("");
    try {
      const result = await command.execute(
        refresh
          ? {
              action: "mes_order.refresh",
              work_order_id: selected,
              binding_id: data.binding!.id,
            }
          : {
              action: "mes_order.bind",
              work_order_id: selected,
              shop_order: shop.trim(),
              replace_binding_id: data.binding?.id || null,
              reason: data.binding ? reason.trim() : null,
            },
        p.project.version,
      );
      if (
        token === generation.current &&
        epoch === requestEpoch.current &&
        result
      ) {
        setShop("");
        setReason("");
        command.clear();
        p.onChanged(result);
        setRevision((x) => x + 1);
      }
    } catch (e) {
      if (token === generation.current && epoch === requestEpoch.current) {
        if (
          e instanceof WorkflowError &&
          (e.status === 401 || e.status === 403)
        ) {
          setData(null);
          setShop("");
          setReason("");
        }
        setError(message(e));
      }
    } finally {
      if (token === generation.current && epoch === requestEpoch.current)
        setBusy(false);
    }
  }
  function discard() {
    leave(() => {
      setShop("");
      setReason("");
      command.clear();
      setError("");
      const token = generation.current,
        epoch = requestEpoch.current;
      setBusy(true);
      p.api
        .project(p.project.id)
        .then((v) => {
          if (token === generation.current && epoch === requestEpoch.current) {
            p.onChanged({ project_id: v.id, project_version: v.version });
            setRevision((x) => x + 1);
          }
        })
        .catch((e) => {
          if (token === generation.current && epoch === requestEpoch.current)
            setError(message(e));
        })
        .finally(() => {
          if (token === generation.current && epoch === requestEpoch.current)
            setBusy(false);
        });
    });
  }
  function select(value: string) {
    leave(() => {
      setSelected(value);
      setData(null);
      setShop("");
      setReason("");
      setError("");
      command.clear();
    });
  }
  return (
    <section aria-label="MES工单物料">
      <h4>MES工单物料</h4>
      <label>
        平台工单{" "}
        <select
          aria-label="平台工单"
          value={selected}
          onChange={(e) => select(e.target.value)}
        >
          <option value="">请选择工单</option>
          {items.map((w) => (
            <option key={w.id} value={w.id}>
              {w.title}
            </option>
          ))}
        </select>
      </label>
      {items.length < total && (
        <button disabled={busy} onClick={() => void more()}>
          加载更多工单
        </button>
      )}
      {error && <p role="alert">{error}</p>}
      {dirty && (
        <button disabled={busy} onClick={discard}>
          放弃草稿并重新读取
        </button>
      )}
      {stale && (
        <p role="alert">项目资料已变化，草稿已保留；请放弃草稿并重新读取。</p>
      )}
      {loading && <p role="status">正在读取MES工单物料…</p>}
      {selected && data && (
        <>
          {data.binding ? (
            <p>
              MES工单：{data.binding.shop_order} ·{" "}
              {data.binding.environment === "test"
                ? "测试"
                : data.binding.environment === "production"
                  ? "生产"
                  : data.binding.environment}
              环境 · 站点 {data.binding.site_code}
            </p>
          ) : (
            <p>尚未关联MES工单。</p>
          )}
          {data.snapshot && (
            <>
              <p>
                读取时间：{data.snapshot.collected_at} · 完整组件{" "}
                {data.snapshot.total} 行
              </p>
              <p>MES已提料需另核对线边实收。</p>
              <div className="wf-table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>组件行</th>
                      <th>物料</th>
                      <th>需求</th>
                      <th>MES已提料</th>
                      <th>单位</th>
                      <th>仓储位置</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.snapshot.components.map((c) => (
                      <tr key={c.component_key}>
                        <td>{c.component_key}</td>
                        <td>{c.material_id}</td>
                        <td>{c.required_quantity}</td>
                        <td>{c.withdrawn_quantity ?? "未提供"}</td>
                        <td>{c.unit}</td>
                        <td>{c.storage_location ?? "未提供"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          {data.can_manage && !p.readOnly && (
            <>
              <label>
                MES工单号{" "}
                <input
                  aria-label="MES工单号"
                  value={shop}
                  onChange={(e) => edit(setShop, e.target.value)}
                />
              </label>
              {data.binding && (
                <label>
                  更换原因{" "}
                  <input
                    aria-label="更换原因"
                    value={reason}
                    onChange={(e) => edit(setReason, e.target.value)}
                  />
                </label>
              )}
              <button
                disabled={
                  busy ||
                  loading ||
                  stale ||
                  !shop.trim() ||
                  (!!data.binding && !reason.trim())
                }
                onClick={() => void send(false)}
              >
                {data.binding ? "更换关联" : "关联MES工单"}
              </button>
              {data.binding && (
                <button
                  disabled={busy || loading || stale}
                  onClick={() => void send(true)}
                >
                  刷新组件
                </button>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
