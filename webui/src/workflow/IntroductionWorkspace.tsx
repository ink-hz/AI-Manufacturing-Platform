import {SystemStepPanel} from './integrations/SystemStepPanel';
import { OEMWorkspace, type OEMWorkspaceProps } from "./OEMWorkspace";
export function IntroductionWorkspace(p: OEMWorkspaceProps) {
  return <><SystemStepPanel {...p} context="introduction" selected={p.initialObject?.summary||null}/><OEMWorkspace {...p} domain="introduction" /></>;
}
