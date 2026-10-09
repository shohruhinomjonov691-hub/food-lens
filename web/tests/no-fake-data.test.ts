// Production code must never contain mock/demo predictions: results come only from the API.
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const roots = ["src", "app"].map((d) => path.resolve(__dirname, "..", d));
const files = (dir: string): string[] =>
  readdirSync(dir).flatMap((f) => {
    const p = path.join(dir, f);
    return statSync(p).isDirectory() ? files(p) : /\.(tsx?|css)$/.test(p) ? [p] : [];
  });

describe("no fake results in production code", () => {
  const sources = roots.flatMap(files).map((p) => [p, readFileSync(p, "utf8")] as const);
  it("has sources to check", () => expect(sources.length).toBeGreaterThan(5));
  it.each(["mock", "fixture", "fake", "demo", "sample", "placeholder"])("contains no %s data", (word) => {
    // The footer text "Portfolio demo" describes the site, it is not data.
    const clean = (s: string) => s.replace(/\/\/.*$|\/\*[\s\S]*?\*\//gm, "").replace(/Portfolio demo/g, "");
    const hits = sources.filter(([, s]) => new RegExp(`\\b${word}`, "i").test(clean(s)));
    expect(hits.map(([p]) => path.basename(p))).toEqual([]);
  });
  it("never writes a confidence value itself", () => {
    const hits = sources.filter(([, s]) => /confidence:\s*[0-9.]/.test(s));
    expect(hits.map(([p]) => path.basename(p))).toEqual([]);
  });
});
