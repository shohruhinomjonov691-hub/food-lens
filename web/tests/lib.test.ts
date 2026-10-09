import { describe, expect, it, vi } from "vitest";
import { fetchIngredients, parsePrediction, predict } from "@/lib/api";
import { clampRect, DEFAULT_RECT, MIN_SIZE, moveRect, outputSize, resizeCorner, toPixels } from "@/lib/crop";
import { DISHES, VARIANTS } from "@/lib/dishes";
import { initialState, reducer, type State } from "@/lib/flow";
import { loadLang, MESSAGES, saveLang, translate } from "@/lib/i18n";
import { checkDimensions, checkFile, sniff } from "@/lib/upload";

const PREDS = [{ class: "kebab", confidence: 0.81 }, { class: "pizza", confidence: 0.1 }, { class: "hot_dog", confidence: 0.05 }];
const okBody = { predictions: PREDS, uncertain: false, threshold: 0.6 };
const photo = (url = "blob:p1") => ({ url, width: 800, height: 600 });
const ok = { kind: "ok" as const, predictions: [{ dish: "kebab" as const, confidence: 0.81 },
  { dish: "pizza" as const, confidence: 0.1 }, { dish: "hot_dog" as const, confidence: 0.05 }], uncertain: false, threshold: 0.6 };

function analyzing(): State {
  let s = reducer(initialState, { type: "PHOTO_LOADED", photo: photo() });
  s = reducer(s, { type: "ANALYZE", sentCrop: photo("blob:c1") });
  return s;
}

describe("flow reducer: stale responses never win", () => {
  it("applies the current prediction", () => {
    const s = analyzing();
    const r = reducer(s, { type: "PREDICTED", seq: s.seq, outcome: ok });
    expect(r.stage).toBe("result");
    expect(r.predictions?.[0].dish).toBe("kebab");
  });
  it.each([
    ["a new photo", { type: "PHOTO_LOADED", photo: photo("blob:p2") }],
    ["a crop change", { type: "CROP_CHANGED", crop: { x: 0, y: 0, w: 0.5, h: 0.5 } }],
    ["edit crop", { type: "EDIT_CROP" }],
    ["reset", { type: "RESET" }],
  ] as const)("ignores the old prediction after %s", (_, action) => {
    const s = analyzing();
    const old = s.seq;
    const next = reducer(s, action);
    expect(reducer(next, { type: "PREDICTED", seq: old, outcome: ok })).toBe(next);
  });
  it("ignores the old prediction after a second analysis", () => {
    const s = analyzing();
    const again = reducer(reducer(s, { type: "EDIT_CROP" }), { type: "ANALYZE", sentCrop: photo("blob:c2") });
    expect(reducer(again, { type: "PREDICTED", seq: s.seq, outcome: ok })).toBe(again);
    expect(reducer(again, { type: "PREDICTED", seq: again.seq, outcome: { kind: "not-ready" } }).stage).toBe("not-ready");
  });
  it("maps outcomes to stages", () => {
    const s = analyzing();
    const p = (outcome: Parameters<typeof reducer>[1] & { type: "PREDICTED" }) => reducer(s, outcome);
    expect(p({ type: "PREDICTED", seq: s.seq, outcome: { ...ok, uncertain: true } }).stage).toBe("uncertain");
    expect(p({ type: "PREDICTED", seq: s.seq, outcome: { kind: "network" } })).toMatchObject({ stage: "error", error: "network" });
    expect(p({ type: "PREDICTED", seq: s.seq, outcome: { kind: "server", status: 500 } }).error).toBe("server");
    expect(p({ type: "PREDICTED", seq: s.seq, outcome: { kind: "aborted" } })).toBe(s);
  });
});

