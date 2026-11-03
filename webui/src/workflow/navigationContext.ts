import type { ConsoleView } from "../console/ConsoleShell";
import type { ObjectKind } from "./types";

export type BusinessModule =
  | "introduction"
  | "laboratory"
  | "orders"
  | "supply"
  | "execution"
  | "quality"
  | "collaboration";
type LedgerTab = { kind: ObjectKind; title: string; column: string };
export const businessModules: Record<
  BusinessModule,
  { title: string; tabs: LedgerTab[] }
> = {
  introduction: {
    title: "工程与资产台账",
    tabs: [
      { kind: "npi", title: "工程导入", column: "导入记录" },
      { kind: "npi_issue", title: "导入问题", column: "问题记录" },
      { kind: "reusable_asset", title: "资产修订", column: "资产名称" },
      { kind: "asset_use", title: "采用验证", column: "采用记录" },
      { kind: "revision", title: "固定修订", column: "资料修订" },
    ],
  },
  laboratory: {
    title: "测试与标定台账",
    tabs: [
      { kind: "test_plan", title: "测试计划", column: "工位与设备" },
      { kind: "test_run", title: "测试运行", column: "SN 与运行" },
      { kind: "calibration", title: "标定读回", column: "SN 与算法" },
      { kind: "component_link", title: "部件履历", column: "SN 与部件" },
      { kind: "unit", title: "单台履历", column: "出厂 SN" },
    ],
  },
  orders: {
    title: "订单与交付台账",
    tabs: [
      { kind: "order_line", title: "订单", column: "订单编号" },
      { kind: "demand", title: "需求", column: "需求编号" },
      { kind: "commitment_change", title: "承诺变更", column: "变更编号" },
      { kind: "shipment", title: "发货", column: "发货编号" },
      { kind: "closure", title: "关账", column: "关账记录" },
    ],
  },
  supply: {
    title: "计划与物料台账",
    tabs: [
      { kind: "requirement", title: "物料需求", column: "物料需求编号" },
      { kind: "plan", title: "计划", column: "计划编号" },
      { kind: "commitment", title: "供应承诺", column: "供应承诺编号" },
      { kind: "material_lot", title: "批次", column: "物料批次编号" },
      { kind: "arrival", title: "到件观察", column: "到件编号" },
      { kind: "receipt", title: "到货", column: "到货编号" },
      { kind: "reservation", title: "预留", column: "预留编号" },
      { kind: "material_handoff", title: "物料交接", column: "交接记录 · 批次 · 位置 · 双方" },
    ],
  },
  execution: {
    title: "工单与执行台账",
    tabs: [
      { kind: "work_order", title: "工单", column: "工单编号" },
      { kind: "unit", title: "SN", column: "产品序列号" },
      { kind: "interruption", title: "中断", column: "中断记录" },
    ],
  },
  quality: {
    title: "质量与追溯台账",
    tabs: [
      { kind: "test", title: "检验测试", column: "检验测试编号" },
      { kind: "nonconformance", title: "NCR", column: "不合格编号" },
      { kind: "rework", title: "返工", column: "返工编号" },
      { kind: "release", title: "放行", column: "放行编号" },
      { kind: "rma", title: "RMA", column: "退货编号" },
      { kind: "capa", title: "CAPA", column: "纠正预防编号" },
    ],
  },
  collaboration: {
    title: "系统交换与对账",
    tabs: [
      { kind: "exchange", title: "交换与对账", column: "交换编号" },
      { kind: "authority_rule", title: "系统责任", column: "责任范围" },
    ],
  },
};
export function isBusinessModule(view: ConsoleView): view is BusinessModule {
  return view in businessModules;
}
export interface LedgerContext {
  handoffState?: "pending" | "disputed" | "all";
  kind: ObjectKind;
  projectId: string;
  offset: number;
}
export interface TaskContext {
  projectId: string;
  offset: number;
}
export function initialLedgerContexts(): Record<BusinessModule, LedgerContext> {
  return Object.fromEntries(
    Object.entries(businessModules).map(([key, value]) => [
      key,
      { kind: value.tabs[0].kind, projectId: "", offset: 0 },
    ]),
  ) as Record<BusinessModule, LedgerContext>;
}
