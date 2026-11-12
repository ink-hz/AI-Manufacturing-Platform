import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { MaterialHandoffForms } from "./forms/MaterialHandoffForms";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;
let host: HTMLDivElement;
afterEach(async () => { if (root) await act(async () => root!.unmount()); host?.remove(); root = undefined; });
const selected: any = {
  kind: "material_handoff", id: "h1", material_lot_id: "lot1", work_order_id: "wo1",
  handoff_number: "交接20", quantity: "20", unit: "kg", from_location: "仓库", to_location: "线边仓",
  sender_id: "warehouse", receiver_id: "production", sender_name: "仓管", receiver_name: "产线收料员",
  state: "pending", receipt: null,
};
const requirement = (id: string, material_id = "steel-1") => ({
  id, execution_scope: "common", work_order_id: "wo1", material_id, owner_id: "Customer", unit: "kg", required: "20", state: "required",
});
const page = (requirements: any[], total = requirements.length) => ({ requirements, total, limit: 50, offset: 0, project_version: 7 });
function api() {
  return {
    object: vi.fn(async () => ({ value: { kind: "material_lot", material_id: "steel-1", owner_id: "Customer", unit: "kg" } })),
    materialProject: vi.fn(async (_id: string, _limit: number, _offset: number) => page([requirement("req1")])),
    command: vi.fn(async (_id: string, body: any) => ({ project_id: "p1", project_version: 8,
      operation_id: body.operation_id, object_type: "material_handoff", object_id: "h1", replayed: false })),
  };
}
async function mount(a: any, action = "material_handoff.receive", handoff = selected) {
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  await act(async () => root!.render(<MaterialHandoffForms api={a} project={{ id: "p1", version: 7 } as any}
    readOnly={false} onDirty={() => {}} onChanged={() => {}} onOpen={() => {}}
    action={action as any} lots={[]} workOrders={[]} members={[]} selected={handoff} />));
}
async function choose(name: string, value: string) {
  const element = host.querySelector<HTMLSelectElement>(`select[aria-label="${name}"]`);
  expect(element).not.toBeNull();
  await act(async () => { element!.value = value; element!.dispatchEvent(new Event("change", { bubbles: true })); });
}
async function input(name: string, value: string) {
  const element = host.querySelector<HTMLInputElement>(`input[aria-label="${name}"]`);
  expect(element).not.toBeNull();
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(element, value);
    element!.dispatchEvent(new Event("input", { bubbles: true })); });
}
async function save(text: string) {
  const button = [...host.querySelectorAll("button")].find(x => x.textContent === text);
  expect(button).toBeDefined(); expect(button!.disabled).toBe(false);
  await act(async () => button!.click());
}

it("records exact line-side use with a business requirement choice", async () => {
  const a = api(); await mount(a);
  await choose("实收用途", "line_side");
  expect(host.querySelector<HTMLOptionElement>('option[value="req1"]')!.textContent).toContain("共用");
  await choose("对应物料需求", "req1");
  await save("确认接收");
  expect(a.command).toHaveBeenCalledWith("p1", expect.objectContaining({
    action: "material_handoff.receive", receipt_use: "line_side", requirement_id: "req1",
    received_quantity: "20", received_location: "线边仓",
  }));
  expect(host.textContent).toContain("steel-1");
});

it("loads all scoped pages and excludes another material, owner, unit or work order", async () => {
  const a = api();
  a.materialProject.mockImplementation(async (_id: string, _limit: number, offset: number) => offset === 0
    ? page(Array.from({ length: 50 }, (_, i) => requirement("other" + i, "steel-10")), 51)
    : page([requirement("req51")], 51));
  await mount(a); await choose("实收用途", "line_side");
  const choices = host.querySelector<HTMLSelectElement>('select[aria-label="对应物料需求"]')!;
  expect([...choices.options].map(x => x.value)).toContain("req51");
  expect([...choices.options].some(x => x.value.startsWith("other"))).toBe(false);
  expect(a.materialProject).toHaveBeenCalledTimes(2);
});

it("confirms a legacy receipt purpose without rewriting its signed quantity or location", async () => {
  const a = api();
  await mount(a, "material_handoff.confirm_use", { ...selected, state: "received",
    receipt: { received_quantity: "18", received_location: "线边仓", receipt_use: "unspecified" } });
  await choose("实收用途", "line_side"); await choose("对应物料需求", "req1");
  await input("用途核对说明", "已核对该笔属于本工单需求");
  await save("保存实收用途");
  const body = a.command.mock.calls[0][1];
  expect(body).toMatchObject({ action: "material_handoff.confirm_use", handoff_id: "h1", receipt_use: "line_side", requirement_id: "req1" });
  expect(body).not.toHaveProperty("received_quantity");
  expect(body).not.toHaveProperty("received_location");
});

it("leaves transfer use independent from a final requirement", async () => {
  const a = api(); await mount(a);
  await choose("实收用途", "transfer"); await save("确认接收");
  expect(a.command).toHaveBeenCalledWith("p1", expect.objectContaining({ receipt_use: "transfer", requirement_id: null }));
  expect(a.materialProject).not.toHaveBeenCalled();
});

it("blocks a requirement list read from a newer project version", async () => {
  const a = api(); a.materialProject.mockResolvedValue({ ...page([requirement("req1")]), project_version: 8 });
  await mount(a); await choose("实收用途", "line_side");
  expect(host.textContent).toContain("项目资料已变化");
  expect([...host.querySelectorAll("button")].find(b => b.textContent === "确认接收")!.disabled).toBe(true);
  expect(a.command).not.toHaveBeenCalled();
});

for (const action of ["material_handoff.receive", "material_handoff.confirm_use"]) {
  for (const [scope, label] of [["trial", "试产"], ["bulk", "量产"]]) {
    it(`${action} identifies the ${label} demand and submits its ID`, async () => {
      const a = api();
      a.materialProject.mockResolvedValue(page([
        { ...requirement("trial-id"), execution_scope: "trial" },
        { ...requirement("bulk-id"), execution_scope: "bulk" },
      ]));
      const handoff = action.endsWith("confirm_use") ? { ...selected, state: "received",
        receipt: { received_quantity: "18", received_location: "线边仓", receipt_use: "unspecified" } } : selected;
      await mount(a, action, handoff); await choose("实收用途", "line_side");
      const options = [...host.querySelector<HTMLSelectElement>('select[aria-label="对应物料需求"]')!.options];
      expect(options.find(o => o.value === "trial-id")!.textContent).toContain("试产");
      expect(options.find(o => o.value === "bulk-id")!.textContent).toContain("量产");
      await choose("对应物料需求", options.find(o => o.textContent!.includes(label))!.value);
      if (action.endsWith("confirm_use")) await input("用途核对说明", "核对需求范围");
      await save(action.endsWith("confirm_use") ? "保存实收用途" : "确认接收");
      expect(a.command).toHaveBeenCalledWith("p1", expect.objectContaining({ action, requirement_id: `${scope}-id` }));
    });
  }
}

it("does not allow an unscoped legacy projection to be selected", async () => {
  const a = api(); a.materialProject.mockResolvedValue(page([{ ...requirement("legacy"), execution_scope: undefined }]));
  await mount(a); await choose("实收用途", "line_side");
  const option = host.querySelector<HTMLOptionElement>('option[value="legacy"]')!;
  expect(option.textContent).toContain("范围待核对"); expect(option.disabled).toBe(true);
  expect([...host.querySelectorAll("button")].find(b => b.textContent === "确认接收")!.disabled).toBe(true);
});
