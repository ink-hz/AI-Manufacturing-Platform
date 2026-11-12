// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { ArrivalObservationForm } from "./ArrivalObservationForm";
import { project } from "../testHelpers";

it("records only the observed package details with generated attributable metadata", async () => {
  const host=document.createElement("div"); document.body.append(host); const root=createRoot(host);
  const result={project_id:project.id,project_version:4,object_type:"arrival",object_id:"a"};
  const api={command:vi.fn().mockResolvedValue(result)}; const recorded=vi.fn(), changed=vi.fn();
  await act(async()=>root.render(<ArrivalObservationForm p={{api:api as never,project:{...project,allowed_actions:["arrival.record"]},readOnly:false,onChanged:vi.fn(),onMaterialChanged:changed,onDirty:vi.fn(),onOpen:vi.fn(),requestLeave:f=>f()}} onRecorded={recorded}/>));
  for(const [label,value] of [["到件编号","箱 A"],["观察位置","收货区"],["包裹数","2"],["实物描述","标签轴承"]]) {
    const input=host.querySelector(`[aria-label="${label}"]`) as HTMLInputElement;
    await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value")!.set!.call(input,value);input.dispatchEvent(new Event("input",{bubbles:true}));});
  }
  await act(async()=>[...host.querySelectorAll("button")].find(b=>b.textContent==="保存观察")!.click());
  expect(api.command).toHaveBeenCalledWith(project.id,expect.objectContaining({action:"arrival.record",arrival_number:"箱 A",location:"收货区",package_count:2,description:"标签轴承",expected_version:3,source:expect.objectContaining({mode:"manual",object_type:"arrival",version:1,evidence:"标签轴承"})}));
  expect(api.command.mock.calls[0][1]).not.toHaveProperty("receipt_id"); expect(changed).toHaveBeenCalledWith(result); expect(recorded).toHaveBeenCalled();
  await act(async()=>root.unmount());host.remove();
});
