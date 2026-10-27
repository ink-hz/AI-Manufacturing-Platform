import type { Activity } from "./types";
export function ActivityFeed({
  items,
  onOpen,
}: {
  items: Activity[];
  onOpen?: (id: string, stage?: string) => void;
}) {
  return (
    <section className="mf-activity" aria-label="最近动态">
      <h3>最近动态</h3>
      {!items.length ? (
        <p className="mf-muted">尚无操作记录。</p>
      ) : (
        <ol>
          {items.map((a) => (
            <li key={a.id}>
              <div>
                {a.project_id && onOpen ? (
                  <button
                    className="mf-link"
                    onClick={() =>
                      onOpen(a.project_id!, a.stage_id || undefined)
                    }
                  >
                    {a.project_name}
                  </button>
                ) : null}{" "}
                {a.summary}
              </div>
              <small className="mf-muted">
                {a.actor} ·{" "}
                <time dateTime={a.created_at}>
                  {a.created_at.replace("T", " ").slice(0, 16)}
                </time>
              </small>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
