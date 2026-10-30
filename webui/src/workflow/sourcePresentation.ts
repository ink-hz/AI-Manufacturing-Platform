import type { SourceRef } from "./types";

export function sourceModeLabel(mode: SourceRef["mode"]): string {
  return {
    manual: "人工登记",
    file: "文件导入",
    mock: "模拟系统",
    api: "接口采集",
  }[mode];
}

export function compactSource(source: SourceRef): string {
  return `${source.system} · ${sourceModeLabel(source.mode)}`;
}
