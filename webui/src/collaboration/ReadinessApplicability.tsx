import type { ReadinessItem } from "./types";
import { Field } from "./ui";
export function ReadinessApplicability({
  item,
  replacement,
  update,
}: {
  item: ReadinessItem;
  replacement: boolean;
  update: (patch: Partial<ReadinessItem>) => void;
}) {
  const na = item.status === "na";
  return (
    <>
      <button
        type="button"
        aria-pressed={na}
        onClick={() =>
          update({
            status: na ? "pending" : "na",
            reason: "",
            source_ref: "",
            evidence: "",
            ...(replacement ? { owner: "" } : {}),
          })
        }
      >
        {na ? "撤销本次不适用确认，继续核对" : "本次重新确认不适用"}
      </button>
      {na && (
        <>
          <p className="mf-muted mf-full-width">
            本次明确登记不适用，不沿用旧结论。
            {replacement
              ? "请重新填写负责人、来源、凭据和原因。"
              : "请填写本次判断原因。"}
          </p>
          {replacement && (
            <>
              <Field
                label="不适用来源"
                required
                value={item.source_ref}
                onChange={(v) => update({ source_ref: v })}
              />
              <Field
                label="不适用凭据"
                required
                value={item.evidence}
                onChange={(v) => update({ evidence: v })}
              />
            </>
          )}
          <Field
            label="不适用原因"
            required
            value={item.reason}
            onChange={(v) => update({ reason: v })}
          />
        </>
      )}
    </>
  );
}