describe("flow reducer: the user chooses the kind", () => {
  const confirmed = (dish: "kebab" | "dessert" | "pizza") => {
    const s = analyzing();
    return reducer(reducer(s, { type: "PREDICTED", seq: s.seq, outcome: ok }), { type: "CONFIRM_DISH", dish });
  };
  it("kebab and dessert ask for the kind and preselect nothing", () => {
    for (const dish of ["kebab", "dessert"] as const) {
      const s = confirmed(dish);
      expect(s.stage).toBe("variant");
      expect(s.variant).toBeNull();
      expect(reducer(s, { type: "CONFIRM_VARIANT" })).toBe(s);               // no kind -> nothing happens
      expect(reducer(s, { type: "PICK_VARIANT", variant: "pizza" })).toBe(s);  // not a kind of this dish
    }
  });
  it("pizza goes straight to ingredients", () => {
    expect(confirmed("pizza")).toMatchObject({ stage: "ingredients", variant: null });
  });
  it("an old ingredient response cannot replace the new kind", () => {
    let s = reducer(confirmed("kebab"), { type: "PICK_VARIANT", variant: "skewered" });
    s = reducer(s, { type: "CONFIRM_VARIANT" });
    const oldSeq = s.ingredientsSeq;
    s = reducer(s, { type: "CHANGE_VARIANT" });
    s = reducer(reducer(s, { type: "PICK_VARIANT", variant: "doner_shawarma" }), { type: "CONFIRM_VARIANT" });
    const stale = reducer(s, { type: "INGREDIENTS", seq: oldSeq, outcome: { kind: "error" } });
    expect(stale).toBe(s);
    const reload = reducer(s, { type: "RELOAD_INGREDIENTS" });   // language change
    expect(reducer(reload, { type: "INGREDIENTS", seq: s.ingredientsSeq, outcome: { kind: "error" } })).toBe(reload);
  });
  it("back returns to the result, or to not-ready for a manual pick", () => {
    expect(reducer(confirmed("kebab"), { type: "BACK_TO_RESULT" }).stage).toBe("result");
    const s = analyzing();
    const nr = reducer(reducer(s, { type: "PREDICTED", seq: s.seq, outcome: { kind: "not-ready" } }), { type: "CONFIRM_DISH", dish: "pizza" });
    expect(reducer(nr, { type: "BACK_TO_RESULT" }).stage).toBe("not-ready");
  });
  it("a bad file never replaces the current photo", () => {
    const s = reducer(initialState, { type: "PHOTO_LOADED", photo: photo() });
    const r = reducer(s, { type: "FILE_REJECTED", code: "unsupported_format" });
    expect(r.photo?.url).toBe("blob:p1");
    expect(r.fileError).toBe("unsupported_format");
  });
});

describe("api client", () => {
  const res = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  const signal = () => new AbortController().signal;

  it("sends exactly the given blob and parses a result", async () => {
    const blob = new Blob(["crop"], { type: "image/jpeg" });
    const f = vi.fn(async () => res(200, okBody));
    expect(await predict(blob, signal(), f)).toMatchObject({ kind: "ok", uncertain: false, threshold: 0.6 });
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/predict");
    expect(init.body).toBe(blob);
  });
  it.each([
    [503, { code: "MODEL_NOT_READY", detail: "no model" }, "not-ready"],
    [415, { code: "unsupported_format" }, "invalid"],
    [422, { code: "corrupt_image" }, "invalid"],
    [500, { detail: "boom" }, "server"],
    [503, { code: "OTHER" }, "server"],
    [200, { predictions: PREDS.slice(0, 2), uncertain: false, threshold: 0.6 }, "server"],
    [200, { predictions: [PREDS[1], PREDS[0], PREDS[2]], uncertain: false, threshold: 0.6 }, "server"],
    [200, { predictions: [{ class: "sushi", confidence: 0.9 }, PREDS[1], PREDS[2]], uncertain: false, threshold: 0.6 }, "server"],
    [200, { ...okBody, threshold: "0.6" }, "server"],
  ])("status %i %j -> %s", async (status, body, kind) => {
    expect((await predict(new Blob(["x"]), signal(), async () => res(status, body))).kind).toBe(kind);
  });
  it("network failure and abort", async () => {
    expect((await predict(new Blob(["x"]), signal(), async () => { throw new TypeError("offline"); })).kind).toBe("network");
    const c = new AbortController();
    c.abort();
    const f = async () => { throw new DOMException("aborted", "AbortError"); };
    expect((await predict(new Blob(["x"]), c.signal, f)).kind).toBe("aborted");
  });
  it("parsePrediction rejects duplicates and NaN", () => {
    expect(parsePrediction({ ...okBody, predictions: [PREDS[0], PREDS[0], PREDS[2]] })).toBeNull();
    expect(parsePrediction({ ...okBody, predictions: [{ class: "kebab", confidence: Number.NaN }, PREDS[1], PREDS[2]] })).toBeNull();
  });
  const ing = { dish: "kebab", variant: "skewered", name: "Kebab · Shish", ingredients: ["Meat"],
    disclaimer: "Typical ingredients; not identified from your photo.", variant_note: "You choose the kind.",
    sources: [{ url: "https://en.wikipedia.org/wiki/Shish_kebab", title: "Shish kebab" }], translated: false };
  it("ingredients: grouped dishes need the user's kind; responses are checked", async () => {
    const f = vi.fn(async () => res(200, ing));
    expect((await fetchIngredients("kebab", null, "en", signal(), f)).kind).toBe("error");
    expect(f).not.toHaveBeenCalled();
    const r = await fetchIngredients("kebab", "skewered", "ko", signal(), f);
    expect(r.kind).toBe("ok");
    expect((f.mock.calls[0] as unknown as [string])[0]).toBe("/api/ingredients/kebab?lang=ko&variant=skewered");
    const bad = async () => res(200, { ...ing, sources: [{ url: "http://insecure", title: "x" }] });
    expect((await fetchIngredients("kebab", "skewered", "en", signal(), bad)).kind).toBe("error");
    const other = async () => res(200, { ...ing, variant: "doner_shawarma" });
    expect((await fetchIngredients("kebab", "skewered", "en", signal(), other)).kind).toBe("error");
  });
});

