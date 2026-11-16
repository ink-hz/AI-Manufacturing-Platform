/** Fixed, authenticated manufacturing assets; never changes shared host branding. */
export function manufacturingBrand(apiBase: string, release: string): { logo: string; icon: string } {
  const base = apiBase.replace(/\/+$/, "");
  if (!base.startsWith("/") || base.startsWith("//") || /[\\?#]/.test(base) ||
      new URL(base, location.origin).origin !== location.origin)
    throw new Error("apiBase must be a same-origin path");
  const asset = (name: string) => `${base}/workflow/assets/${name}?release=${encodeURIComponent(release)}`;
  return { logo: asset("master-logo-v2.png"), icon: asset("app-icon-v2.png") };
}
