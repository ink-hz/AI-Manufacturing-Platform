import { expect, it } from "vitest";
import { manufacturingBrand } from "./branding";
it("uses release-pinned same-origin branding at the configured API mount", () => {
  expect(manufacturingBrand("/preview/api/v1/manufacturing/", "r 2")).toEqual({
    logo: "/preview/api/v1/manufacturing/workflow/assets/master-logo-v2.png?release=r%202",
    icon: "/preview/api/v1/manufacturing/workflow/assets/app-icon-v2.png?release=r%202",
  });
});
it.each(["//evil.test/api", "https://evil.test", "/\\evil.test/api", "/api?x=1", "/api#x"])("rejects unsafe API mount %s", base => {
  expect(() => manufacturingBrand(base, "r")).toThrow();
});
