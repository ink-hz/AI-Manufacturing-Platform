import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { splitChapters } from "./handbook";
it("preserves every source byte and recognizes only real H2 phase headings outside fences", () => {
  const source =
    "前言\n# 第一部分\n总览\n```md\n## 5. S1 假标题\n```\n## 5. S1 需求\n正文\n~~~\n## S2 假标题\n~~~\n## S2 工程\n结尾\n";
  const chapters = splitChapters(source);
  expect(chapters.map((c) => c.markdown).join("")).toBe(source);
  expect(chapters.filter((c) => c.stageId).map((c) => c.stageId)).toEqual([
    "S1",
    "S2",
  ]);
  const actual = readFileSync(
    "../docs/manufacturing-system-handbook.md",
    "utf8",
  );
  const real = splitChapters(actual);
  expect(real.map((c) => c.markdown).join("")).toBe(actual);
  expect(real.filter((c) => c.stageId).map((c) => c.stageId)).toEqual(
    Array.from({ length: 9 }, (_, i) => `S${i + 1}`),
  );
});
it("preserves related workflow source, CRLF preambles and nested fence lengths without false phases", () => {
  const actual = readFileSync(
    "../docs/workflows/manufacturing-process-overview.md",
    "utf8",
  );
  expect(
    splitChapters(actual)
      .map((c) => c.markdown)
      .join(""),
  ).toBe(actual);
  const source =
    "前言\r\n\r\n# S1 不是阶段\r\n````md\r\n```\r\n## S2 假标题\r\n````\r\n## 普通目录 S3\r\n## S4物料\r\n## 8. S4 物料\r\n尾注";
  const chapters = splitChapters(source);
  expect(chapters.map((c) => c.markdown).join("")).toBe(source);
  expect(chapters.filter((c) => c.stageId).map((c) => c.stageId)).toEqual([
    "S4",
  ]);
});
