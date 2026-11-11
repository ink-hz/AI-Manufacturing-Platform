// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { MesIqcResults } from "./MesIqcResults";
import { project } from "../testHelpers";
it("admits only a verified result for the exact receipt and unit", async () => {
  const receipt = {
    system: "wms",
    object_type: "receipt",
    external_id: "receipt-A",
    version: 1,
  };
  const fact = (id: string, sourceReceipt = receipt, unit = "kg") => ({
    source: { system: "mes", object_type: "iqc", external_id: id, version: 1 },
    project_id: project.id,
    payload: {
      fact_type: "mes.iqc",
      receipt: sourceReceipt,
      accepted: { quantity: "1", unit },
      rejected: { quantity: "0", unit },
      evidence: "单据",
    },
  });
  const good = fact("GOOD"),
    wrong = fact("WRONG", { ...receipt, external_id: "other" }),
    badUnit = fact("BAD", receipt, "piece");
  const api = {
    integrationLinks: vi
      .fn()
      .mockResolvedValue({
        records: [{ source_key: receipt }],
        continuation: null,
      }),
    systemFacts: vi
      .fn()
      .mockResolvedValue({
        records: [good, wrong, badUnit],
        continuation: null,
      }),
    systemFact: vi
      .fn()
      .mockResolvedValue({
        fact: good,
        source_accepted: true,
        workflow_projected: false,
      }),
    command: vi
      .fn()
      .mockResolvedValue({
        project_id: project.id,
        project_version: 4,
        integration: { phase: "applied" },
      }),
  };
  const host = document.createElement("div"),
    root = createRoot(host);
  await act(async () =>
    root.render(
      <MesIqcResults
        api={api as never}
        project={{ ...project, allowed_actions: ["integration.pull"] as never }}
        receiptId="r"
        unit="kg"
        readOnly={false}
        onChanged={() => {}}
      />,
    ),
  );
  await act(async () => {});
  expect(host.textContent).toContain("单据");
  expect(
    [...host.querySelectorAll("button")].filter(
      (x) => x.textContent === "关联检验结果",
    ),
  ).toHaveLength(1);
  const b = [...host.querySelectorAll("button")].find(
    (x) => x.textContent === "关联检验结果",
  );
  expect(b).toBeTruthy();
  await act(async () => b!.click());
  expect(api.command).toHaveBeenCalledWith(
    project.id,
    expect.objectContaining({
      action: "integration.pull",
      source_key: good.source,
      expected_version: 3,
    }),
  );
  await act(async () => root.unmount());
});
