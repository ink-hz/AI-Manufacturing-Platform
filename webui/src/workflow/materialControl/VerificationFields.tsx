import type { TaskReference } from "./types";

export type VerificationOutcome = "identity_verified" | "unable_to_verify" | "incorrect_observation" | "superseded";
export function VerificationFields({ outcome, onOutcome, current, currentReference, adopted, onAdopt }: {
  outcome: VerificationOutcome; onOutcome(value: VerificationOutcome): void;
  current: boolean | null; currentReference: TaskReference | null;
  adopted: boolean; onAdopt(value: boolean): void;
}) {
  return <>
    <label>核实结论
      <select aria-label="核实结论" value={outcome} onChange={e => onOutcome(e.target.value as VerificationOutcome)}>
        <option value="identity_verified">身份已核实</option>
        <option value="unable_to_verify">无法核实</option>
        <option value="incorrect_observation">观察有误</option>
        <option value="superseded">已替代</option>
      </select>
    </label>
    {outcome === "identity_verified" && current !== true && (currentReference
      ? <label><input type="checkbox" aria-label="采用当前引用" checked={adopted} onChange={e => onAdopt(e.target.checked)} />明确采用当前引用</label>
      : <p>当前引用不可采用；请选择其他结论。</p>)}
  </>;
}
