// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { startHttpHost, projectInput } from "./httpTestHost";
import { MesIqcResults } from "./materialControl/MesIqcResults";
import type { CommandFields } from "./types";
it("projects a selected existing MES result only for the task receipt", async () => {
  const http = await startHttpHost({ businessClock: "2026-11-03T00:00:00Z" }),
    host = document.createElement("div"),
    root = createRoot(host);
  try {
    const s = await http.login("owner");
    vi.stubGlobal("fetch", s.transport);
    const p = await s.api.createProject({
      ...projectInput("12"),
      name: "MES IQC",
      mode: "oem",
      customer_id: "C",
      product: "P",
      contract: {
        ...projectInput().contract,
        customer_revision: "A",
        internal_revision: "A",
      },
    });
    const refs = (await s.setupNetwork(p.id, "supply")).refs;
    const cmd = async (fields: CommandFields) =>
      s.api.command(p.id, {
        ...fields,
        operation_id: crypto.randomUUID(),
        expected_version: (await s.api.project(p.id)).version,
      });
    const wms = await cmd({
      action: "mock_system.execute",
      system: "wms",
      payload: {
        operation: "wms.receive",
        custodian: "warehouse",
        commitment_id: refs.commitment,
        material_lot_id: refs.lot,
        lot_id: "LOT",
        material_id: "M",
        owner_id: "C",
        amount: { quantity: "2", unit: "piece", scale: 0 },
        location: "receiving",
        supplier_batch: "B1",
        expiry: "2026-12-03",
      },
    });
    const intent = (await s.api.integrationIntents(p.id, 200, 0)).records.find(
      (i) => i.intent_id === wms.integration?.intent_id,
    )!;
    const source = intent.receipt!.source_keys[0];
    const receiptFact = await s.api.systemFact(p.id, source);
    const receipt = receiptFact.projection!.targets.find(
      (t) => t.kind === "receipt",
    )!.id;
    const task = await cmd({
      action: "material_task.open",
      requirement_id: refs.requirement,
      task_kind: "iqc",
      receipt_id: receipt,
      handoff_id: null,
      assignee_id: s.identity.user_id,
      note: "关联 MES 检验",
    });
    const operation = crypto.randomUUID();
    await s.configureNetworkFault(p.id, "mes", operation);
    await s.api.command(p.id, {
      action: "mock_system.execute",
      system: "mes",
      payload: {
        operation: "mes.inspect",
        receipt: source,
        accepted: { quantity: "2", unit: "piece", scale: 0 },
        rejected: { quantity: "0", unit: "piece", scale: 0 },
        evidence: "对应到货检验",
      },
      operation_id: operation,
      expected_version: (await s.api.project(p.id)).version,
    });
    const page = await s.api.systemFacts(p.id, "mes", {
      object_type: "iqc",
      limit: 50,
    });
    expect(
      page.records.some(
        (f) =>
          f.payload.fact_type === "mes.iqc" &&
          f.payload.receipt.external_id !== source.external_id,
      ),
    ).toBe(true);
    const fact = page.records.find(
      (f) =>
        f.payload.fact_type === "mes.iqc" &&
        f.payload.receipt.external_id === source.external_id,
    )!;
    expect(fact).toBeTruthy();
    const before = await s.api.systemFact(p.id, fact.source);
    expect(before.workflow_projected).toBe(false);
    let changed = false;
    await act(async () =>
      root.render(
        <MesIqcResults
          api={s.api}
          project={await s.api.project(p.id)}
          receiptId={receipt}
          unit="piece"
          readOnly={false}
          onChanged={() => {
            changed = true;
          }}
        />,
      ),
    );
    for (let i = 0; i < 200 && !host.textContent?.includes("对应到货检验"); i++)
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });
    expect(host.textContent).toContain("对应到货检验");
    expect(host.textContent).not.toContain("Receipt-specific IQC");
    expect(
      [...host.querySelectorAll("button")].filter(
        (b) => b.textContent === "关联检验结果",
      ),
    ).toHaveLength(1);
    const button = [...host.querySelectorAll("button")].find(
      (b) => b.textContent === "关联检验结果",
    );
    expect(button).toBeTruthy();
    await act(async () => button!.click());
    for (let i = 0; i < 200 && !changed; i++)
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });
    expect(changed, host.textContent || "").toBe(true);
    const after = await s.api.systemFact(p.id, fact.source);
    expect(after.workflow_projected).toBe(true);
    expect(after.projection?.targets).toContainEqual(
      expect.objectContaining({ kind: "receipt", id: receipt }),
    );
    const taskDetail = await s.api.object(
      p.id,
      "material_task",
      task.object_id,
    );
    expect(taskDetail.value).toMatchObject({ receipt_id: receipt });
    const receiptDetail = await s.api.object(p.id, "receipt", receipt);
    expect(receiptDetail.value).toMatchObject({ accepted: "2", rejected: "0" });
  } finally {
    await act(async () => root.unmount());
    vi.unstubAllGlobals();
    await http.close();
  }
}, 30000);
