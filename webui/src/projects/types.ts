import type { RecordContent, Stage } from "../types";
export type WorkStatus = "todo" | "doing" | "blocked" | "done";
export type ProjectStatus =
  | "planned"
  | "active"
  | "blocked"
  | "completed"
  | "archived";
export type Kind = "task" | "issue" | "confirmation";
export type Priority = "normal" | "high" | "urgent";
export const workStatus = {
  todo: "未开始",
  doing: "进行中",
  blocked: "受阻",
  done: "已完成",
};
export const projectStatus = {
  planned: "待启动",
  active: "进行中",
  blocked: "受阻",
  completed: "已完成",
  archived: "已归档",
};
export const kinds = { task: "任务", issue: "问题", confirmation: "确认事项" };
export const priorities = { normal: "普通", high: "高", urgent: "紧急" };
export interface ProjectFields {
  name: string;
  owner: string;
  product: string;
  customer: string;
  due_date: string | null;
  target_quantity: number | null;
  summary: string;
}
export type ProjectCreate = Pick<ProjectFields, "name" | "owner"> &
  Partial<ProjectFields> & { line_id: string; operation_id: string };
export type ProjectWrite = Partial<ProjectFields> & {
  expected_version: number;
  archived?: boolean;
};
export interface ProjectSummary extends ProjectFields {
  id: string;
  code: string;
  line_id: string;
  line_name: string;
  group_id: string;
  archived: boolean;
  version: number;
  created_at: string;
  updated_at: string;
  updated_by: string;
  status: ProjectStatus;
  current_stage_id: string;
  current_stage_name: string;
  completed_stages: number;
  total_stages: number;
  open_tasks: number;
}
export interface StageFields extends RecordContent {
  status: WorkStatus;
  owner: string;
  due_date: string | null;
  blocker: string;
}
export interface ProjectStage extends Stage, StageFields {
  version: number;
  updated_at: string;
  updated_by: string;
}
export type StageWrite = StageFields & { expected_version: number };
export interface TaskFields {
  stage_id: string;
  title: string;
  kind: Kind;
  owner: string;
  due_date: string | null;
  priority: Priority;
  notes: string;
}
export type ProjectTaskCreate = Pick<TaskFields, "stage_id" | "title"> &
  Partial<TaskFields> & { operation_id: string };
export type ProjectTaskWrite = Partial<TaskFields> & {
  expected_version: number;
  status?: WorkStatus;
};
export interface ProjectTask extends TaskFields {
  source?: { type: "readiness"; id: string; item_id: string } | null;
  id: string;
  project_id: string;
  status: WorkStatus;
  version: number;
  created_at: string;
  updated_at: string;
  updated_by: string;
}
export interface FlatTask extends ProjectTask {
  project_name: string;
  project_code: string;
  line_id: string;
  line_name: string;
  group_id: string;
  stage_name: string;
}
export interface Activity {
  id: string;
  created_at: string;
  actor: string;
  action: string;
  summary: string;
  stage_id: string | null;
  task_id: string | null;
  project_id?: string;
  project_name?: string;
}
export interface ProjectDetailData {
  project: ProjectSummary;
  stages: ProjectStage[];
  tasks: ProjectTask[];
  activity: Activity[];
}
export interface Blocker {
  project_id: string;
  project_name: string;
  stage_id: string;
  stage_name: string;
  task_id: string | null;
  title: string;
  reason: string;
  owner: string;
  due_date: string | null;
}
export interface Dashboard {
  control_attention?: import("../collaboration/types").Attention[];
  counts: {
    active_projects: number;
    blocked_projects: number;
    due_soon: number;
    open_tasks: number;
    pending_confirmations: number;
  };
  projects: ProjectSummary[];
  attention: FlatTask[];
  blockers: Blocker[];
  activity: Activity[];
}
export interface Handbook {
  title: string;
  markdown: string;
  updated_at: string;
  source_path: string;
  sha256: string;
  release: string;
}
export type DocumentName = "handbook" | "workflow";
export function message(error: unknown) {
  return error instanceof Error && error.name !== "AbortError"
    ? error.message
    : "请求失败，请重试";
}
