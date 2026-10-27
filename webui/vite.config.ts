import { defineConfig } from "vitest/config";
export default defineConfig(({ command }) => ({
  esbuild: { jsx: "automatic" },
  define:
    command === "build"
      ? { "process.env.NODE_ENV": JSON.stringify("production") }
      : {},
  build: {
    lib: {
      entry: "src/index.tsx",
      name: "OrbbecManufacturing",
      formats: ["iife"],
      fileName: () => "manufacturing.js",
      cssFileName: "manufacturing",
    },
    cssCodeSplit: false,
  },
  test: { environment: "jsdom", setupFiles: ["src/test-setup.ts"] },
}));
