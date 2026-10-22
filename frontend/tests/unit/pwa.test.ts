import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const pub = (p: string) => path.resolve(__dirname, "../../public", p);

describe("PWA assets", () => {
  const manifest = JSON.parse(readFileSync(pub("manifest.webmanifest"), "utf8"));

  it("is installable: standalone display, start url in scope, name and icons", () => {
    expect(manifest.display).toBe("standalone");
    expect(manifest.start_url.startsWith(manifest.scope)).toBe(true);
    expect(manifest.name && manifest.short_name).toBeTruthy();
    const sizes = manifest.icons.map((i: { sizes: string }) => i.sizes);
    expect(sizes).toContain("192x192");
    expect(sizes).toContain("512x512");
    expect(manifest.icons.some((i: { purpose: string }) => i.purpose === "maskable")).toBe(true);
  });

  it("points at icon files that exist and are real PNGs of the declared size", () => {
    for (const icon of manifest.icons as { src: string; sizes: string }[]) {
      const file = pub(icon.src.replace(/^\//, ""));
      expect(existsSync(file), icon.src).toBe(true);
      const buf = readFileSync(file);
      expect(buf.subarray(1, 4).toString()).toBe("PNG");
      const [w] = icon.sizes.split("x").map(Number);
      expect(buf.readUInt32BE(16)).toBe(w);
      expect(buf.readUInt32BE(20)).toBe(w);
    }
    expect(existsSync(pub("icons/apple-touch-icon.png"))).toBe(true);
  });

  it("ships an offline page and a service worker that never touches the API", () => {
    expect(existsSync(pub("offline.html"))).toBe(true);
    const sw = readFileSync(pub("sw.js"), "utf8");
    expect(sw).toContain("/offline.html");
    expect(sw).toMatch(/\(api\|ws\|healthz\)/);
  });
});
