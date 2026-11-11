// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { startHttpHost, projectInput } from "./httpTestHost";
import { SupplyWorkspace } from "./SupplyWorkspace";
import { App } from "../App";
it("reads the OEM material workspace from the authenticated local FastAPI service", async () => {
  const http = await startHttpHost();
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    const session = await http.login("owner");
    vi.stubGlobal("fetch", session.transport);
    const project = await session.api.createProject({
      ...projectInput(),
      mode: "oem",
    });
    const overview = await session.api.materialOverview();
    expect(overview.items.some((x) => x.project_id === project.id)).toBe(true);
    await act(async () =>
      root.render(
        <SupplyWorkspace
          api={session.api}
          project={project}
          readOnly={false}
          onChanged={() => {}}
          onOpen={() => {}}
          onDirty={() => {}}
          requestLeave={(f) => f()}
        />,
      ),
    );
    for (let i = 0; i < 100 && !host.textContent?.includes("暂无物料需求"); i++)
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });
    expect(host.textContent).toContain("暂无物料需求");
    expect(host.textContent).toContain("料况");
    const noCsrf = await session.transport(
      `/api/v1/manufacturing/workflow/projects/${project.id}/commands`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          action: "material_task.accept",
          task_id: crypto.randomUUID(),
          operation_id: crypto.randomUUID(),
          expected_version: project.version,
        }),
      },
    );
    expect(noCsrf.status).toBe(403);
  } finally {
    await act(async () => root.unmount());
    host.remove();
    vi.unstubAllGlobals();
    await http.close();
  }
}, 30000);
it("opens an expedite through the component against FastAPI with project version and CSRF", async () => {
  const http = await startHttpHost();
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    const s = await http.login("owner");
    vi.stubGlobal("fetch", s.transport);
    const p = await s.api.createProject({ ...projectInput(), mode: "oem" });
    await s.api.grant(p.id, s.identity.user_id, {
      operation_id: crypto.randomUUID(),
      expected_version: p.version,
      scope: { kind: "project", project_id: p.id },
      roles: [
        "project_owner",
        "engineering",
        "planner",
        "supply",
        "production",
        "quality",
        "warehouse",
      ],
      qualifications: [
        "inspection",
        "disposition",
        "quality_release",
        "readiness_verification",
      ],
      active: true,
      evidence: "Synthetic roles",
    });
    const cmd = async (fields: import("./types").CommandFields) =>
      s.api.command(p.id, {
        ...fields,
        operation_id: crypto.randomUUID(),
        expected_version: (await s.api.project(p.id)).version,
      });
    const src = (object_type: string) => ({
      system: "HTTP fixture",
      object_type,
      external_id: crypto.randomUUID(),
      version: 1,
      mode: "manual" as const,
      occurred_at: new Date().toISOString(),
      collected_at: new Date().toISOString(),
      cutoff: null,
      evidence: "Synthetic",
    });
    const demand = (
      await cmd({
        action: "demand.record",
        kind: "firm",
        product: "Camera",
        quantity: "2",
        unit: "piece",
        due_date: "2026-12-01",
        source: src("demand"),
      })
    ).object_id;
    for (const dimension of [
      "technical",
      "material",
      "capacity",
      "commercial",
      "quality",
    ] as const)
      await cmd({
        action: "demand.review",
        demand_id: demand,
        dimension,
        decision: "approved",
        evidence: "Synthetic review",
      });
    const order = (
      await cmd({
        action: "order.register",
        demand_id: demand,
        quantity: "2",
        unit: "piece",
        due_date: "2026-12-01",
        source: src("order_line"),
      })
    ).object_id;
    const revision = (
      await cmd({
        action: "engineering.revision",
        package_id: crypto.randomUUID(),
        revision: "M1",
        customer_revision: "C1",
        internal_revision: "M1",
        items: [
          {
            id: crypto.randomUUID(),
            kind: "drawing",
            title: "Drawing",
            revision: "M1",
            evidence: "Synthetic drawing",
            status: "verified",
            source_system_id: null,
            source_name: "",
            source_ref: "",
            owner: "Engineering",
            reason: "",
          },
        ],
        route_steps: [{ station: "assembly", instruction_version: "S1" }],
        test_spec: {
          version: "T1",
          program_version: "P1",
          measurements: [
            { name: "voltage", unit: "V", lower: "4", upper: "6" },
          ],
        },
        firmware_version: "F1",
      })
    ).object_id;
    await cmd({
      action: "engineering.handoff",
      revision_id: revision,
      to_system: "MES",
      received_revision: "M1",
      decision: "accepted",
      evidence: "Synthetic receipt",
    });
    const wo = (
      await cmd({
        action: "work_order.register",
        order_line_id: order,
        revision_id: revision,
        unit: "piece",
        purpose: "production",
        quantity: "2",
        trial_quantity: "1",
        planned_start: "2026-12-01T00:00:00Z",
        planned_end: "2026-12-02T00:00:00Z",
        source: src("work_order"),
      })
    ).object_id;
    await cmd({
      action: "order.allocate",
      order_line_id: order,
      work_order_id: wo,
      quantity: "2",
      unit: "piece",
    });
    const lot = await cmd({
      action: "material.define",
      material_id: "steel",
      lot_id: "LOT-1",
      owner_id: "Customer 1",
      unit: "kg",
      scale: 3,
      expiry: "2027-12-01",
      source: src("material_lot"),
    });
    await cmd({
      action: "plan.receive",
      source: { ...src("plan"), cutoff: new Date().toISOString() },
      input_revision_ids: [revision],
      input_order_versions: [
        {
          order_line_id: order,
          version: (await s.api.object(p.id, "order_line", order)).summary
            .version,
        },
      ],
      requirements: [
        {
          work_order_id: wo,
          execution_scope: "trial",
          material_id: "steel",
          owner_id: "Customer 1",
          quantity: "1.25",
          unit: "kg",
        },
      ],
    }).catch((e) => {
      throw new Error(
        JSON.stringify({
          status: e.status,
          code: e.code,
          reasons: e.reasons,
          fields: e.fields,
        }),
      );
    });
    const project = await s.api.project(p.id);
    let changed = false;
    await act(async () =>
      root.render(
        <SupplyWorkspace
          api={s.api}
          project={project}
          readOnly={false}
          onChanged={() => {
            changed = true;
          }}
          onOpen={() => {}}
          onDirty={() => {}}
          requestLeave={(f) => f()}
        />,
      ),
    );
    const wait = async (f: () => boolean) => {
      for (let i = 0; i < 150 && !f(); i++)
        await act(async () => {
          await new Promise((r) => setTimeout(r, 20));
        });
      expect(f(), host.textContent || "").toBe(true);
    };
    const click = async (t: string) => {
      await wait(() =>
        [...host.querySelectorAll("button")].some((b) => b.textContent === t),
      );
      await act(async () =>
        [...host.querySelectorAll("button")]
          .find((b) => b.textContent === t)!
          .click(),
      );
    };
    await click("steel");
    expect(host.textContent).toContain("1.25 kg");
    await click("发起催料");
    for (const [name, value] of [
      ["催料原因", "缺料"],
      ["影响", "装配等待"],
    ]) {
      const e = host.querySelector(
        `[aria-label="${name}"]`,
      ) as HTMLInputElement;
      await act(async () => {
        Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype,
          "value",
        )!.set!.call(e, value);
        e.dispatchEvent(new Event("input", { bubbles: true }));
      });
    }
    await click("提交催料");
    await wait(() => changed);
    const page = await s.api.materialProject(p.id);
    expect(page.expedites).toHaveLength(1);
    expect(page.expedites[0]).toMatchObject({
      reason: "缺料",
      impact: "装配等待",
    });
    const requirement = page.requirements[0].id;
    const commitment = await cmd({
      action: "supply.commit",
      requirement_id: requirement,
      type: "purchase",
      owner_id: "Customer 1",
      quantity: "1.25",
      unit: "kg",
      original_due: "2026-12-01",
      current_due: "2026-12-01",
      source: src("commitment"),
    });
    const receipt = await cmd({
      action: "supply.receive",
      commitment_id: commitment.object_id,
      material_lot_id: lot.object_id,
      quantity: "1.25",
      unit: "kg",
      source: src("receipt"),
    });
    const task = await cmd({
      action: "material_task.open",
      requirement_id: requirement,
      task_kind: "iqc",
      receipt_id: receipt.object_id,
      handoff_id: null,
      assignee_id: s.identity.user_id,
      note: "检查钢材",
    });
    const boot = await s.api.bootstrap();
    await act(async () =>
      root.render(<App options={{ ...s.options, bootstrap: boot }} />),
    );
    await click("事项");
    await click("检查钢材");
    await wait(() => !!host.querySelector('[aria-label="物料任务"]'));
    await click("接单");
    await wait(
      () =>
        host.textContent?.includes("登记检验结果") === true &&
        host.textContent?.includes("处理中") === true,
    );
    await act(async () => {
      await new Promise((r) => setTimeout(r, 100));
    });
    expect(host.querySelector('[aria-label="物料任务"]')).toBeTruthy();
    await click("登记检验结果");
    for (const [name, value] of [
      ["合格数量", "1"],
      ["拒收数量", "0.25"],
      ["检验说明", "检验完成"],
    ]) {
      const e = host.querySelector(
        `[aria-label="${name}"]`,
      ) as HTMLInputElement;
      expect(e, name).toBeTruthy();
      await act(async () => {
        Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype,
          "value",
        )!.set!.call(e, value);
        e.dispatchEvent(new Event("input", { bubbles: true }));
      });
    }
    await click("提交");
    await wait(
      () =>
        host.textContent?.includes("完成任务") === true &&
        !host.textContent?.includes("正在读取任务"),
    );
    await act(async () => {
      await new Promise((r) => setTimeout(r, 100));
    });
    expect(host.querySelector('[aria-label="物料任务"]')).toBeTruthy();
    await click("完成任务");
    const evidence = host.querySelector(
      '[aria-label="完成说明"]',
    ) as HTMLInputElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(evidence, "检验完毕");
      evidence.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await click("提交");
    await wait(
      () =>
        host
          .querySelector('[aria-label="物料任务"]')
          ?.textContent?.includes("状态：已完成") === true,
    );
    expect(host.querySelector('[aria-label="物料任务"]')).toBeTruthy();
    expect(
      (await s.api.object(p.id, "material_task", task.object_id)).summary.state,
    ).toBe("closed");
    await click("返回业务列表");
    expect(host.querySelector('[aria-label="我的待处理事项"]')).toBeTruthy();
  } finally {
    await act(async () => root.unmount());
    host.remove();
    vi.unstubAllGlobals();
    await http.close();
  }
}, 30000);
