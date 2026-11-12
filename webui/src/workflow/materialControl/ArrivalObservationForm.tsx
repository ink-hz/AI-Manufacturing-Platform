import { useRef, useState } from "react";
import type { OEMWorkspaceProps } from "../OEMWorkspace";
import { useMaterialCommand } from "./useMaterialCommand";

export function ArrivalObservationForm({ p, onRecorded }: {
  p: OEMWorkspaceProps;
  onRecorded(): void;
}) {
  const [number, setNumber] = useState("");
  const [location, setLocation] = useState("");
  const [count, setCount] = useState("1");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const version = useRef(p.project.version);
  const revision = useRef(0);
  const command = useMaterialCommand(p.api, p.project.id);
  const sourceId = useRef(crypto.randomUUID());
  const time = useRef(new Date().toISOString());
  const allowed = !p.readOnly && p.project.allowed_actions.includes("arrival.record");
  const authority = useRef({ allowed, version: p.project.version });
  if (authority.current.allowed !== allowed || authority.current.version !== p.project.version) {
    authority.current = { allowed, version: p.project.version };
    revision.current++;
  }
  const valid = number.trim() && location.trim() && description.trim() &&
    Number.isInteger(+count) && +count >= 1 && +count <= 100000;
  function edit(set: (v: string) => void, value: string) {
    revision.current++;
    set(value);
    p.onDirty("arrival-observation", true);
  }
  async function save() {
    if (!allowed || version.current !== p.project.version || busy || !valid) return;
    const token = revision.current;
    setBusy(true);
    setError("");
    try {
      const result = await command.execute({
        action: "arrival.record",
        arrival_number: number,
        location,
        package_count: +count,
        description,
        source: {
          system: "platform", object_type: "arrival", external_id: sourceId.current,
          version: 1, mode: "manual", occurred_at: time.current,
          collected_at: time.current, cutoff: null, evidence: description,
        },
      }, version.current, result => {
        if (p.onMaterialChanged) p.onMaterialChanged(result);
        else if (command.isCurrent() && revision.current === token) p.onChanged(result);
      });
      if (result && command.isCurrent() && revision.current === token) {
        p.onDirty("arrival-observation", false);
        onRecorded();
      }
    } catch (e) {
      if (command.isCurrent() && token === revision.current) setError(String(e));
    } finally {
      if (command.isCurrent()) setBusy(false);
    }
  }
  return (
    <section aria-label="实际包裹观察">
      <p>此观察不构成正式收货或库存记录。</p>
      <label>到件编号<input aria-label="到件编号" value={number} onChange={e => edit(setNumber, e.target.value)} /></label>
      <label>观察位置<input aria-label="观察位置" value={location} onChange={e => edit(setLocation, e.target.value)} /></label>
      <label>包裹数<input aria-label="包裹数" type="number" value={count} onChange={e => edit(setCount, e.target.value)} /></label>
      <label>实物描述<input aria-label="实物描述" value={description} onChange={e => edit(setDescription, e.target.value)} /></label>
      {version.current !== p.project.version && <p>项目已更新，草稿已保留。</p>}
      {error && <p role="alert">观察保存失败：{error}</p>}
      <button disabled={!allowed || busy || version.current !== p.project.version || !valid} onClick={() => void save()}>保存观察</button>
    </section>
  );
}
