import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
const dom = new JSDOM('<div id="mount"></div>', {
  url: "https://workbench.example/",
  runScripts: "outside-only",
});
try {
  dom.window.eval(
    readFileSync(new URL("../dist/manufacturing.js", import.meta.url), "utf8"),
  );
  assert.equal(typeof dom.window.OrbbecManufacturing?.mount, "function");
  assert.ok(
    readFileSync(
      new URL("../dist/manufacturing.css", import.meta.url),
      "utf8",
    ).includes(".mf-root"),
  );
  console.log(
    "IIFE global and scoped CSS verified without Node globals or browser automation.",
  );
} finally {
  dom.window.close();
}
