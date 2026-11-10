import type { InvestigationPatch } from "./types";
const prefix = "production-investigation:";
const key = (user: string, project: string) => `${prefix}${user}:${project}`;
export interface ResumeEntry {
  id?: string;
  pending: InvestigationPatch;
}
export function activeProductionProject(user: string): string {
  try {
    const value = JSON.parse(
      sessionStorage.getItem(key(user, "active")) || "null",
    );
    return typeof value?.projectId === "string" &&
      /^[1-9][0-9]{0,19}$/.test(value.projectId)
      ? value.projectId
      : "";
  } catch {
    return "";
  }
}
export function readProductionResume(
  user: string,
  project: string,
): ResumeEntry | null {
  try {
    return JSON.parse(sessionStorage.getItem(key(user, project)) || "null");
  } catch {
    return null;
  }
}
export function saveProductionResume(
  user: string,
  project: string,
  value: ResumeEntry,
) {
  if (!user || !project) return;
  try {
    sessionStorage.setItem(key(user, project), JSON.stringify(value));
    sessionStorage.setItem(
      key(user, "active"),
      JSON.stringify({ projectId: project, id: value.id }),
    );
  } catch {
    /* Server remains authoritative when browser storage is unavailable. */
  }
}
export function clearProductionResume(user: string) {
  try {
    for (const k of Object.keys(sessionStorage))
      if (k.startsWith(`${prefix}${user}:`)) sessionStorage.removeItem(k);
  } catch {}
}
