export const methods = {
  unknown: "方式未核实",
  manual: "人工登记",
  file: "文件传递",
  api: "API方式（仅登记）",
};
export const usages = {
  unverified: "待核实",
  purchased_unused: "已购买未使用",
  used_bypassed: "已使用但被绕过",
  manual_effective: "人工流程有效",
  missing: "能力缺失",
};
export const objects = {
  material: "物料",
  ebom: "设计清单 EBOM",
  mbom: "制造清单 MBOM",
  work_order: "工单",
  inventory: "库存",
  inspection: "检验",
  equipment: "设备",
};
export const packageKinds = {
  ebom: "设计清单",
  mbom: "制造清单",
  drawing: "图纸",
  route: "工艺路线",
  sop: "作业指导",
  firmware: "固件",
  test_program: "测试程序",
  test_spec: "测试规范",
  other: "其他资料",
};
export const packageStates = {
  draft: "草稿",
  review: "待人工核对",
  verified: "已人工核对 / 冻结",
  returned: "已退回",
  invalid: "已失效",
};
export const assertions = {
  pending: "待核对",
  verified: "已人工核对",
  blocked: "受阻",
  na: "不适用（有理由）",
};
export const readinessKinds = {
  version: "版本核对",
  materials: "材料准备",
  equipment: "设备准备",
  people: "人员准备",
  first_article: "首件确认",
  customer: "客户条件",
  customer_material: "客供料准备",
};
export const readinessStates = {
  pending: "待核对",
  blocked: "受阻",
  complete: "必需项已核对",
};
export const handoffStates = {
  draft: "交接草稿",
  sent: "已登记交出",
  received: "已登记接收",
  returned: "已登记退回",
  cancelled: "已取消",
};
export const packageActions = {
  submit: "提交人工核对",
  verify: "确认人工核对",
  return: "退回资料包",
  revise: "创建新修订",
  invalidate: "登记资料失效",
};
export const handoffActions = {
  send: "登记交出",
  receive: "登记接收",
  return: "登记退回",
  cancel: "取消交接",
};
const reasons: Record<string, string> = {
  "Package awaits manual verification": "资料包等待人工核对",
  "Awaiting manual receipt": "等待人工登记接收",
  "Handoff draft": "交接尚为草稿",
  "Handoff returned": "交接已登记退回",
  "Engineering material requires review": "工程资料项等待人工核对",
  "Execution basis is not verified": "执行依据尚未完成人工核对",
  "Readiness requires evidence": "准备核对需要凭据",
  "Package invalidated": "资料包已登记失效",
  "Source system retired or business scope removed":
    "来源系统已停用或移出该业务线",
};
const events: Record<string, string> = {
  create: "建立记录",
  update: "更新记录",
  submit: "提交人工核对",
  verify: "完成人工核对",
  return: "登记退回",
  revise: "建立新修订",
  invalidate: "登记失效",
  send: "登记交出",
  receive: "登记接收",
  cancel: "取消交接",
  issue_created: "登记关联问题",
  supersede: "被新核对替代",
  retire: "停用记录",
  basis_invalidated: "准备依据已失效",
};
export const reasonLabel = (reason: string) =>
  reasons[reason] ||
  (reason.startsWith("Package invalidated: ")
    ? "资料包已失效：" + reason.slice(21)
    : /^Replaced by .+ for package revision \d+$/.test(reason)
      ? reason.replace(
          /^Replaced by (.+) for package revision (\d+)$/,
          "由 $1 替代，资料修订 $2",
        )
      : reason);
export const eventLabel = (action: string) => events[action] || "业务记录更新";
