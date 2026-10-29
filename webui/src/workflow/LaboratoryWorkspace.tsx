import { OEMWorkspace, type OEMWorkspaceProps } from "./OEMWorkspace";
export function LaboratoryWorkspace(p: OEMWorkspaceProps) {
  return <OEMWorkspace {...p} domain="laboratory" />;
}
