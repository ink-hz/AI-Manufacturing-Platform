import type { FulfillmentCheck } from "./fulfillmentTypes";

export function ExpediteFulfillment({ value, fresh = true }: { value: FulfillmentCheck; fresh?: boolean }) {
  const quantity = (v: string | null) => v == null ? "待核对" : `${v} ${value.unit}`;
  return <section aria-label="急料满足核对">
    <h5>当前满足情况</h5>
    <dl className="wf-facts">
      <div><dt>当前需求</dt><dd>{quantity(value.required)}</dd></div>
      <div><dt>相关批次合格量</dt><dd>{quantity(value.qualified)}</dd></div>
      <div><dt>本需求有效预留</dt><dd>{quantity(value.usable_reserved)}</dd></div>
      <div><dt>本需求线边实收</dt><dd>{quantity(value.line_received)}</dd></div>
      <div><dt>仍待实收</dt><dd>{quantity(value.remaining_to_receive)}</dd></div>
    </dl>
    {!fresh ? <p>资料已变化，请重新打开核对。</p>
      : value.can_fulfill ? <p>当前记录满足结束条件。</p> : value.blocking_reasons.map((reason, index) => <p key={index}>{reason}</p>)}
    <p>核对时间：{value.evaluated_at}</p>
  </section>;
}
