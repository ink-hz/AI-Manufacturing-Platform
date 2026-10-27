export interface MountOptions {
  /** Same-origin API root, e.g. /api/v1/manufacturing. */
  apiBase: string;
  csrfToken: string;
  readOnly: boolean;
  onAuthError?: () => void;
  onDirtyChange?: (dirty: boolean) => void;
}
export interface Group {
  id: string;
  name: string;
  enabled: boolean;
  order: number;
}
export interface Line extends Group {
  group_id: string;
  description: string;
  stage_ids: string[];
}
export interface Participant {
  name: string;
  role: string;
  responsibility: string;
}
export interface Handoff {
  name: string;
  from_party: string;
  to_party: string;
  version_reference: string;
  notes: string;
}
export interface SystemRelationship {
  name: string;
  kind: string;
  objects: string;
  maintainer: string;
  method: "unknown" | "manual" | "file" | "api";
  notes: string;
}
export interface Stage {
  id: string;
  name: string;
  purpose: string;
  help: string;
  prompts: string[];
  reference_participants: Participant[];
  reference_handoffs: Handoff[];
  reference_systems: SystemRelationship[];
}
export interface Catalog {
  groups: Group[];
  lines: Line[];
  stages: Stage[];
  can_edit: boolean;
  release: string;
}
export interface RecordContent {
  practice: string;
  participants: Participant[];
  handoffs: Handoff[];
  systems: SystemRelationship[];
}
export interface StageRecord extends RecordContent {
  version: number;
  updated_at: string | null;
  updated_by: string | null;
}
export interface RecordWrite extends RecordContent {
  expected_version: number;
}
export interface Task {
  id: string;
  title: string;
  completed: boolean;
  version: number;
  created_at: string;
  updated_at: string;
  updated_by: string;
}
export interface TaskCreate {
  title: string;
  operation_id: string;
}
export interface TaskWrite {
  title: string;
  completed: boolean;
  expected_version: number;
}
export interface LineOverview {
  line: Line;
  stages: (Stage & { recorded: boolean; open_tasks: number })[];
  can_edit: boolean;
}
export interface StageResponse {
  line: Line;
  stage: Stage;
  record: StageRecord;
  tasks: Task[];
  can_edit: boolean;
}
