import type { Attention, ControlTarget } from "./types";
import { reasonLabel } from "./labels";
export function ControlAttention({
  items,
  onOpen,
}: {
  items: Attention[];
  onOpen: (project: string, target: ControlTarget) => void;
}) {
  return items.length ? (
    <section>
      <h3>协同待处理</h3>
      {items.slice(0, 12).map((a, n) => (
        <article
          className="mf-attention-row"
          key={`${a.object_id}-${a.item_id}-${n}`}
        >
          <button className="mf-link" onClick={() => onOpen(a.project_id, a)}>
            {a.title}
          </button>
          <p>{reasonLabel(a.reason)}</p>
          <small>
            {a.project_name} · {a.owner || "未分派"} ·{" "}
            {a.due_date || "未设日期"}
          </small>
        </article>
      ))}
    </section>
  ) : null;
}
