import { useState } from "react";
import type { ProvenancedQuantity, QuantityOrigin, QuantityEnvironment, QuantityCoverage } from "./types";

const origins: Record<QuantityOrigin, string> = { native: "原生", manual: "手工", file: "文件", mock: "模拟", unknown: "来源待核对" };
const environments: Record<QuantityEnvironment, string> = { production: "生产", test: "测试", development: "开发", mock: "模拟", unknown: "环境待核对" };
const coverage: Record<QuantityCoverage, string> = { complete: "平台记录完整", partial: "部分", failed: "读取失败", unknown: "待核对" };
const roles = { confirmed: "平台确认记录", observation: "观察记录", unknown: "待核对" } as const;
const time = (v: string | null) => v || "时间待核对";

export function QuantityValue({ quantity, value, unit, title }: { quantity?: ProvenancedQuantity; value: string | null | undefined; unit: string; title: string }) {
  const [open, setOpen] = useState(false);
  const display = quantity === undefined ? value : quantity.value;
  return <div className="wf-quantity" style={{ display: "inline-block" }}>
    {display == null ? "未提供" : `${display} ${quantity?.unit || unit}`}
    {" · "}{quantity ? (quantity.origins.length ? quantity.origins.map(o => origins[o]).join("、") : "来源待核对") : "来源待核对"}
    {quantity && <> · {time(quantity.observed_at || quantity.collected_at)}
      <details onToggle={e => setOpen(e.currentTarget.open)}><summary>{title}数量依据</summary>
        {open && <div>数量性质：{roles[quantity.fact_role]}；环境：{quantity.environments.map(e => environments[e]).join("、") || "环境待核对"}；记录覆盖：{coverage[quantity.coverage]}；发生时间：{time(quantity.observed_at)}；读取时间：{time(quantity.collected_at)}
          {quantity.source_refs.map((s, i) => <div key={`${s.reference}-${i}`}>
            输入：{s.value == null ? "未提供" : `${s.value} ${s.unit || ""}`}；{origins[s.origin]}；{environments[s.environment]}；项目 {s.project_id}；对象 {s.object_kind} / {s.object_id}；版本 {s.version ?? "待核对"}；系统 {s.system || "待核对"}；类型 {s.source_type || "待核对"}；外部编号 {s.external_id || "待核对"}；范围 {s.namespace || "待核对"}；发生 {time(s.occurred_at)}；读取 {time(s.collected_at)}；覆盖 {coverage[s.coverage]}；含义 {s.meaning}；引用 {s.reference}
          </div>)}
          {quantity.input_refs.length > 0 && <div>输入引用：{quantity.input_refs.join("、")}</div>}
        </div>}
      </details></>}
  </div>;
}
