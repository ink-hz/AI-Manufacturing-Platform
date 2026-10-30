import type { ReactNode } from "react";

export function OperationHelp({ children }: { children: ReactNode }) {
  return <details className="wf-operation-help"><summary>操作说明</summary>{children}</details>;
}