describe("crop math", () => {
  it("clamps, moves and resizes inside the image", () => {
    expect(clampRect({ x: -1, y: 2, w: 3, h: 0 })).toEqual({ x: 0, y: 1 - MIN_SIZE, w: 1, h: MIN_SIZE });
    const moved = moveRect(DEFAULT_RECT, 1, 1);
    expect([moved.x, moved.y, moved.w, moved.h].map((v) => +v.toFixed(9))).toEqual([0.1, 0.1, 0.9, 0.9]);
    const r = resizeCorner(DEFAULT_RECT, "nw", 2, 2);
    expect(r.w).toBeCloseTo(MIN_SIZE);
    expect(r.x + r.w).toBeCloseTo(0.95);
    expect(resizeCorner(DEFAULT_RECT, "se", 1, 1)).toEqual({ x: 0.05, y: 0.05, w: 0.95, h: 0.95 });
  });
  it("converts to pixels and limits the output size", () => {
    expect(toPixels({ x: 0.5, y: 0.5, w: 0.5, h: 0.5 }, 801, 601)).toEqual({ sx: 401, sy: 301, sw: 400, sh: 300 });
    expect(outputSize(4000, 3000)).toEqual({ width: 2048, height: 1536 });
    expect(outputSize(300, 200)).toEqual({ width: 300, height: 200 });
  });
});

describe("i18n", () => {
  it("English and Korean have the same keys, incl. every dish and kind", () => {
    expect(Object.keys(MESSAGES.ko).sort()).toEqual(Object.keys(MESSAGES.en).sort());
    for (const d of DISHES) expect(MESSAGES.en).toHaveProperty(`dish.${d}`);
    for (const [d, vs] of Object.entries(VARIANTS)) for (const v of vs ?? []) expect(MESSAGES.ko).toHaveProperty(`variant.${d}.${v}`);
    expect(translate("en", "result.ask", { dish: "Pizza" })).toBe("Is this Pizza?");
  });
  it("defaults to English and survives blocked storage", () => {
    expect(loadLang(undefined)).toBe("en");
    expect(loadLang({ getItem: () => "ko" })).toBe("ko");
    expect(loadLang({ getItem: () => "fr" })).toBe("en");
    expect(loadLang({ getItem: () => { throw new Error("blocked"); } })).toBe("en");
    expect(() => saveLang({ setItem: () => { throw new Error("blocked"); } }, "ko")).not.toThrow();
  });
});

describe("upload checks", () => {
  const bytes = (...b: number[]) => new Uint8Array([...b, ...new Array(16).fill(0)]);
  it("sniffs the real format", () => {
    expect(sniff(bytes(0xff, 0xd8, 0xff))).toBe("JPEG");
    expect(sniff(bytes(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a))).toBe("PNG");
    expect(sniff(bytes(0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0, 0x57, 0x45, 0x42, 0x50))).toBe("WEBP");
    expect(sniff(bytes(0x47, 0x49, 0x46))).toBeNull();
  });
  it("checks size and type", async () => {
    expect(await checkFile(new Blob([]))).toEqual({ ok: false, code: "empty_file" });
    expect(await checkFile(new Blob([new Uint8Array(10 * 1024 * 1024 + 1)]))).toEqual({ ok: false, code: "file_too_large" });
    expect(await checkFile(new Blob(["<html>"]))).toEqual({ ok: false, code: "unsupported_format" });
    expect(await checkFile(new Blob([bytes(0xff, 0xd8, 0xff)]))).toEqual({ ok: true, format: "JPEG" });
    expect(checkDimensions(9000, 10)).toBe("image_too_large");
    expect(checkDimensions(6000, 5000)).toBe("image_too_large");
    expect(checkDimensions(0, 10)).toBe("corrupt_image");
    expect(checkDimensions(4000, 3000)).toBeNull();
  });
});
