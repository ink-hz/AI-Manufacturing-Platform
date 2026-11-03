import {SystemStepPanel} from './integrations/SystemStepPanel';
import { OEMWorkspace, type OEMWorkspaceProps } from "./OEMWorkspace";
export function LaboratoryWorkspace(p: OEMWorkspaceProps) {
  return <><SystemStepPanel {...p} context="laboratory" selected={p.initialObject?.summary||null}/><OEMWorkspace {...p} domain="laboratory" /></>;
}
